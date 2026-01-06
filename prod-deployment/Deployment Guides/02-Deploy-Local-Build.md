# Local Build Deployment Guide

This guide covers deploying Aurora on EC2 by **cloning the repository and building images locally** on the server. This method is useful for development, testing, or when you don't have an ECR registry set up.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Setup GitHub Deploy Key](#setup-github-deploy-key)
3. [Clone Repository](#clone-repository)
4. [Configure Environment](#configure-environment)
5. [Deploy Application](#deploy-application)
6. [Verify Deployment](#verify-deployment)
7. [Ongoing Operations](#ongoing-operations)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

✅ **Complete the [EC2 Base Setup](./01-EC2-Base-Setup.md) first**

You should have:
- EC2 instance running with Docker installed
- Security groups configured (ports 80, 443, 22)
- SSH access to the instance
- Domain pointed to EC2 (for Let's Encrypt) **OR** CloudFront distribution setup

---

## Setup GitHub Deploy Key

Deploy keys allow the EC2 instance to clone your private repository without storing personal credentials.

### 1. Generate SSH Key on EC2

```bash
# Connect via SSM (recommended)
aws ssm start-session --target i-YOUR_INSTANCE_ID

# Or SSH (if port 22 is open)
ssh -i ~/.ssh/your-key.pem ec2-user@YOUR_EC2_IP

# Generate deploy key (no passphrase - press Enter twice)
ssh-keygen -t ed25519 -C "aurora-ec2-deploy" -f ~/.ssh/aurora_deploy_key

# Display public key
cat ~/.ssh/aurora_deploy_key.pub
```

**Copy the entire public key output** (starts with `ssh-ed25519 ...`)

### 2. Add Deploy Key to GitHub

1. Go to your repository: `https://github.com/extremenetworks/octo-rapid-aurora`
2. Click **Settings** → **Deploy keys** → **Add deploy key**
3. **Title**: `Aurora EC2 Production`
4. **Key**: Paste the public key from above
5. ✅ **Allow write access**: ❌ Leave unchecked (read-only is safer)
6. Click **Add key**

### 3. Configure SSH for GitHub

```bash
# Create SSH config on EC2
cat > ~/.ssh/config <<EOF
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/aurora_deploy_key
  StrictHostKeyChecking no
EOF

chmod 600 ~/.ssh/config

# Test connection
ssh -T git@github.com
```

**Expected output:**
```
Hi extremenetworks/octo-rapid-aurora! You've successfully authenticated, but GitHub does not provide shell access.
```

---

## Clone Repository

### 1. Clone the Repository

```bash
# Clone to home directory
cd ~
git clone git@github.com:extremenetworks/octo-rapid-aurora.git

# Navigate to prod-deployment folder
cd octo-rapid-aurora/prod-deployment
```

### 2. Verify Repository Structure

```bash
ls -la
```

**Expected structure:**
```
.env.prod                    # Environment template
docker-compose.build.yml     # Local build configuration
docker-compose.prod.yml      # ECR configuration
Deployment Guides/           # This guide!
migrations/                  # Database migrations
scripts/                     # Utility scripts
Makefile                     # Deployment commands
README.md
```

---

## Configure Environment

### 1. Create Environment File

```bash
# Copy template
cp .env.prod .env

# Edit configuration
nano .env
```

### 2. Required Configuration

Update these **REQUIRED** values in `.env`:

#### Deployment Domain

Choose based on your deployment method:

**Method 1: CloudFront (Recommended)**
```bash
DEPLOYMENT_DOMAIN=d1234abcd5678.cloudfront.net  # Your CloudFront URL
USE_HTTPS=true
# Skip SSL_EMAIL (CloudFront handles SSL)
```

**Method 2: Let's Encrypt (Custom Domain)**
```bash
DEPLOYMENT_DOMAIN=app.yourcompany.com           # Your domain
USE_HTTPS=true
SSL_EMAIL=admin@yourcompany.com                 # For cert renewal notifications
```

**Note**: HTTPS is required because AWS Cognito authentication requires secure callback URLs.

#### Database Passwords

```bash
# PostgreSQL
POSTGRES_PASSWORD=your_strong_postgres_password_here

# Neo4j
NEO4J_PASSWORD=your_strong_neo4j_password_here

# RabbitMQ
RABBITMQ_PASSWORD=your_strong_rabbitmq_password_here
```

#### Azure OpenAI

```bash
AZURE_OPENAI_API_KEY=your_azure_openai_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

#### AWS Cognito

```bash
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=xxxxxxxxxxxxxxxxxx
COGNITO_APP_CLIENT_SECRET=xxxxxxxxxxxxxxxxxx
COGNITO_DOMAIN=your-app.auth.us-east-1.amazoncognito.com
AWS_REGION=us-east-1
```

**Important**: Update Cognito callback URL to match your `DEPLOYMENT_DOMAIN`:
- Go to AWS Cognito Console → App Clients → Settings
- Set callback URL: `https://{DEPLOYMENT_DOMAIN}/api/auth/callback`

#### Web Scraping Credentials

```bash
WFA_CAUSEWAY_USERNAME=your_username
WFA_CAUSEWAY_PASSWORD=your_password
```

### 3. Skip ECR Configuration

Since you're building locally, you **don't need** to set:
- ❌ `ECR_REGISTRY` - Leave empty or default value

### 4. Verify Configuration

```bash
# Check for CHANGE_ME values
grep -n "CHANGE_ME" .env

# Should show only commented examples, no active values
```

---

## Deploy Application

### 1. Initial Deployment

```bash
# Still in ~/octo-rapid-aurora/prod-deployment/

# Build and start all services
docker-compose -f docker-compose.build.yml up --build -d
```

**This will**:
- Build all Docker images from source (takes 10-20 minutes first time)
- Create database volumes and initialize schemas
- Start all services
- Set up SSL certificates (if using Let's Encrypt)

### 2. Monitor Initial Startup

```bash
# Watch logs (Ctrl+C to exit)
docker-compose -f docker-compose.build.yml logs -f

# Or check specific service
docker-compose -f docker-compose.build.yml logs -f frontend
docker-compose -f docker-compose.build.yml logs -f nginx
```

**Look for**:
- ✅ Frontend: "Compiled successfully"
- ✅ Nginx: "Configuration test successful"
- ✅ Auth: "Application startup complete"
- ✅ Backend: "Application startup complete"

### 3. Wait for Services to be Healthy

```bash
# Check service status
docker-compose -f docker-compose.build.yml ps
```

**All services should show "Up" or "Up (healthy)"**

---

## Verify Deployment

### 1. Check Service Health

```bash
# Verify all containers are running
docker-compose -f docker-compose.build.yml ps
```

Expected output:
```
NAME                STATUS              PORTS
auth                Up (healthy)
backend             Up (healthy)
curator             Up
digester            Up
retriever           Up
postgres            Up (healthy)
neo4j               Up (healthy)
rabbitmq            Up (healthy)
redis               Up (healthy)
nginx               Up (healthy)        0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
frontend            Exited (0)          # This is normal - builds and exits
```

### 2. Test Application Access

**Browser Test**:
- Navigate to: `https://your-domain.com` or `https://your-cloudfront-url.cloudfront.net`
- Should see Aurora login page
- Try logging in with Cognito credentials

**Command Line Test**:
```bash
# From your local machine
curl -I https://your-domain.com

# Should return: HTTP/2 200
```

### 3. Verify Database Connections

```bash
# Check PostgreSQL
docker-compose -f docker-compose.build.yml exec postgres psql -U aurora -d aurora -c "SELECT COUNT(*) FROM users;"

# Check Neo4j (through SSH tunnel)
# From your local machine:
ssh -L 7474:localhost:7474 -L 7687:localhost:7687 -L 15672:localhost:15672 ec2-user@YOUR_EC2_IP
# Then browse to: http://localhost:7474
```

### 4. Check Application Logs

```bash
# View logs for any errors
docker-compose -f docker-compose.build.yml logs --tail=100 backend
docker-compose -f docker-compose.build.yml logs --tail=100 auth
docker-compose -f docker-compose.build.yml logs --tail=100 nginx
```

---

## Ongoing Operations

### Update Application (Pull Latest Code)

```bash
cd ~/octo-rapid-aurora

# Pull latest changes
git pull origin main  # or your branch

# Rebuild and restart
cd prod-deployment
docker-compose -f docker-compose.build.yml up --build -d

# Monitor restart
docker-compose -f docker-compose.build.yml logs -f
```

### View Logs

```bash
# All services
docker-compose -f docker-compose.build.yml logs -f

# Specific service
docker-compose -f docker-compose.build.yml logs -f backend

# Last 100 lines
docker-compose -f docker-compose.build.yml logs --tail=100
```

### Restart Services

```bash
# Restart all services
docker-compose -f docker-compose.build.yml restart

# Restart specific service
docker-compose -f docker-compose.build.yml restart backend
```

### Stop Application

```bash
# Stop all services (keeps data)
docker-compose -f docker-compose.build.yml stop

# Stop and remove containers (keeps data)
docker-compose -f docker-compose.build.yml down

# Nuclear option - removes everything including data!
docker-compose -f docker-compose.build.yml down -v  # ⚠️ Deletes all data!
```

### Database Backups

```bash
# Manual backup
docker-compose -f docker-compose.build.yml exec postgres pg_dump -U aurora aurora > backup_$(date +%Y%m%d).sql

# Restore from backup
cat backup_20241223.sql | docker-compose -f docker-compose.build.yml exec -T postgres psql -U aurora aurora
```

### Check Disk Space

```bash
# Check disk usage
df -h

# Check Docker disk usage
docker system df

# Clean up unused images/containers
docker system prune -a
```

---

## Troubleshooting

### Build Fails with Memory Issues

**Problem**: Build fails with "Killed" or memory errors

**Solution**: Increase EC2 instance size or add swap:

```bash
# Add 4GB swap
sudo dd if=/dev/zero of=/swapfile bs=1M count=4096
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Git Pull Fails (Permission Denied)

**Problem**: `git pull` fails with "Permission denied (publickey)"

**Solution**: Verify deploy key setup:

```bash
# Test GitHub connection
ssh -T git@github.com

# If fails, regenerate deploy key
ssh-keygen -t ed25519 -C "aurora-ec2-deploy" -f ~/.ssh/aurora_deploy_key
cat ~/.ssh/aurora_deploy_key.pub
# Add new key to GitHub
```

### Frontend Build Fails

**Problem**: Frontend container shows webpack errors

**Solution**: Check Node.js memory and rebuild:

```bash
# Increase Node memory limit in docker-compose.build.yml
# Add to frontend service environment:
NODE_OPTIONS: "--max_old_space_size=4096"

# Rebuild
docker-compose -f docker-compose.build.yml up --build -d frontend
```

### SSL Certificate Issues (Let's Encrypt)

**Problem**: Nginx fails to start, SSL errors

**Solution**:

```bash
# Check nginx logs
docker-compose -f docker-compose.build.yml logs nginx

# Verify domain DNS
nslookup your-domain.com

# Try HTTP first (comment out SSL in nginx config temporarily)
# Or use CloudFront instead
```

### Services Won't Start (Port Conflicts)

**Problem**: "Port already in use" errors

**Solution**:

```bash
# Check what's using ports
sudo netstat -tulpn | grep :80
sudo netstat -tulpn | grep :443

# Stop conflicting services
sudo systemctl stop httpd  # Apache
sudo systemctl stop nginx  # System nginx
```

### Database Connection Errors

**Problem**: Services can't connect to postgres/neo4j

**Solution**:

```bash
# Check database health
docker-compose -f docker-compose.build.yml ps postgres neo4j

# View database logs
docker-compose -f docker-compose.build.yml logs postgres
docker-compose -f docker-compose.build.yml logs neo4j

# Restart databases
docker-compose -f docker-compose.build.yml restart postgres neo4j
```

### Check Service Health

```bash
# Detailed health check
docker inspect <container_name> | grep -A 10 Health

# Manual health check
docker-compose -f docker-compose.build.yml exec backend curl http://localhost:8000/
```

---

## Performance Optimization

### After Initial Deployment

1. **Monitor Resource Usage**:
   ```bash
   docker stats
   ```

2. **Optimize Docker Image Cache**:
   ```bash
   # After successful builds, clean up build cache
   docker builder prune
   ```

3. **Set Up Log Rotation**:
   ```bash
   # Configure Docker log limits in /etc/docker/daemon.json
   sudo tee /etc/docker/daemon.json > /dev/null <<EOF
   {
     "log-driver": "json-file",
     "log-opts": {
       "max-size": "10m",
       "max-file": "3"
     }
   }
   EOF
   
   sudo systemctl restart docker
   ```

---

## Next Steps

- ✅ Application deployed and running
- 📊 Set up monitoring: Check [MONITORING_SYSTEM.md](../../doc/MONITORING_SYSTEM.md)
- 🔄 Configure automated backups: See [Database Backups](#database-backups)
- 🔐 Review security: See [Production Setup](../../doc/PRODUCTION_SETUP.md)
- 📖 Explore features: See [Quickstart Guide](../../doc/QUICKSTART.md)

---

## Migration to ECR

Once you're comfortable with the deployment, you can migrate to ECR for faster updates:

1. Build images locally and push to ECR (see root Makefile)
2. Switch to `docker-compose.prod.yml` on EC2
3. No more building on EC2 - just pull and run!

See [ECR Deployment Guide](./03-Deploy-ECR.md) for details.
