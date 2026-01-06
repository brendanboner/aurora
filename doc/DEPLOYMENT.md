# Aurora Production Deployment Guide

This guide covers deploying Aurora to an AWS EC2 instance with Docker Compose, nginx reverse proxy, and Let's Encrypt SSL certificates.

## Table of Contents

- [Prerequisites](#prerequisites)
- [EC2 Instance Setup](#ec2-instance-setup)
- [Domain Configuration](#domain-configuration)
- [Application Deployment](#application-deployment)
- [SSL Certificate Setup](#ssl-certificate-setup)
- [Post-Deployment](#post-deployment)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Accounts & Services

- **AWS Account** with EC2 access
- **Domain Name** pointed to your EC2 instance
- **AWS Cognito** user pool configured
- **Azure OpenAI** API access

### Local Requirements

- Git
- SSH client
- AWS CLI (optional, for EC2 management)

---

## EC2 Instance Setup

### 1. Launch EC2 Instance

**Recommended Instance Type:**
- **Minimum:** `t3.large` (2 vCPU, 8 GB RAM)
- **Recommended:** `t3.xlarge` (4 vCPU, 16 GB RAM) or larger
- **Storage:** 50-100 GB EBS volume

**AMI:** Amazon Linux 2023 or Ubuntu 22.04 LTS

### 2. Configure Security Group

Create/configure security group with these inbound rules:

| Type  | Protocol | Port | Source    | Description              |
|-------|----------|------|-----------|--------------------------|
| SSH   | TCP      | 22   | Your IP   | SSH access               |
| HTTP  | TCP      | 80   | 0.0.0.0/0 | HTTP (redirects to HTTPS)|
| HTTPS | TCP      | 443  | 0.0.0.0/0 | HTTPS (production)       |

**Note:** Do NOT expose ports 5432, 7474, 7687, 5672, 15672, 6379, 8000, 3000 in production.

### 3. Connect to EC2 Instance

```bash
ssh -i /path/to/your-key.pem ec2-user@your-ec2-public-ip
# or for Ubuntu:
ssh -i /path/to/your-key.pem ubuntu@your-ec2-public-ip
```

### 4. Install Docker & Docker Compose

#### For Amazon Linux 2023:

```bash
# Update system
sudo yum update -y

# Install Docker
sudo yum install -y docker

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -a -G docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Log out and back in for group changes to take effect
exit
```

#### For Ubuntu 22.04:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
sudo apt install -y docker.io

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group
sudo usermod -a -G docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Log out and back in for group changes to take effect
exit
```

### 5. Install Git

```bash
# Amazon Linux
sudo yum install -y git

# Ubuntu
sudo apt install -y git
```

---

## Domain Configuration

### 1. Point Domain to EC2

Get your EC2 instance's **public IP** or **Elastic IP** (recommended for production).

**In your domain registrar's DNS settings**, add an A record:

```
Type: A
Name: @ (or your subdomain)
Value: your-ec2-public-ip
TTL: 300 (or default)
```

**Example:**
- Domain: `aurora.example.com`
- Points to: `54.123.45.67`

### 2. Verify DNS Propagation

```bash
# Check if domain resolves to your EC2 IP
nslookup your-domain.com
# or
dig your-domain.com +short
```

**Wait for DNS propagation** (can take 5-60 minutes).

---

## Application Deployment

### 1. Clone Repository

```bash
cd ~
git clone https://github.com/your-org/octo-rapid-aurora.git
cd octo-rapid-aurora
```

### 2. Configure Environment

```bash
# Copy production environment template
cp .env.prod .env

# Edit with your values
nano .env
# or
vi .env
```

**Critical values to update:**

```bash
# Domain & SSL
DOMAIN=your-domain.com
SSL_EMAIL=admin@your-domain.com

# Database passwords (use strong passwords!)
POSTGRES_PASSWORD=your_strong_postgres_password
NEO4J_PASSWORD=your_strong_neo4j_password
RABBITMQ_PASSWORD=your_strong_rabbitmq_password

# Azure OpenAI
AZURE_OPENAI_API_KEY=your_azure_openai_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# AWS Cognito
AWS_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_APP_CLIENT_ID=your_client_id
COGNITO_APP_CLIENT_SECRET=your_client_secret
COGNITO_DOMAIN=your-app.auth.us-east-1.amazoncognito.com

# Application URLs (match your domain)
APPLICATION_URL=https://your-domain.com
COOKIE_DOMAIN=your-domain.com
```

**Save and exit** (`Ctrl+X`, `Y`, `Enter` in nano).

### 5. Deploy with Automated Backups

```bash
# Deploy production + setup automated backups
make deploy-prod

# This automatically:
# 1. Starts production services
# 2. Sets up backups (every other day at 2 PM)
# 3. Runs initial test backup (optional prompt)
# 4. Safe to run multiple times (updates schedule)
```

**Manual alternative:**
```bash
# Start production services
docker compose -f docker-compose.prod.yml up --build -d

# Setup automated backups separately
make backup-setup

# View logs
docker compose -f docker-compose.prod.yml logs -f

# Check running services
docker ps
```

**Initial startup takes 5-10 minutes** as services initialize and SSL certificates are obtained.

### 6. Verify Backup Setup

```bash
# Check backup status
make backup-status

# View backup logs
make backup-logs

# Run manual backup test
make backup
```

---

## SSL Certificate Setup

### Automatic Setup (Handled by Container)

The nginx container automatically:
1. Generates self-signed certificates for initial startup
2. Requests Let's Encrypt certificates via ACME challenge
3. Reloads nginx with production certificates
4. Sets up automatic renewal (daily check)

### Verify SSL Certificates

```bash
# Check certificate status
docker exec aurora-nginx ls -la /etc/letsencrypt/live/your-domain.com/

# View certificate details
docker exec aurora-nginx openssl x509 -in /etc/letsencrypt/live/your-domain.com/fullchain.pem -noout -text

# Check nginx logs
docker logs aurora-nginx
```

### Manual Certificate Renewal (if needed)

```bash
# Force certificate renewal
docker exec aurora-nginx certbot renew --force-renewal

# Reload nginx
docker exec aurora-nginx nginx -s reload
```

### SSL Certificate Troubleshooting

If Let's Encrypt fails:

1. **Check domain DNS**: Ensure domain points to EC2 IP
2. **Check port 80**: Must be accessible from internet
3. **Check domain in .env**: `DOMAIN=` must match DNS
4. **Check logs**: `docker logs aurora-nginx`

Common issues:
- Domain not propagated yet → Wait and retry
- Port 80 blocked by firewall → Check security group
- Too many certificate requests → Let's Encrypt rate limit (wait 1 hour)

---

## Post-Deployment

### 1. Verify Application

```bash
# Check all services are healthy
docker ps

# Test HTTP → HTTPS redirect
curl -I http://your-domain.com

# Test HTTPS
curl -I https://your-domain.com

# Test API endpoint
curl https://your-domain.com/api/health
```

### 2. Access Application

Open browser and navigate to:
```
https://your-domain.com
```

### 3. Configure AWS Cognito Callback URLs

In AWS Cognito User Pool settings, add:

**Callback URLs:**
```
https://your-domain.com/oauth/callback
```

**Sign-out URLs:**
```
https://your-domain.com
```

**Allowed OAuth Flows:**
- ✅ Authorization code grant
- ✅ Implicit grant (if needed)

**Allowed OAuth Scopes:**
- ✅ openid
- ✅ email
- ✅ profile

### 4. Test Authentication

1. Navigate to `https://your-domain.com`
2. Click "Login" or access a protected route
3. Should redirect to Cognito hosted UI
4. Login with test user
5. Should redirect back to application

---

## Maintenance

### Quick Commands

```bash
# View logs (all services)
docker compose -f docker-compose.prod.yml logs -f

# View logs (specific service)
docker logs -f aurora-nginx

# Check service status
docker ps

# Run backup now
make backup

# Check backup status
make backup-status
```

### View Logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker logs -f aurora-frontend
docker logs -f aurora-auth
docker logs -f aurora-nginx

# Last 100 lines
docker logs --tail 100 aurora-backend
```

### Stop Application

```bash
docker compose -f docker-compose.prod.yml down
```

### Stop and Remove Volumes (⚠️ DATA LOSS)

```bash
docker compose -f docker-compose.prod.yml down -v
```

### Update Application

```bash
# Pull latest code
cd ~/octo-rapid-aurora
git pull origin main

# Rebuild and restart
docker compose -f docker-compose.prod.yml up --build -d

# Remove old images
docker image prune -a
```

### Backup Data

```bash
# Create backup directory
mkdir -p ~/backups

# Backup PostgreSQL
docker exec aurora-postgres pg_dump -U aurora aurora > ~/backups/postgres_$(date +%Y%m%d).sql

# Backup Neo4j
docker exec aurora-neo4j neo4j-admin dump --database=neo4j --to=/data/neo4j_$(date +%Y%m%d).dump
docker cp aurora-neo4j:/data/neo4j_$(date +%Y%m%d).dump ~/backups/

# Backup all volumes
docker run --rm \
  -v aurora_postgres-data:/data \
  -v ~/backups:/backup \
  alpine tar czf /backup/postgres-data_$(date +%Y%m%d).tar.gz -C /data .
```

### Monitor Resources

```bash
# System resources
htop
# or
top

# Docker stats
docker stats

# Disk usage
df -h
docker system df
```

---

## Troubleshooting

### Application Not Accessible

1. **Check domain DNS:**
   ```bash
   nslookup your-domain.com
   ```

2. **Check security group:** Verify ports 80 and 443 are open

3. **Check nginx status:**
   ```bash
   docker logs aurora-nginx
   docker exec aurora-nginx nginx -t
   ```

4. **Check service health:**
   ```bash
   docker ps
   docker compose -f docker-compose.prod.yml ps
   ```

### SSL Certificate Issues

1. **View certificate logs:**
   ```bash
   docker logs aurora-nginx | grep -i cert
   ```

2. **Check certificate files:**
   ```bash
   docker exec aurora-nginx ls -la /etc/letsencrypt/live/your-domain.com/
   ```

3. **Test Let's Encrypt challenge:**
   ```bash
   curl http://your-domain.com/.well-known/acme-challenge/test
   ```

### Database Connection Issues

1. **Check PostgreSQL:**
   ```bash
   docker logs aurora-postgres
   docker exec aurora-postgres pg_isready -U aurora
   ```

2. **Check Neo4j:**
   ```bash
   docker logs aurora-neo4j
   docker exec aurora-neo4j cypher-shell -u neo4j -p YOUR_PASSWORD "RETURN 1;"
   ```

### Service Can't Connect

1. **Verify all services are running:**
   ```bash
   docker ps | grep aurora
   ```

2. **Check network:**
   ```bash
   docker network inspect octo-rapid-aurora_aurora-network
   ```

3. **Test internal connectivity:**
   ```bash
   docker exec aurora-auth curl http://backend:8000/health
   ```

### Out of Memory

1. **Check memory usage:**
   ```bash
   free -h
   docker stats
   ```

2. **Increase EC2 instance size** or reduce service memory limits

3. **Reduce worker counts:**
   - In `.env`: `RABBITMQ_MAX_WORKERS=2`

### Out of Disk Space

1. **Check disk usage:**
   ```bash
   df -h
   docker system df
   ```

2. **Clean up Docker:**
   ```bash
   docker system prune -a --volumes
   ```

3. **Remove old logs:**
   ```bash
   sudo find /var/lib/docker/containers/ -name "*.log" -exec truncate -s 0 {} \;
   ```

---

## Performance Optimization

### 1. Enable CloudWatch Monitoring

Install CloudWatch agent for metrics:
```bash
wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
sudo rpm -U ./amazon-cloudwatch-agent.rpm
```

### 2. Configure Log Rotation

```bash
# Edit Docker daemon config
sudo nano /etc/docker/daemon.json
```

Add:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

Restart Docker:
```bash
sudo systemctl restart docker
docker compose -f docker-compose.prod.yml up -d
```

### 3. Use Elastic IP

For production, use an Elastic IP to prevent IP changes on restart:

```bash
# In AWS Console: EC2 > Elastic IPs > Allocate
# Then associate with your instance
```

---

## Security Best Practices

### 1. Regular Updates

```bash
# Update system packages
sudo yum update -y  # Amazon Linux
sudo apt update && sudo apt upgrade -y  # Ubuntu

# Update application
cd ~/octo-rapid-aurora
git pull
docker compose -f docker-compose.prod.yml up --build -d
```

### 2. Secure Environment File

```bash
# Restrict permissions
chmod 600 .env

# Never commit to git
git update-index --assume-unchanged .env
```

### 3. Enable EC2 Instance Firewall

```bash
# Amazon Linux (firewalld)
sudo systemctl start firewalld
sudo systemctl enable firewalld
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# Ubuntu (ufw)
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 4. Regular Backups

Set up automated backups using cron:

```bash
crontab -e
```

Add:
```cron
# Automated backups every other day at 2 PM
0 14 */2 * * /home/ec2-user/octo-rapid-aurora/scripts/backup.sh
```

**Note:** `make prod` and `make backup-setup` automatically configure this for you.

---

## Support

For issues or questions:
- Check logs: `docker compose -f docker-compose.prod.yml logs -f`
- Review troubleshooting section above
- Contact system administrator

---

**Last Updated:** December 2025
