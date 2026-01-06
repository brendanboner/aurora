# Aurora Production Deployment Package

This folder contains everything needed to deploy Aurora on EC2 - it's completely standalone and doesn't require the application source code.

## 📚 Deployment Guides

**👉 New to Aurora deployment? Start here:**

### [Deployment Guides/](./Deployment%20Guides/)

Complete step-by-step guides for deploying Aurora:

1. **[EC2 Base Setup](./Deployment%20Guides/01-EC2-Base-Setup.md)** - Set up your AWS EC2 instance
2. **[Local Build Deployment](./Deployment%20Guides/02-Deploy-Local-Build.md)** - Deploy by building on EC2
3. **[ECR Deployment](./Deployment%20Guides/03-Deploy-ECR.md)** ⭐ - Deploy with pre-built images (recommended)

**Choose your path:**
- 🆕 **First time?** → Follow guides 1 → 2 (or 1 → 3 if using ECR)
- 🔧 **Quick reference?** → See Quick Start sections below
- 🚀 **Experienced?** → Jump to the guide you need

---

## 🏗️ Deployment Options

### Option 1: ECR Images (Recommended) ⭐
**Use:** `docker-compose.prod.yml`
- Pulls pre-built images from AWS ECR
- Fast deployment (no build time)
- Requires ECR login credentials
- Best for production
- **Guide**: [03-Deploy-ECR.md](./Deployment%20Guides/03-Deploy-ECR.md)

### Option 2: Local Build (Alternative)
**Use:** `docker-compose.build.yml`
- Builds images locally on the server
- Requires application source code
- Slower deployment (build time ~10-15 minutes)
- Good for testing without ECR access
- **Guide**: [02-Deploy-Local-Build.md](./Deployment%20Guides/02-Deploy-Local-Build.md)

## 📦 Contents

- `docker-compose.prod.yml` - Production service configuration (pulls from ECR)
- `docker-compose.build.yml` - Build configuration (builds locally on server)
- `.env.prod` - Environment variable template
- `Deployment Guides/` - Complete deployment documentation
  - `README.md` - Guide overview and comparison
  - `01-EC2-Base-Setup.md` - EC2 instance setup
  - `02-Deploy-Local-Build.md` - Local build deployment
  - `03-Deploy-ECR.md` - ECR image deployment
- `migrations/` - Database migrations (schema and data changes)
  - `001_initial_schema.sql` - Initial PostgreSQL schema
  - `002_seed_data.sql` - Initial seed data
  - `README.md` - Migration documentation and best practices
- `Makefile` - Deployment commands
- `scripts/backup.sh` - Database backup script
- `scripts/migrate.sh` - Database migration script
- `scripts/setup-backups.sh` - Automated backup setup
- `scripts/BACKUP_RESTORE.md` - Backup and restore procedures

**Note:** This folder is standalone and contains everything needed for production deployment. No application source code required on the server when using ECR images.

**Note:** The actual `.env` file is excluded from git (root .gitignore). Only `.env.prod` template is committed.

## 🚀 Quick Start (ECR Images)

### Prerequisites

1. **AWS ECR images already pushed** (from dev machine):
   ```bash
   # On dev machine with full repo:
   make login
   make ship-all
   ```

2. **EC2 instance ready**:
   - Docker and Docker Compose installed
   - Domain pointing to EC2 IP
   - Security groups: ports 22, 80, 443 open

### Deployment Steps

#### 1. Transfer to EC2

**Option A: Direct Copy (Git Clone)**
```bash
# On EC2:
git clone https://github.com/your-org/octo-rapid-aurora.git
cd octo-rapid-aurora/prod-deployment
```

**Option B: Tarball Transfer**
```bash
# On dev machine:
cd /path/to/repo
tar -czf aurora-prod.tar.gz prod-deployment/

# Transfer:
scp aurora-prod.tar.gz ec2-user@YOUR_EC2_IP:~/

# On EC2:
tar -xzf aurora-prod.tar.gz
cd prod-deployment
```

