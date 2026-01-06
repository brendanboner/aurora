# ECR Deployment Guide

This guide covers deploying Aurora on EC2 using **pre-built Docker images from AWS Elastic Container Registry (ECR)**. This is the **recommended production deployment method** as it's faster, more reliable, and doesn't require building on the server.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Verify ECR Images](#verify-ecr-images)
3. [Configure EC2 for ECR Access](#configure-ec2-for-ecr-access)
4. [Deploy on EC2](#deploy-on-ec2)
5. [Verify Deployment](#verify-deployment)
6. [Update Deployment](#update-deployment)
7. [Ongoing Operations](#ongoing-operations)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### On Your Local Machine

✅ **You need**:
- Git repository cloned locally
- Docker installed and running with buildx support
- AWS CLI configured with credentials (for ECR operations)
- Access to create ECR repositories
- Permissions to push images to ECR

### On EC2 Server

✅ **Complete the [EC2 Base Setup](./01-EC2-Base-Setup.md) first**

You should have:
- t4g.xlarge instance with Docker and buildx installed
- IAM role attached with ECR + SSM permissions
- Security groups configured (port 80 or 80+443)
- 200GB data volume mounted at `/data`
- Domain/CloudFront configured (optional)

---

## Verify ECR Images

Before deploying to EC2, verify that Docker images are available in ECR.

### 1. Verify ECR Repositories Exist

ECR repositories should already be created in your AWS account:

- `aurora-auth`
- `aurora-backend`
- `aurora-curator`
- `aurora-digester`
- `aurora-retriever`
- `aurora-frontend`
- `aurora-nginx`

**Check existing repositories:**
```bash
aws ecr describe-repositories --region us-east-1 | grep repositoryName
```

If repositories don't exist, they need to be created by your DevOps/infrastructure team before proceeding.

### 2. Verify Images Exist in ECR

**In production, images should already be built and pushed to ECR** by your CI/CD pipeline or development team. Verify they exist:

```bash
# Check for images in ECR
aws ecr describe-images --repository-name aurora-auth --region us-east-1
aws ecr describe-images --repository-name aurora-backend --region us-east-1
aws ecr describe-images --repository-name aurora-nginx --region us-east-1
```

**Or check in AWS Console**: **ECR → Repositories → aurora-auth → Images**

You should see images tagged with `latest` or specific version tags.

**Note**: If images don't exist, contact your development team or CI/CD pipeline owner. Images must be built and pushed to ECR before you can deploy to EC2.

---

## Configure EC2 for ECR Access

### 1. Connect to EC2 Instance

```bash
# Via SSM (recommended)
aws ssm start-session --target i-YOUR_INSTANCE_ID

# Or SSH (if port 22 is open)
ssh -i ~/.ssh/your-key.pem ec2-user@YOUR_EC2_IP
```
ssh -i ~/.ssh/your-key.pem ec2-user@YOUR_EC2_PUBLIC_IP
```

### 2. Create Deployment Directory

```bash
# Create directory for production files
mkdir -p ~/aurora-prod
cd ~/aurora-prod
```

### 3. Download Production Files

You need these files from the repository on EC2:

**Option A: Clone Repository (Minimal)**

```bash
# Clone repo (you only need prod-deployment folder)
git clone --depth 1 git@github.com:extremenetworks/octo-rapid-aurora.git
cd octo-rapid-aurora/prod-deployment
```

**Option B: Manual File Transfer (No Git)**

```bash
# From your local machine, copy prod-deployment folder
scp -i ~/.ssh/your-key.pem -r prod-deployment/ ec2-user@YOUR_EC2_IP:~/aurora-prod/

# Then on EC2
cd ~/aurora-prod/prod-deployment
```

### 4. Create Environment File

```bash
# Copy template
cp .env.prod .env

# Edit configuration
nano .env
```

### 5. Configure Required Values

Update these **REQUIRED** values in `.env`:

#### ECR Registry

```bash
ECR_REGISTRY=YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
AWS_REGION=us-east-1
```

#### Deployment Domain

Choose based on your method:

**Method 1: CloudFront (Recommended)**
```bash
DEPLOYMENT_DOMAIN=d1234abcd5678.cloudfront.net
USE_HTTPS=true
# Skip SSL_EMAIL
```

**Method 2: Let's Encrypt (Custom Domain)**
```bash
DEPLOYMENT_DOMAIN=app.yourcompany.com
USE_HTTPS=true
SSL_EMAIL=admin@yourcompany.com
```

#### Database Passwords

```bash
POSTGRES_PASSWORD=your_strong_postgres_password
NEO4J_PASSWORD=your_strong_neo4j_password
RABBITMQ_PASSWORD=your_strong_rabbitmq_password
```

#### Azure OpenAI

```bash
AZURE_OPENAI_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

#### AWS Cognito

```bash
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=xxxxxxxxxx
COGNITO_APP_CLIENT_SECRET=xxxxxxxxxx
COGNITO_DOMAIN=your-app.auth.us-east-1.amazoncognito.com
```

**Update Cognito callback URL**:
- URL: `https://{DEPLOYMENT_DOMAIN}/api/auth/callback`

#### Web Scraping

```bash
WFA_CAUSEWAY_USERNAME=your_username
WFA_CAUSEWAY_PASSWORD=your_password
```

### 6. Verify Configuration

```bash
# Check for CHANGE_ME values
grep -n "CHANGE_ME" .env

# Verify ECR registry is set
grep "ECR_REGISTRY" .env
```

---

## Deploy on EC2

### 1. Login to ECR (Usually Not Needed)

**If you followed the [EC2 Base Setup](./01-EC2-Base-Setup.md) and attached an IAM role with ECR permissions**, Docker will automatically authenticate to ECR when pulling images. **You can skip this step.**

**Only needed if**:
- You didn't attach an IAM role, OR
- You see authentication errors when pulling images

```bash
# Manual ECR login (only if IAM role is not configured)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
```

### 2. Initial Deployment

Using the Makefile (recommended):

```bash
# From ~/aurora-prod/prod-deployment/ (or wherever you put the files)

# Deploy everything (sets up backups + starts services)
make deploy
```

**Or manually**:

```bash
# Pull images and start services
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

**This will**:
- Pull pre-built images from ECR (much faster than building!)
- Initialize databases with migrations
- Start all services
- Set up SSL certificates (if using Let's Encrypt)
- Configure automated backups

### 3. Monitor Startup

```bash
# Watch logs (Ctrl+C to exit)
make logs

# Or directly
docker-compose -f docker-compose.prod.yml logs -f
```

**Look for**:
- ✅ All images pulled successfully
- ✅ Databases initialized
- ✅ Services starting up
- ✅ Nginx configuration successful

### 4. Check Service Status

```bash
# Using Makefile
make status

# Or directly
docker-compose -f docker-compose.prod.yml ps
```

**All services should show "Up" or "Up (healthy)"**

---

## Verify Deployment

### 1. Check Container Status

```bash
make status
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
frontend            Exited (0)          # Normal - builds and exits
```

### 2. Test Application Access

**Browser**:
- Navigate to: `https://your-domain.com`
- Should see Aurora login page
- Test login with Cognito

**Command Line**:
```bash
# From local machine
curl -I https://your-domain.com

# Should return: HTTP/2 200
```

### 3. Verify Databases

```bash
# Check PostgreSQL
docker-compose -f docker-compose.prod.yml exec postgres psql -U aurora -d aurora -c "SELECT version();"

# Check Neo4j (via SSH tunnel from local machine)
ssh -i ~/.ssh/your-key.pem \
  -L 7474:localhost:7474 \
  -L 7687:localhost:7687 \
  -L 15672:localhost:15672 \
  ec2-user@ec2.ip.address

# Browse to: http://localhost:7474
```

### 4. Check Logs for Errors

```bash
# View recent logs
make logs

# Check specific service
docker-compose -f docker-compose.prod.yml logs --tail=50 backend
```

---

## Update Deployment

When new images are pushed to ECR (by your CI/CD pipeline or development team), update the deployment on EC2:

### Pull Latest Images and Restart

```bash
# SSH into EC2
ssh -i ~/.ssh/your-key.pem ec2-user@YOUR_EC2_IP
cd ~/aurora-prod/prod-deployment

# Update services (creates backup, pulls latest, restarts)
make update
```

The `make update` command will:
1. Create a backup first (safety measure)
2. Pull latest images from ECR
3. Restart all services with new images

**Or manually**:

```bash
# Just pull images without restarting
make pull

# Or pull and restart in one step
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d

# Monitor restart
make logs
```

---

## Ongoing Operations

### Using Makefile Commands

The `prod-deployment/Makefile` provides all the commands you need:

```bash
# View all available commands
make help

# Deployment
make deploy        # Full deployment (setup backups + start services)
make start         # Start all services
make stop          # Stop all services
make restart       # Restart all services
make update        # Pull latest images and restart

# Monitoring
make status        # Check service status
make logs          # View logs (all services)
make logs-nginx    # View nginx logs
make logs-auth     # View auth logs
make logs-backend  # View backend logs
make health        # Check service health
make ps            # List running containers
make disk          # Check disk usage

# Database
make migrate       # Run database migrations
make migrate-status # Show migration status

# Backups
make backup        # Run backup now
make backup-setup  # Setup automated backups
make backup-status # Check backup status
make backup-logs   # View backup logs

# Maintenance
make pull          # Pull latest images from ECR
make clean         # Remove stopped containers
```

### Common Operations

**View service logs:**
```bash
make logs              # All services (follow mode)
make logs-backend      # Backend only
make logs-nginx        # Nginx only
```

**Check health:**
```bash
make status            # Service status
make health            # Endpoint health checks
make ps                # Running containers
```

**Disk management:**
```bash
make disk              # Check disk usage
make clean             # Clean up stopped containers
```

### Database Operations

**Run migrations:**
```bash
make migrate           # Apply pending migrations
make migrate-status    # Check migration state
```

**Backups:**
```bash
# Manual backup
make backup

# Check backup status
make backup-status

# View backup logs
make backup-logs

# Setup automated daily backups
make backup-setup

# Restore from backup (manual)
./scripts/restore-backup.sh ~/backups/aurora/backup_20241223_120000.tar.gz
```

---

## Troubleshooting

### ECR Login Fails

**Problem**: "authentication token has expired" or "unauthorized"

**Solution**:

```bash
# Re-login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# Verify IAM role attached to EC2
aws sts get-caller-identity

# Check ECR permissions
aws ecr describe-repositories --region us-east-1
```

### Image Pull Fails

**Problem**: "image not found" or "manifest unknown"

**Solution**:

```bash
# Verify image exists in ECR
aws ecr list-images --repository-name aurora-backend --region us-east-1

# Check image tag in docker-compose.prod.yml
grep "image:" docker-compose.prod.yml

# If image doesn't exist, contact your dev team or CI/CD pipeline owner
# Images should be built and pushed to ECR before deployment
```

### Service Won't Start After Update

**Problem**: Service fails after pulling new image

**Solution**:

```bash
# Check logs for specific service
docker-compose -f docker-compose.prod.yml logs --tail=100 backend

# Rollback to previous image
docker-compose -f docker-compose.prod.yml down
# Edit docker-compose.prod.yml to use previous tag
docker-compose -f docker-compose.prod.yml up -d

# Or pull previous image manually
docker pull YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/aurora-backend:previous-tag
```

### ECR Storage Costs

**Problem**: Too many old images in ECR

**Solution**: Set up lifecycle policies

```bash
# Create lifecycle policy (keep only last 5 images)
aws ecr put-lifecycle-policy --repository-name aurora-backend --lifecycle-policy-text '{
  "rules": [{
    "rulePriority": 1,
    "description": "Keep last 5 images",
    "selection": {
      "tagStatus": "any",
      "countType": "imageCountMoreThan",
      "countNumber": 5
    },
    "action": { "type": "expire" }
  }]
}'
```

### Network Issues Between Services

**Problem**: Service A can't connect to Service B

**Solution**:

```bash
# Check all services on same network
docker network ls
docker network inspect prod-deployment_aurora-network

# Verify service names resolve
docker-compose -f docker-compose.prod.yml exec backend ping postgres -c 3

# Restart networking
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

### SSL Certificate Issues

**Problem**: Let's Encrypt certificate fails to renew

**Solution**:

```bash
# Check nginx logs
docker-compose -f docker-compose.prod.yml logs nginx

# Force certificate renewal
docker-compose -f docker-compose.prod.yml exec nginx certbot renew --force-renewal

# Verify certificate
docker-compose -f docker-compose.prod.yml exec nginx certbot certificates
```

### High Memory Usage

**Problem**: EC2 instance running out of memory

**Solution**:

```bash
# Check which service is using memory
docker stats --no-stream

# Restart heavy service
docker-compose -f docker-compose.prod.yml restart neo4j

# Consider upgrading EC2 instance type
# Or add swap (see EC2 Base Setup guide)
```

---

## Performance Optimization

### Image Pull Optimization

Use Docker layer caching:

```bash
# Configure Docker daemon on EC2
sudo tee -a /etc/docker/daemon.json > /dev/null <<EOF
{
  "max-concurrent-downloads": 10,
  "max-concurrent-uploads": 10
}
EOF

sudo systemctl restart docker
```

### ECR Transfer Acceleration

Use VPC endpoints for faster ECR access:

1. Go to **VPC Console** → **Endpoints**
2. Create endpoint for `com.amazonaws.us-east-1.ecr.dkr`
3. Create endpoint for `com.amazonaws.us-east-1.ecr.api`
4. Associate with your VPC

---

## Advantages of ECR Deployment

✅ **Faster deployments**: No building on EC2, just pull and run  
✅ **Consistent images**: Same images from dev to prod  
✅ **Rollback capability**: Easy to revert to previous image tags  
✅ **CI/CD friendly**: Integrates with GitHub Actions, CodePipeline  
✅ **Better resource usage**: EC2 doesn't need CPU/memory for builds  
✅ **Version control**: Track image versions with tags  

---

## Next Steps

- ✅ Application deployed with ECR images
- 🔄 Set up automated deployments with GitHub Actions
- 📊 Configure monitoring: See [MONITORING_SYSTEM.md](../../doc/MONITORING_SYSTEM.md)
- 🔐 Review security: See [PRODUCTION_SETUP.md](../../doc/PRODUCTION_SETUP.md)
- 📖 Explore features: See [Quickstart Guide](../../doc/QUICKSTART.md)

---

## Related Documentation

- [ECR User Guide](https://docs.aws.amazon.com/ecr/)
- [Docker Compose Production Guide](https://docs.docker.com/compose/production/)
- [AWS IAM Roles for EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html)
