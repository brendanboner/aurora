# EC2 Base Setup Guide for Aurora

This guide covers the initial setup of an AWS EC2 instance for hosting the Aurora application. This is the **prerequisite** for both deployment methods (local build and ECR).

---

## Table of Contents

1. [EC2 Instance Specifications](#ec2-instance-specifications)
2. [Security Groups](#security-groups)
3. [IAM Roles & Permissions](#iam-roles--permissions)
4. [Initial Server Setup](#initial-server-setup)
5. [Docker Installation](#docker-installation)
6. [SSH/SSM Tunnel Setup](#sshssm-tunnel-setup)
7. [Domain Configuration](#domain-configuration)
8. [Next Steps](#next-steps)

---

## EC2 Instance Specifications

### Instance Configuration

| Component | Specification | Notes |
|-----------|--------------|-------|
| **Instance Type** | `t4g.xlarge` | 4 vCPUs, 16 GB RAM, ARM64 architecture |
| **AMI** | Amazon Linux 2023 (ARM64) | Latest stable release |
| **Root Volume** | 50 GB GP3 EBS | For OS and Docker images |
| **Data Volume** | 200 GB GP3 EBS | Mounted for application data |
| **Architecture** | ARM64 (aarch64) | Graviton processors, cost-effective |

### Storage Layout

Aurora uses two volumes for optimal performance and data management:

**Root Volume (`/`) - 50 GB**:
- Operating system
- Docker images and containers
- System logs
- Application code (if building locally)

**Data Volume (`/data`) - 200 GB**:
- PostgreSQL data (`/data/postgres`)
- Neo4j data (`/data/neo4j`)
- RabbitMQ data (`/data/rabbitmq`)
- Redis data (`/data/redis`)
- Application backups (`/data/backups`)

### Why These Specs?

Aurora runs the following services simultaneously:
- PostgreSQL (backend database)
- Neo4j (knowledge graph database)
- RabbitMQ (message queue)
- Redis (cache/session store)
- 5 Python microservices (auth, backend, curator, digester, retriever)
- Nginx (reverse proxy)
- Frontend (React build)

**Note**: The t4g.xlarge instance uses AWS Graviton processors (ARM64), which provide better price-performance than x86 instances.

---

## Security Groups

### Create Aurora Security Group

1. Go to **EC2 Console** → **Security Groups** → **Create Security Group**

2. **Inbound Rules** (Choose based on deployment method):

   #### CloudFront Deployment (Recommended)
   
   | Type | Protocol | Port Range | Source | Description |
   |------|----------|------------|--------|-------------|
   | HTTP | TCP | 80 | CloudFront Prefix List | Application access via CloudFront only |

   **To restrict to CloudFront traffic only**:
   - Create a custom security group that will listen on port 80 and come from a custom source of `com.amazonaws.global.cloudfront.origin-facing`
   - This ensures only CloudFront can reach your EC2 instance on port 80
   - Security is enforced at the network level by the security group

   #### Let's Encrypt Deployment (Custom Domain)
   
   | Type | Protocol | Port Range | Source | Description |
   |------|----------|------------|--------|-------------|
   | HTTP | TCP | 80 | 0.0.0.0/0 | HTTP (redirects to HTTPS + Let's Encrypt validation) |
   | HTTPS | TCP | 443 | 0.0.0.0/0 | HTTPS application access |

   #### SSH Access (Optional)
   
   | Type | Protocol | Port Range | Source | Description |
   |------|----------|------------|--------|-------------|
   | SSH | TCP | 22 | Your IP/CIDR | SSH access for emergency management |

   **Important**: Port 22 (SSH) should only be opened if absolutely necessary and restricted to your specific IP address. **AWS Systems Manager (SSM) is preferred** for secure shell access without opening ports.

3. **Outbound Rules**:
   - Leave default (all traffic allowed)

### Security Best Practices

- **Use AWS Systems Manager (SSM)**: Connect to EC2 without opening SSH port (see [SSH/SSM Access](#sshssm-access) below)
- **Restrict SSH if used**: Limit port 22 to your office IP or VPN CIDR block
- **CloudFront is safer**: Only port 80 exposed, CloudFront handles DDoS protection
- **Never expose database ports**: PostgreSQL (5432), Neo4j (7474, 7687), RabbitMQ (5672, 15672), Redis (6379) should **NOT** be in security group
- **Use SSH tunnels** for database management (see below)

---

## IAM Roles & Permissions

### Required IAM Role

The EC2 instance needs an IAM role with appropriate permissions depending on your deployment method and monitoring preferences.

1. **Create IAM Role**:
   - Go to **IAM Console** → **Roles** → **Create Role**
   - Select **AWS Service** → **EC2**
   - Name: `Aurora-EC2-Role`

2. **Required Permissions**:

   Create a custom IAM policy (or attach AWS managed policies) that includes:

   - **ECR Access**: Required for pulling Docker images from ECR
     - Permissions: `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:GetDownloadUrlForLayer`, `ecr:BatchGetImage`
   
   - **SSM Access**: Recommended for secure shell access without opening port 22
     - AWS Managed Policy: `AmazonSSMManagedInstanceCore`
   
   - **CloudWatch Logs**: Optional for centralized logging
     - Permissions: `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`, `logs:DescribeLogStreams`

3. **Attach Role to EC2 Instance**:
   - Select your EC2 instance
   - **Actions** → **Security** → **Modify IAM Role**
   - Select `Aurora-EC2-Role`

### Monitoring

Currently, the primary method for monitoring Aurora is:
- **SSH/SSM into the instance** and view Docker logs directly
- Use `docker-compose logs` commands
- Check container status with `docker-compose ps`
- Monitor resource usage with `docker stats`

CloudWatch integration is optional and would require the CloudWatch permissions listed above plus Docker daemon logging configuration.

---

## Initial Server Setup

### 1. Launch EC2 Instance

```bash
# From AWS Console or CLI
aws ec2 run-instances \
  --image-id ami-xxxxxxxx \
  --instance-type t4g.xlarge \
  --security-group-ids sg-xxxxxxxx \
  --iam-instance-profile Name=Aurora-EC2-Role \
  --block-device-mappings \
    DeviceName=/dev/xvda,Ebs={VolumeSize=50,VolumeType=gp3} \
    DeviceName=/dev/xvdf,Ebs={VolumeSize=200,VolumeType=gp3}
```

**Note**: Use an ARM64-compatible Amazon Linux 2023 AMI for t4g instances.

### 2. Connect to Instance

**Option A: AWS Systems Manager (Recommended)**

```bash
# From AWS Console: EC2 → Instances → Select instance → Connect → Session Manager
# Or via AWS CLI:
aws ssm start-session --target i-1234567890abcdef0
```

**No port 22 needed!** SSM provides secure shell access through AWS infrastructure.

**Option B: SSH (If port 22 is open)**

```bash
ssh -i ~/.ssh/your-key.pem ec2-user@YOUR_EC2_PUBLIC_IP
```

### 3. Mount Data Volume

The 200GB data volume needs to be formatted and mounted:

```bash
# Check available disks
lsblk

# Expected output shows nvme1n1 (200GB) unmounted
# NAME          MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
# nvme0n1       259:0    0   50G  0 disk 
# └─nvme0n1p1   259:1    0   50G  0 part /
# nvme1n1       259:2    0  200G  0 disk

# Format the data volume (only needed once!)
sudo mkfs -t xfs /dev/nvme1n1

# Create mount point
sudo mkdir -p /data

# Mount the volume
sudo mount /dev/nvme1n1 /data

# Verify mount
df -h /data
# Should show 200GB mounted at /data

# Make mount permanent (add to /etc/fstab)
# First, get the UUID
sudo blkid /dev/nvme1n1
# Copy the UUID value

# Add to fstab (replace UUID with your value)
echo "UUID=your-uuid-here  /data  xfs  defaults,nofail  0  2" | sudo tee -a /etc/fstab

# Verify fstab works
sudo umount /data
sudo mount -a
df -h /data  # Should show mounted again
```

### 4. Create Data Directories

```bash
# Create directories for Docker volumes
sudo mkdir -p /data/postgres
sudo mkdir -p /data/neo4j
sudo mkdir -p /data/rabbitmq
sudo mkdir -p /data/redis
sudo mkdir -p /data/backups

# Set ownership for Docker access
sudo chown -R ec2-user:ec2-user /data
```

### 5. Update System Packages

```bash
# Update system
sudo dnf update -y

# Install Git (for cloning repository)
sudo dnf install -y git

# Install Make (for Makefile commands)
sudo dnf install -y make

# Install Cronie (for automated backup scheduling)
sudo dnf install -y cronie

# Enable and start cron service
sudo systemctl enable crond
sudo systemctl start crond

# Verify cron is running
sudo systemctl status crond
```

### 6. System Limits (Optional)

**Note**: If you encounter "too many open files" errors from Neo4j or RabbitMQ, you may need to increase file descriptor and process limits. This can be done by modifying `/etc/security/limits.conf` to set higher `nofile` (65536) and `nproc` (4096) values, and applying them with `sysctl -w fs.file-max=65536`. In practice, this is rarely needed for typical Aurora deployments.

---

## Docker Installation

### Install Docker on Amazon Linux 2023

```bash
# Install Docker
sudo dnf install -y docker

# Start Docker service
sudo systemctl start docker
sudo systemctl enable docker

# Add user to docker group (no need for sudo)
sudo usermod -aG docker ec2-user

# Log out and back in for group changes to take effect
exit
# Reconnect via SSM or SSH
```

### Install Docker Compose Plugin

```bash
# Create Docker CLI plugins directory
mkdir -p ~/.docker/cli-plugins

# Download latest Docker Compose plugin for ARM64
curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-aarch64" \
  -o ~/.docker/cli-plugins/docker-compose

# Make it executable
chmod +x ~/.docker/cli-plugins/docker-compose

# Verify installation
docker --version
docker compose version
```

**Expected output:**
```
Docker version 25.x.x
Docker Compose version v2.x.x
```

**Note**: We're installing the Docker Compose **plugin** (used as `docker compose`), not the standalone `docker-compose` command. All modern Docker Compose files and the Aurora Makefiles use the `docker compose` syntax.

### Install Docker Buildx Plugin

**Note**: Docker Compose requires buildx for the `build` command, even for simple same-architecture builds. This is a dependency of modern Docker Compose, not specifically for cross-platform builds.

```bash
# Get the latest buildx version and download for ARM64
BUILDX_VERSION=$(curl -s https://api.github.com/repos/docker/buildx/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')
curl -SL "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-arm64" \
  -o ~/.docker/cli-plugins/docker-buildx

# Make it executable
chmod +x ~/.docker/cli-plugins/docker-buildx

# Verify buildx installation
docker buildx version
```

**Expected output:**
```
github.com/docker/buildx vX.XX.X
```

### Configure Docker to Use Data Volume (Optional)

**Note**: By default, Docker stores images, containers, and build cache in `/var/lib/docker` on the root volume. For Aurora with ~8 services, this typically uses 5-10GB. The 50GB root volume is usually sufficient, especially if using pre-built ECR images.

**Consider moving Docker to the data volume if**:
- You're doing local builds on EC2 (build cache can grow large)
- You want extra headroom and separation of concerns
- You're not disciplined about pruning old images

To move Docker's storage to the data volume:

```bash
# Stop Docker
sudo systemctl stop docker

# Create Docker data directory on data volume
sudo mkdir -p /data/docker

# Update Docker daemon configuration
sudo tee /etc/docker/daemon.json > /dev/null <<EOF
{
  "data-root": "/data/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF

# Start Docker
sudo systemctl start docker

# Verify Docker is using /data
docker info | grep "Docker Root Dir"
# Should show: Docker Root Dir: /data/docker
```

### Test Docker Installation

```bash
# Test Docker
docker run hello-world

# Should see: "Hello from Docker!"
```

---

## SSH/SSM Tunnel Setup

Aurora binds infrastructure services to `localhost` only for security. To access management interfaces, you need to create a tunnel.

### Option A: AWS Systems Manager Port Forwarding (Recommended)

No security group changes needed!

```bash
# From your local machine - Neo4j Browser:
aws ssm start-session \
  --target i-1234567890abcdef0 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7474"],"localPortNumber":["7474"]}'

# In another terminal - Neo4j Bolt:
aws ssm start-session \
  --target i-1234567890abcdef0 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7687"],"localPortNumber":["7687"]}'

# In another terminal - RabbitMQ:
aws ssm start-session \
  --target i-1234567890abcdef0 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["15672"],"localPortNumber":["15672"]}'
```

### Option B: SSH Tunnel (If port 22 is open)

```bash
# From your local machine (not on EC2):
ssh -i ~/.ssh/your-key.pem \
  -L 7474:localhost:7474 \
  -L 7687:localhost:7687 \
  -L 15672:localhost:15672 \
  ec2-user@YOUR_EC2_PUBLIC_IP
```

### Access Management Interfaces

Once tunnel is established:

| Service | URL | Default Credentials |
|---------|-----|-------------------|
| Neo4j Browser | http://localhost:7474 | neo4j / (see .env) |
| RabbitMQ Management | http://localhost:15672 | aurora / (see .env) |

### Persistent Tunnel via SSH Config (Optional)

If using SSH, add to your local `~/.ssh/config`:

```
Host aurora-prod
  HostName YOUR_EC2_PUBLIC_IP
  User ec2-user
  IdentityFile ~/.ssh/your-key.pem
  LocalForward 7474 localhost:7474
  LocalForward 7687 localhost:7687
  LocalForward 15672 localhost:15672
```

Then simply run: `ssh aurora-prod`

---

## Domain Configuration

Domain and DNS configuration is independent of your deployment method (local build vs ECR). You can choose either approach:

- **CloudFront + HTTP**: Recommended for production. CloudFront handles SSL/TLS termination, DDoS protection, and CDN caching. Your EC2 instance only needs port 80 open (restricted to CloudFront IPs).

- **Let's Encrypt + HTTPS**: Direct HTTPS to your EC2 instance with automatic SSL certificate management. Requires ports 80 and 443 open to the internet.

Domain setup instructions are covered in the deployment guides:
- [02-Deploy-Local-Build.md](./02-Deploy-Local-Build.md) - Local build deployment
- [03-Deploy-ECR.md](./03-Deploy-ECR.md) - ECR deployment

Both guides include sections on CloudFront and Let's Encrypt configuration.

---

## Next Steps

Your EC2 instance is now ready for Aurora deployment! Choose your deployment method:

### ✅ Base Setup Complete - Choose Deployment Method:

- **[Local Build Deployment](./02-Deploy-Local-Build.md)** - Clone repo and build on EC2
- **[ECR Deployment](./03-Deploy-ECR.md)** - Use pre-built images from AWS ECR

---

## Troubleshooting

### SSM Connection Issues

**Problem**: Can't connect via AWS Systems Manager

**Solution**:
```bash
# Verify SSM agent is running
sudo systemctl status amazon-ssm-agent

# Start if needed
sudo systemctl start amazon-ssm-agent
sudo systemctl enable amazon-ssm-agent

# Verify IAM role is attached
aws ec2 describe-instances --instance-ids i-YOUR_INSTANCE_ID \
  --query 'Reservations[0].Instances[0].IamInstanceProfile'

# Check SSM agent connectivity
aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=i-YOUR_INSTANCE_ID"
```

### Docker Permission Denied

```bash
# If you see: "permission denied while trying to connect to Docker daemon"
# Log out and back in for group changes to take effect (or reboot)
exit
# Reconnect via SSM or SSH
```

### Data Volume Not Mounting

**Problem**: `/data` volume not accessible after reboot

**Solution**:
```bash
# Check if volume is attached
lsblk

# Verify fstab entry
cat /etc/fstab | grep /data

# Mount manually
sudo mount -a

# Check mount
df -h /data
```

### Docker Using Root Volume Instead of Data Volume

**Problem**: Docker filling up root volume (/)

**Solution**:
```bash
# Verify Docker data directory
docker info | grep "Docker Root Dir"

# Should show: /data/docker
# If not, check /etc/docker/daemon.json and restart Docker
sudo systemctl restart docker
```

### Port Already in Use

```bash
# Check what's using port 80/443
sudo netstat -tulpn | grep :80
sudo netstat -tulpn | grep :443

# Stop conflicting service (example: Apache)
sudo systemctl stop httpd
sudo systemctl disable httpd
```

### Disk Space

```bash
# Check available space
df -h

# Clean up Docker if needed
docker system prune -a --volumes
```

### File Descriptor Limits

```bash
# Check current limits
ulimit -n
ulimit -u

# Should show 65536 and 4096 respectively
# If not, verify /etc/security/limits.conf and reboot
```

---

## Additional Resources

- [AWS EC2 Documentation](https://docs.aws.amazon.com/ec2/)
- [Docker Documentation](https://docs.docker.com/)
- [Neo4j Production Deployment](https://neo4j.com/docs/operations-manual/current/docker/)
- [RabbitMQ Production Checklist](https://www.rabbitmq.com/production-checklist.html)