**Option C: Deployment Branch**
```bash
# Create deployment-only branch
git checkout --orphan production-deploy
git rm -rf .
git add prod-deployment/*
mv prod-deployment/* .
rmdir prod-deployment
git commit -m "Production deployment files"
git push origin production-deploy

# On EC2:
git clone -b production-deploy https://github.com/your-org/octo-rapid-aurora.git aurora
cd aurora
```

#### 2. Configure Environment

```bash
# Copy and edit environment file
cp .env.prod .env
nano .env

# Required settings:
# - ECR_REGISTRY=your-account.dkr.ecr.us-east-1.amazonaws.com
# - AWS_REGION=us-east-1
# - DOMAIN=your-domain.com
# - SSL_EMAIL=your-email@domain.com
# - All passwords and secrets
# - BACKUP_DIR (optional, defaults to ~/backups/aurora)
```

#### 3. Deploy

```bash
# Full deployment (setup backups + start services)
make deploy

# Or manually:
# make backup-setup
# make start
```

#### 4. Verify

```bash
# Check services
make status

# View logs
make logs

# Check health
make health

# Check backups
make backup-status

# Access application
# https://your-domain.com
```

## 📋 Available Commands

### Deployment
```bash
make deploy        # Full deployment (setup + start)
make start         # Start all services
make stop          # Stop all services
make restart       # Restart all services
make update        # Pull latest images + restart (with backup)
```

### Monitoring
```bash
make status        # Check service status
make logs          # View all logs (follow mode)
make logs-nginx    # View nginx logs
make logs-auth     # View auth logs
make logs-backend  # View backend logs
make health        # Check service endpoints
make disk          # Check disk usage
```

### Database
```bash
make migrate       # Run pending database migrations
make migrate-status # Show migration history
```

See `migrations/README.md` for detailed migration documentation.

### Backup
```bash
make backup        # Run backup now
make backup-setup  # Setup automated backups (2 PM every other day)
make backup-status # Check backup status
make backup-logs   # View backup logs
```

### Maintenance
```bash
make pull          # Pull latest images from ECR
make clean         # Clean stopped containers
```

## 🗄️ Database Migrations

Aurora uses a versioned migration system to manage database schema changes.

### Running Migrations

Migrations run automatically on fresh installations. For existing installations:

```bash
# Run all pending migrations
make migrate

# Check migration status
make migrate-status
```

### Creating New Migrations

1. Create a new migration file in `migrations/` with the next version number:
   ```bash
   touch migrations/003_add_user_roles.sql
   ```

2. Write your SQL changes:
   ```sql
   -- 003_add_user_roles.sql
   ALTER TABLE app_users ADD COLUMN role TEXT DEFAULT 'user';
   CREATE INDEX idx_users_role ON app_users(role);
   ```

3. Test locally, then deploy to production

See `migrations/README.md` for complete migration documentation and best practices.

## 🔄 Updating Production

### When New Images are Pushed to ECR

```bash
# Update automatically (includes backup)
make update

# Or manually:
make backup
make pull
make restart
```

### When Configuration Changes

```bash
# On dev machine: Update this folder and push to git
# On EC2: Pull changes and restart
git pull
make restart
```

## 🗂️ What's NOT Included

This deployment package does NOT include:
- ❌ Application source code (in ECR images)
- ❌ Build tools or development dependencies  
- ❌ Test files
- ❌ CI/CD configuration
- ❌ Nginx source (pushed to ECR as image)

All application code is in the pre-built Docker images in ECR.

## 🔐 Security Notes

1. **Never commit `.env`** - Only `.env.prod` template is in git (root .gitignore protects prod-deployment/.env)
2. **Use strong passwords** - Change all default passwords
3. **Restrict EC2 access** - Use security groups and key-based SSH
4. **Keep ECR images private** - Don't make repositories public
5. **Backup regularly** - `make backup-status` to verify

## 🔧 Accessing Management UIs via SSH Tunnel

Infrastructure services (Neo4j, RabbitMQ, Redis) are bound to localhost only for security. To access their management UIs, use SSH port forwarding.

### Setting Up SSH Tunnel

**From your local machine:**
```bash
# Forward all management ports at once
ssh -L 7474:localhost:7474 \
    -L 15672:localhost:15672 \
    -L 6379:localhost:6379 \
    ec2-user@YOUR_EC2_IP

# Or forward individual services as needed:
ssh -L 7474:localhost:7474 ec2-user@YOUR_EC2_IP  # Neo4j only
ssh -L 15672:localhost:15672 ec2-user@YOUR_EC2_IP  # RabbitMQ only
```

### Accessing the UIs

Once the SSH tunnel is active, open these URLs in your **local browser**:

- **Neo4j Browser**: http://localhost:7474
  - Username: From `NEO4J_USER` in `.env`
  - Password: From `NEO4J_PASSWORD` in `.env`

- **RabbitMQ Management**: http://localhost:15672
  - Username: From `RABBITMQ_USER` in `.env`
  - Password: From `RABBITMQ_PASSWORD` in `.env`

- **Redis CLI**: Use redis-cli on your local machine
  ```bash
  redis-cli -h localhost -p 6379
  ```

### Important Notes

- **Ports are NOT exposed to the internet** - They're bound to `127.0.0.1` only
- **SSH tunnel must remain active** - Keep the terminal window open
- **Use your EC2 SSH key** - Same key you use for regular SSH access
- **Background tunnel** - Add `-N -f` flags to run in background:
  ```bash
  ssh -N -f -L 7474:localhost:7474 -L 15672:localhost:15672 ec2-user@YOUR_EC2_IP
  ```

### Closing the Tunnel

```bash
# If running in foreground: Ctrl+C in the SSH terminal
# If running in background:
ps aux | grep "ssh.*localhost"  # Find process ID
kill <PID>  # Kill the SSH tunnel process
```

## 🆘 Troubleshooting

### Services Won't Start
```bash
make status
make logs
# Check .env configuration
# Ensure ECR_REGISTRY is correct
```

### Can't Pull Images
```bash
# Check ECR authentication
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin $ECR_REGISTRY

# Verify images exist
aws ecr describe-repositories --region us-east-1
```

### SSL Certificate Issues
```bash
make logs-nginx
docker exec aurora-nginx ls -la /etc/letsencrypt/live/

# Check domain DNS
nslookup your-domain.com

# Restart nginx
docker restart aurora-nginx
```

### Disk Space Issues
```bash
make disk
make clean

# Check backups
ls -lh ~/backups/aurora
```

## 📚 Documentation

For detailed information, see:
- `scripts/BACKUP_RESTORE.md` - Backup and restore procedures
- Main repo `DEPLOYMENT.md` - Complete deployment guide
- Main repo `ECR_DEPLOYMENT_WORKFLOW.md` - ECR workflow details

## 🔄 Keeping This Folder Updated

This folder should be kept in sync with the main repo configuration:

```bash
# When you update .env.prod, docker-compose.prod.yml, or Makefile.ec2:
# Copy them here so the prod-deployment folder stays current

# Example:
cp .env.prod prod-deployment/.env.prod
cp docker-compose.prod.yml prod-deployment/
cp Makefile.ec2 prod-deployment/Makefile
cp scripts/backup.sh prod-deployment/scripts/
cp scripts/setup-backups.sh prod-deployment/scripts/

# Then commit to git
git add prod-deployment/
git commit -m "Update production deployment configuration"
```

## 💡 Tips

- **Test locally first**: Use the dev environment to test changes before deploying
- **Backup before updates**: `make update` does this automatically
- **Monitor logs**: Use `make logs` after deployment to watch for issues
- **Check health regularly**: Add `make health` to cron for monitoring
- **Keep .env secure**: Never commit your actual `.env` file

## 🎯 Common Workflows

### First-Time Deployment
```bash
cp .env.prod .env
nano .env                    # Configure
make deploy                  # Deploy everything
make health                  # Verify
```

### Daily Operations
```bash
make status                  # Check services
make logs                    # View logs
make backup-status           # Check backups
```

### Updating
```bash
# After pushing new images to ECR
make update                  # Backup + pull + restart
```

### Troubleshooting
```bash
make health                  # Check endpoints
make logs-nginx              # Check specific service
make disk                    # Check space
docker ps -a                 # Check all containers
```
