# Aurora Backup & Restore Guide

This comprehensive guide covers backing up and restoring all Aurora system components in production.

## Table of Contents

- [Understanding Backups](#understanding-backups)
  - [What Gets Backed Up](#what-gets-backed-up)
  - [What Doesn't Get Backed Up](#what-doesnt-get-backed-up)
  - [Backup Methods Explained](#backup-methods-explained)
  - [Storage Location](#storage-location)
  - [Typical Backup Sizes](#typical-backup-sizes)
- [Creating Backups](#creating-backups)
  - [Manual Backup](#manual-backup)
  - [Custom Backup Location](#custom-backup-location)
  - [Custom Retention Period](#custom-retention-period)
  - [Configuration via .env File](#configuration-via-env-file)
- [Automated Backups](#automated-backups)
  - [Setup Daily Backups with Cron](#setup-daily-backups-with-cron)
  - [Check Backup Logs](#check-backup-logs)
- [Restoring from Backup](#restoring-from-backup)
  - [Overview](#overview)
  - [Prerequisites](#prerequisites)
  - [Quick Restore Checklist](#quick-restore-checklist)
  - [Restore PostgreSQL](#restore-postgresql)
  - [Restore Neo4j](#restore-neo4j)
  - [Restore RabbitMQ](#restore-rabbitmq)
  - [Restore Redis](#restore-redis-optional)
  - [Complete System Restore](#complete-system-restore)
- [Storage Management](#storage-management)
  - [Check Disk Usage](#check-disk-usage)
  - [List All Backups](#list-all-backups)
  - [Manual Cleanup](#manual-cleanup)
  - [Monitor Disk Space](#monitor-disk-space)
- [Best Practices](#best-practices)
  - [1. Test Your Backups](#1-test-your-backups)
  - [2. Backup Before Major Changes](#2-backup-before-major-changes)
  - [3. Monitor Backup Success](#3-monitor-backup-success)
  - [4. Document Your Restore Process](#4-document-your-restore-process)
  - [5. Off-Site and Cloud Backups](#5-off-site-and-cloud-backups)
  - [6. Disk Space Alerts and Monitoring](#6-disk-space-alerts-and-monitoring)
- [Troubleshooting](#troubleshooting)
  - [Backup Script Fails](#backup-script-fails)
  - [Restore Fails](#restore-fails)
- [Emergency Recovery](#emergency-recovery)
  - [Complete System Rebuild](#complete-system-rebuild-with-backup-restoration)
  - [Partial Recovery](#partial-recovery-single-component)
  - [Recovery Priority](#recovery-priority)
  - [Post-Recovery Checklist](#post-recovery-checklist)
- [Quick Reference](#quick-reference)
- [Changelog](#changelog)

---

## Understanding Backups

### What Gets Backed Up

The backup script (`scripts/backup.sh`) creates backups of:

1. **PostgreSQL Database** - User accounts, preferences, document metadata (SQL dump)
2. **Neo4j Database** - Complete data directory with knowledge graph (all nodes, relationships, indexes)
3. **RabbitMQ Data** - Complete data directory including:
   - Queue definitions, exchanges, bindings
   - Persistent messages (queued documents awaiting processing)
   - All configuration and state
4. **Redis** (optional) - Cache and session data (enable with `BACKUP_REDIS=true`)

**✨ Key Feature: Complete RabbitMQ Backup**

The backup script now backs up the **entire RabbitMQ data directory**, which includes:
- ✅ All queue configurations
- ✅ Persistent message content (including unprocessed scraped documents)
- ✅ Exchange and binding definitions
- ✅ Complete RabbitMQ state

This means if your system fails with messages in the queue, they will be restored from backup!

### What Doesn't Get Backed Up

- Docker images (rebuild with `docker compose build`)
- Application code (stored in Git)
- Log files
- Temporary files

### Backup Methods Explained

#### PostgreSQL
- **Method:** SQL dump using `pg_dump`
- **Format:** Compressed SQL file (`.sql.gz`)
- **Restore:** Import SQL into database

#### Neo4j
- **Method:** Data directory backup using `tar`
- **Format:** Compressed tarball (`.tar.gz`)
- **Contents:** Complete database files, transaction logs, indexes
- **Restore:** Extract to Neo4j data volume (service must be stopped)
- **Note:** Safe to backup while database is running due to Neo4j's transaction log system

#### RabbitMQ
- **Method:** Data directory backup using `tar`
- **Format:** Compressed tarball (`.tar.gz`)
- **Contents:** All queue data, messages, configurations, mnesia database
- **Restore:** Extract to RabbitMQ data volume (service should be stopped)
- **Note:** Captures queue message count for verification

#### Redis (Optional)
- **Method:** RDB snapshot using `SAVE` command
- **Format:** Compressed RDB file (`.rdb.gz`)
- **Restore:** Copy RDB file to Redis data directory

### Storage Location

- **Default:** `~/backups/aurora/`
- **Configurable:** Set `BACKUP_DIR` in `.env` to use a different location
- **Retention:** 7 days by default (configurable via `BACKUP_RETENTION_DAYS`)
- **Format:** Compressed `.gz` and `.tar.gz` files
- **Logs:** `~/backups/aurora/backup.log` (when using automated backups)

**Quick Setup:** Run `make backup-setup` in the `prod-deployment` directory to configure automated backups.

### Typical Backup Sizes

| Component  | Small     | Medium    | Large      | Description                    |
|------------|-----------|-----------|------------|--------------------------------|
| PostgreSQL | 1-10 MB   | 10-50 MB  | 50-500 MB  | User data, document metadata   |
| Neo4j      | 50-200 MB | 200 MB-1 GB| 1-10 GB   | Knowledge graph data directory |
| RabbitMQ   | 1-10 MB   | 10-100 MB | 100 MB-1 GB| Queue data + messages          |
| Redis      | 1-5 MB    | 5-20 MB   | 20-100 MB  | Cache/sessions (optional)      |
| **Total**  | ~100 MB   | ~500 MB   | ~5 GB      | Per backup set                 |

**For 7 days retention:** ~700 MB to 35 GB (depending on system size)

---

## Creating Backups

### Manual Backup

**Using Makefile (Recommended):**

```bash
cd ~/octo-rapid-aurora/prod-deployment

# Run backup immediately
make backup

# Check what was backed up
make backup-status
```

**Using Script Directly:**

```bash
# Navigate to prod-deployment directory
cd ~/octo-rapid-aurora/prod-deployment

# Standard backup (PostgreSQL + Neo4j + RabbitMQ)
./scripts/backup.sh

# Include Redis cache/sessions
BACKUP_REDIS=true ./scripts/backup.sh

# Custom backup location and retention
BACKUP_DIR=/mnt/backups BACKUP_RETENTION_DAYS=30 ./scripts/backup.sh
```

**Output Example:**
```
===== Aurora Backup Started =====
Date: Wed Dec 18 14:30:45 UTC 2025
Backup directory: /home/ec2-user/backups/aurora

→ Backing up PostgreSQL...
✓ PostgreSQL backup complete: postgres_20251218_143045.sql.gz

→ Backing up Neo4j...
   Copying Neo4j data directory...
✓ Neo4j backup complete: neo4j_20251218_143045.tar.gz
   Note: This is a data directory backup. Restore by extracting to /data volume

→ Backing up RabbitMQ...
   Backing up RabbitMQ data directory...
✓ RabbitMQ data directory backup complete: rabbitmq_data_20251218_143045.tar.gz
   Checking queue status...
   ✓ Queue 'scraped_content' contains 42 messages (backed up in data directory)

===== Backup Complete =====
Backed up:
  ✓ PostgreSQL (user data, document metadata)
  ✓ Neo4j (knowledge graph with processed content)
  ✓ RabbitMQ (configuration + data directory with persistent messages)

Total backup folder size: 1.2G
```

### Custom Backup Location

Configure via environment variable or `.env` file:

```bash
# One-time custom directory
BACKUP_DIR=/mnt/external/backups ./scripts/backup.sh

# Or set in .env file (recommended)
echo "BACKUP_DIR=/mnt/external/backups" >> .env

# The script will properly expand ${HOME} and other variables
BACKUP_DIR='${HOME}/my-backups' ./scripts/backup.sh
```

### Custom Retention Period

```bash
# Keep backups for 30 days
BACKUP_RETENTION_DAYS=30 ./scripts/backup.sh

# Or set in .env file
echo "BACKUP_RETENTION_DAYS=30" >> .env
```

### Configuration via .env File

For persistent configuration, add to `prod-deployment/.env`:

```bash
# Backup configuration
BACKUP_DIR=${HOME}/backups/aurora
BACKUP_RETENTION_DAYS=7
BACKUP_REDIS=false
RABBITMQ_QUEUE=scraped_content
```

---

## Automated Backups

### Setup Daily Backups (Recommended)

The easiest way to setup automated backups is using the Makefile command:

```bash
# Navigate to deployment directory
cd ~/octo-rapid-aurora/prod-deployment

# Run the automated setup (interactive)
make backup-setup
```

This will:
- ✅ Make the backup script executable
- ✅ Create the backup directory
- ✅ Install a cron job (every other day at 2 PM by default)
- ✅ Optionally run a test backup

**The setup script is safe to run multiple times** - it will update existing cron jobs.

### Check Backup Status

```bash
cd ~/octo-rapid-aurora/prod-deployment

# Check backup status (cron jobs, recent backups, disk usage)
make backup-status

# View backup logs
make backup-logs

# Run a manual backup
make backup
```

### Manual Cron Setup (Alternative Method)

If you prefer to manually configure cron:

1. **Make script executable:**
   ```bash
   chmod +x ~/octo-rapid-aurora/prod-deployment/scripts/backup.sh
   ```

2. **Edit crontab:**
   ```bash
   crontab -e
   ```

3. **Add backup schedule:**
   ```cron
   # Daily at 2 AM (recommended for production)
   0 2 * * * cd ~/octo-rapid-aurora/prod-deployment && ./scripts/backup.sh >> ~/backups/aurora/backup.log 2>&1
   
   # Every other day at 2 PM (default from make backup-setup)
   0 14 */2 * * cd ~/octo-rapid-aurora/prod-deployment && ./scripts/backup.sh >> ~/backups/aurora/backup.log 2>&1
   
   # Twice daily (2 AM and 2 PM) - for critical systems
   0 2,14 * * * cd ~/octo-rapid-aurora/prod-deployment && ./scripts/backup.sh >> ~/backups/aurora/backup.log 2>&1
   ```

4. **Save and exit** (`:wq` in vi, `Ctrl+X` in nano)

5. **Verify cron job:**
   ```bash
   crontab -l
   ```

### Check Backup Logs

```bash
# Using Make command
cd ~/octo-rapid-aurora/prod-deployment
make backup-logs

# Or directly view log file
tail -50 ~/backups/aurora/backup.log

# Monitor live backup
tail -f ~/backups/aurora/backup.log
```

### Customize Backup Schedule

To modify the backup frequency, edit your crontab:

```bash
crontab -e
```

**Common schedules:**

```cron
# Every day at 2 AM
0 2 * * * cd ~/octo-rapid-aurora/prod-deployment && ./scripts/backup.sh >> ~/backups/aurora/backup.log 2>&1

# Twice daily (2 AM and 2 PM)
0 2,14 * * * cd ~/octo-rapid-aurora/prod-deployment && ./scripts/backup.sh >> ~/backups/aurora/backup.log 2>&1

# Every 6 hours
0 */6 * * * cd ~/octo-rapid-aurora/prod-deployment && ./scripts/backup.sh >> ~/backups/aurora/backup.log 2>&1

# Weekly on Sunday at 3 AM
0 3 * * 0 cd ~/octo-rapid-aurora/prod-deployment && ./scripts/backup.sh >> ~/backups/aurora/backup.log 2>&1
```

---

## Restoring from Backup

### Overview

The restore process varies by component. Here's a quick reference:

| Component  | Requires Stop | Difficulty | Time (est.)  |
|------------|---------------|------------|--------------|
| PostgreSQL | Backend only  | Easy       | 1-5 minutes  |
| Neo4j      | Neo4j + deps  | Medium     | 5-15 minutes |
| RabbitMQ   | RabbitMQ + deps| Medium     | 2-10 minutes |
| Redis      | Redis only    | Easy       | 1-2 minutes  |

### Prerequisites

Before restoring:
1. **Have the backup files** available and accessible
2. **Know the backup timestamp** (e.g., `20251218_143045`)
3. **Verify backup integrity** (files not corrupted)
4. **Have sufficient disk space** for restoration
5. **Plan for downtime** (varies by component)

### Quick Restore Checklist

```bash
# 1. Verify backup files exist and are not corrupted
ls -lh ~/backups/aurora/*20251218_143045*
gunzip -t ~/backups/aurora/postgres_20251218_143045.sql.gz

# 2. Note current system state
docker ps
docker exec aurora-postgres psql -U aurora -c "\l"
docker exec aurora-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" "MATCH (n) RETURN count(n);"

# 3. Create a safety backup (optional but recommended)
./scripts/backup.sh

# 4. Proceed with restoration (see specific sections below)
```

### Restore PostgreSQL

PostgreSQL restoration is straightforward and only requires stopping services that actively use the database.

#### Full Database Restore (Recommended)

```bash
# 1. Stop services that use PostgreSQL
docker stop aurora-backend aurora-auth

# 2. Drop and recreate database
docker exec -it aurora-postgres psql -U aurora -c "DROP DATABASE IF EXISTS aurora;"
docker exec -it aurora-postgres psql -U aurora -c "CREATE DATABASE aurora;"

# 3. Restore from backup (replace timestamp with your backup)
BACKUP_DATE="20251218_143045"
gunzip -c ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz | \
  docker exec -i aurora-postgres psql -U aurora aurora

# 4. Restart services
docker start aurora-backend aurora-auth

# 5. Verify restoration
docker exec aurora-postgres psql -U aurora aurora -c "\dt"
docker exec aurora-postgres psql -U aurora aurora -c "SELECT COUNT(*) FROM users;"

echo "✓ PostgreSQL restore complete"
```

#### Restore Specific Tables (Advanced)

```bash
# 1. Extract backup to temporary location
BACKUP_DATE="20251218_143045"
gunzip ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz

# 2. Edit SQL file to keep only desired tables
# Open in editor and remove unwanted CREATE TABLE and INSERT statements
nano ~/backups/aurora/postgres_${BACKUP_DATE}.sql

# 3. Stop backend services
docker stop aurora-backend aurora-auth

# 4. Apply selected tables to database
docker exec -i aurora-postgres psql -U aurora aurora < \
  ~/backups/aurora/postgres_${BACKUP_DATE}.sql

# 5. Re-compress backup for storage
gzip ~/backups/aurora/postgres_${BACKUP_DATE}.sql

# 6. Restart services
docker start aurora-backend aurora-auth

echo "✓ Selected tables restored"
```

### Restore Neo4j

Neo4j restoration requires stopping the database service. The backup contains the complete data directory.

**⚠️ Important:** This will completely replace your Neo4j database. All existing data will be lost.

```bash
# Set backup timestamp
BACKUP_DATE="20251218_143045"

# 1. Stop all services that use Neo4j
docker stop aurora-backend aurora-digester aurora-curator

# 2. Stop Neo4j database
docker stop aurora-neo4j

# 3. Clear existing Neo4j data volume
# WARNING: This deletes all current Neo4j data!
docker run --rm \
  -v prod-deployment_neo4j-data:/data \
  alpine sh -c "rm -rf /data/*"

# 4. Extract backup to Neo4j data volume
docker run --rm \
  -v prod-deployment_neo4j-data:/data \
  -v ~/backups/aurora:/backup:ro \
  alpine sh -c "cd /data && tar xzf /backup/neo4j_${BACKUP_DATE}.tar.gz"

# 5. Fix permissions (Neo4j runs as user 7474:7474)
docker run --rm \
  -v prod-deployment_neo4j-data:/data \
  alpine chown -R 7474:7474 /data

# 6. Start Neo4j and wait for it to be ready
docker start aurora-neo4j

echo "Waiting for Neo4j to start..."
sleep 10

# Monitor Neo4j startup logs
docker logs -f aurora-neo4j &
LOG_PID=$!

# Wait for "Started." message
until docker logs aurora-neo4j 2>&1 | grep -q "Started."; do
    echo "Neo4j is starting..."
    sleep 5
done

kill $LOG_PID 2>/dev/null

# 7. Verify Neo4j is accessible
echo "Testing Neo4j connection..."
docker exec aurora-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" \
  "MATCH (n) RETURN count(n) as total_nodes, 
   count{ MATCH ()-[r]->() RETURN r } as total_relationships;"

# 8. Restart dependent services
docker start aurora-backend aurora-digester aurora-curator

echo "✓ Neo4j restore complete"
echo "  - All nodes and relationships restored"
echo "  - Indexes and constraints preserved"
echo "  - Transaction logs recovered"
```

#### Verify Neo4j Restoration

```bash
# Check node counts by label
docker exec aurora-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" \
  "MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY count DESC;"

# Check relationship counts
docker exec aurora-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" \
  "MATCH ()-[r]->() RETURN type(r) as type, count(r) as count ORDER BY count DESC;"

# Verify indexes are present
docker exec aurora-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" \
  "SHOW INDEXES;"
```

### Restore RabbitMQ

RabbitMQ restoration recovers the complete data directory including all queued messages, configurations, and state.

**⚠️ Important:** This will restore all messages that were in queues at backup time, including unprocessed scraped content!

```bash
# Set backup timestamp
BACKUP_DATE="20251218_143045"

# 1. Stop services that use RabbitMQ
docker stop aurora-retriever aurora-digester

# 2. Stop RabbitMQ
docker stop aurora-rabbitmq

# 3. Clear existing RabbitMQ data
# WARNING: This deletes all current messages and configuration!
docker run --rm \
  -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq \
  alpine sh -c "rm -rf /var/lib/rabbitmq/*"

# 4. Extract backup to RabbitMQ data volume
docker run --rm \
  -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq \
  -v ~/backups/aurora:/backup:ro \
  alpine sh -c "cd /var/lib/rabbitmq && tar xzf /backup/rabbitmq_data_${BACKUP_DATE}.tar.gz"

# 5. Fix permissions (RabbitMQ runs as user 999:999)
docker run --rm \
  -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq \
  alpine chown -R 999:999 /var/lib/rabbitmq

# 6. Start RabbitMQ
docker start aurora-rabbitmq

echo "Waiting for RabbitMQ to start..."
sleep 15

# 7. Verify RabbitMQ is ready
until docker exec aurora-rabbitmq rabbitmqctl status >/dev/null 2>&1; do
    echo "RabbitMQ is starting..."
    sleep 5
done

# 8. Check restored queues and message counts
echo ""
echo "=== Restored RabbitMQ State ==="
docker exec aurora-rabbitmq rabbitmqctl list_queues name messages consumers

# 9. Restart dependent services
docker start aurora-retriever aurora-digester

echo "✓ RabbitMQ restore complete"
echo "  - All queue configurations restored"
echo "  - All messages recovered (including unprocessed documents)"
echo "  - Exchanges and bindings restored"
```

#### Verify RabbitMQ Restoration

```bash
# Check specific queue (replace with your queue name)
RABBITMQ_QUEUE="${RABBITMQ_QUEUE:-scraped_content}"
docker exec aurora-rabbitmq rabbitmqctl list_queues name messages | grep "$RABBITMQ_QUEUE"

# Check all exchanges
docker exec aurora-rabbitmq rabbitmqctl list_exchanges name type

# Check bindings
docker exec aurora-rabbitmq rabbitmqctl list_bindings

# Access management UI (if exposed)
# http://your-server:15672
# Default credentials from your .env file
```

#### What Gets Restored

✅ **Queue Definitions** - All queue configurations
✅ **Messages** - All persistent messages in queues (including scraped content)
✅ **Exchanges** - All exchange definitions
✅ **Bindings** - Queue-to-exchange bindings
✅ **Policies** - Queue and exchange policies
✅ **Virtual Hosts** - If using multiple vhosts
✅ **User Permissions** - Access control settings

### Restore Redis (Optional)

Redis stores cache and session data. Restoration is only needed if you enabled Redis backups (`BACKUP_REDIS=true`).

```bash
# Set backup timestamp
BACKUP_DATE="20251218_143045"

# 1. Verify Redis backup exists
ls -lh ~/backups/aurora/redis_${BACKUP_DATE}.rdb.gz

# 2. Stop Redis
docker stop aurora-redis

# 3. Extract backup
gunzip -c ~/backups/aurora/redis_${BACKUP_DATE}.rdb.gz > /tmp/dump.rdb

# 4. Copy to Redis data volume
docker run --rm \
  -v prod-deployment_redis-data:/data \
  -v /tmp:/backup:ro \
  alpine cp /backup/dump.rdb /data/dump.rdb

# 5. Fix permissions (Redis runs as user 999:999)
docker run --rm \
  -v prod-deployment_redis-data:/data \
  alpine chown 999:999 /data/dump.rdb

# 6. Start Redis
docker start aurora-redis

echo "Waiting for Redis to start..."
sleep 5

# 7. Verify
docker exec aurora-redis redis-cli DBSIZE
docker exec aurora-redis redis-cli INFO server | grep redis_version

# 8. Clean up
rm /tmp/dump.rdb

echo "✓ Redis restore complete"
```

**Note:** Redis restoration is typically not critical since it only contains:
- Session data (users will need to log in again)
- Cached query results (will be regenerated on demand)
- Temporary data (ephemeral by nature)

---

## Complete System Restore

For a full disaster recovery, restore all components in order:

```bash
# Set your backup timestamp
BACKUP_DATE="20251218_143045"
BACKUP_DIR="${HOME}/backups/aurora"

echo "=== Starting Full System Restore ==="
echo "Backup date: $BACKUP_DATE"
echo ""

# 1. Stop all Aurora services
echo "→ Stopping all services..."
cd ~/octo-rapid-aurora/prod-deployment
docker compose -f docker-compose.prod.yml down

# 2. Restore PostgreSQL
echo ""
echo "→ Restoring PostgreSQL..."
docker compose -f docker-compose.prod.yml up -d aurora-postgres
sleep 10
gunzip -c ${BACKUP_DIR}/postgres_${BACKUP_DATE}.sql.gz | \
  docker exec -i aurora-postgres psql -U aurora aurora
echo "✓ PostgreSQL restored"

# 3. Restore Neo4j
echo ""
echo "→ Restoring Neo4j..."
docker run --rm \
  -v prod-deployment_neo4j-data:/data \
  alpine sh -c "rm -rf /data/*"
docker run --rm \
  -v prod-deployment_neo4j-data:/data \
  -v ${BACKUP_DIR}:/backup:ro \
  alpine sh -c "cd /data && tar xzf /backup/neo4j_${BACKUP_DATE}.tar.gz && chown -R 7474:7474 /data"
docker compose -f docker-compose.prod.yml up -d aurora-neo4j
sleep 15
echo "✓ Neo4j restored"

# 4. Restore RabbitMQ
echo ""
echo "→ Restoring RabbitMQ..."
docker run --rm \
  -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq \
  alpine sh -c "rm -rf /var/lib/rabbitmq/*"
docker run --rm \
  -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq \
  -v ${BACKUP_DIR}:/backup:ro \
  alpine sh -c "cd /var/lib/rabbitmq && tar xzf /backup/rabbitmq_data_${BACKUP_DATE}.tar.gz && chown -R 999:999 /var/lib/rabbitmq"
docker compose -f docker-compose.prod.yml up -d aurora-rabbitmq
sleep 15
echo "✓ RabbitMQ restored"

# 5. Optional: Restore Redis
if [ -f "${BACKUP_DIR}/redis_${BACKUP_DATE}.rdb.gz" ]; then
    echo ""
    echo "→ Restoring Redis..."
    gunzip -c ${BACKUP_DIR}/redis_${BACKUP_DATE}.rdb.gz > /tmp/dump.rdb
    docker run --rm \
      -v prod-deployment_redis-data:/data \
      -v /tmp:/backup:ro \
      alpine sh -c "cp /backup/dump.rdb /data/ && chown 999:999 /data/dump.rdb"
    rm /tmp/dump.rdb
    echo "✓ Redis restored"
fi

# 6. Start all remaining services
echo ""
echo "→ Starting all services..."
docker compose -f docker-compose.prod.yml up -d

# 7. Wait for services to be ready
echo "Waiting for services to initialize..."
sleep 30

# 8. Verify all services
echo ""
echo "=== Verification ==="
docker compose -f docker-compose.prod.yml ps

echo ""
echo "PostgreSQL:"
docker exec aurora-postgres psql -U aurora -c "\dt" 2>/dev/null | grep "List of relations" && echo "  ✓ Tables present"

echo ""
echo "Neo4j:"
docker exec aurora-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" \
  "MATCH (n) RETURN count(n) as nodes, count{ MATCH ()-[r]->() RETURN r } as relationships;" 2>/dev/null && echo "  ✓ Graph data present"

echo ""
echo "RabbitMQ:"
docker exec aurora-rabbitmq rabbitmqctl list_queues 2>/dev/null | grep scraped_content && echo "  ✓ Queues present"

echo ""
echo "=== Full System Restore Complete ==="
echo ""
echo "Next steps:"
echo "1. Test the application: http://your-server"
echo "2. Check logs: docker compose -f docker-compose.prod.yml logs -f"
echo "3. Verify data integrity in the UI"
```

---

## Storage Management

### Check Disk Usage

```bash
# Overall disk usage
df -h

# Backup directory usage
du -sh ~/backups/aurora

# Detailed breakdown
du -h ~/backups/aurora | sort -h
```

### List All Backups

```bash
# List all backup files with sizes
ls -lh ~/backups/aurora/*.gz ~/backups/aurora/*.tar.gz 2>/dev/null

# Group by date (YYYYMMDD format)
ls -lh ~/backups/aurora/ | grep "20251218"

# List by component
ls -lh ~/backups/aurora/postgres_*.sql.gz
ls -lh ~/backups/aurora/neo4j_*.tar.gz
ls -lh ~/backups/aurora/rabbitmq_data_*.tar.gz
ls -lh ~/backups/aurora/redis_*.rdb.gz

# Show complete backup sets (all components for a specific date)
BACKUP_DATE="20251218_143045"
ls -lh ~/backups/aurora/*${BACKUP_DATE}*
```

### Manual Cleanup

```bash
# Delete backups older than 30 days
find ~/backups/aurora -name "*.gz" -type f -mtime +30 -delete
find ~/backups/aurora -name "*.tar.gz" -type f -mtime +30 -delete

# Delete specific backup set
BACKUP_DATE="20251201_120000"
rm ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz
rm ~/backups/aurora/neo4j_${BACKUP_DATE}.tar.gz
rm ~/backups/aurora/rabbitmq_data_${BACKUP_DATE}.tar.gz
rm ~/backups/aurora/redis_${BACKUP_DATE}.rdb.gz 2>/dev/null  # may not exist

# Delete all backups (⚠️ DANGER)
rm -rf ~/backups/aurora/*
```

### Monitor Disk Space

Add disk space monitoring:

```bash
# Add to crontab
crontab -e
```

```cron
# Daily disk space check at 8 AM
0 8 * * * df -h / | grep -vE '^Filesystem|tmpfs|cdrom' | awk '{ if ($5 > 80) print "WARNING: Disk usage is " $5 " on " $1 }'
```

---

## Best Practices

### 1. Test Your Backups

**Regularly test restore procedures** (at least quarterly):

```bash
# 1. Create a test restore directory
TEST_DATE=$(date +%Y%m%d)
mkdir -p ~/test-restore-${TEST_DATE}
cd ~/test-restore-${TEST_DATE}

# 2. Use a recent backup
BACKUP_DATE="20251218_143045"

# 3. Verify backup files
echo "Checking backup integrity..."
gunzip -t ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz && echo "✓ PostgreSQL backup OK"
tar tzf ~/backups/aurora/neo4j_${BACKUP_DATE}.tar.gz > /dev/null && echo "✓ Neo4j backup OK"
tar tzf ~/backups/aurora/rabbitmq_data_${BACKUP_DATE}.tar.gz > /dev/null && echo "✓ RabbitMQ backup OK"

# 4. Test PostgreSQL restore to temporary database
docker exec aurora-postgres psql -U aurora -c "CREATE DATABASE aurora_test;"
gunzip -c ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz | \
  docker exec -i aurora-postgres psql -U aurora aurora_test

# 5. Verify restored data
echo ""
echo "Verifying restored PostgreSQL data..."
docker exec aurora-postgres psql -U aurora aurora_test -c "\dt"
docker exec aurora-postgres psql -U aurora aurora_test -c "SELECT COUNT(*) as user_count FROM users;"

# 6. Cleanup test database
docker exec aurora-postgres psql -U aurora -c "DROP DATABASE aurora_test;"

# 7. Document test
echo ""
echo "Backup test completed successfully on $(date)" | tee test-results.txt
echo "Tested backup from: ${BACKUP_DATE}" >> test-results.txt

cd -
```

**Schedule quarterly restore tests:**
```cron
# Quarterly backup restore test (January 1, April 1, July 1, October 1 at 3 AM)
0 3 1 1,4,7,10 * /path/to/test-backup-restore.sh >> ~/test-restore.log 2>&1
```

```

### 2. Backup Before Major Changes

Always backup before:
- Updating the application code
- Running database migrations
- Changing system configurations
- Upgrading Docker images or dependencies
- Making schema changes

```bash
# Pre-update backup workflow
cd ~/octo-rapid-aurora/prod-deployment

# 1. Create backup with descriptive name
echo "Creating pre-update backup..."
./scripts/backup.sh

# 2. Verify backup was created
LATEST_BACKUP=$(ls -t ~/backups/aurora/postgres_*.sql.gz | head -1)
echo "Backup created: ${LATEST_BACKUP}"

# 3. Proceed with update
git pull
docker compose -f docker-compose.prod.yml up --build -d

# 4. Verify services are healthy
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=50
git pull
docker compose -f docker-compose.prod.yml up --build -d
```

### 3. Monitor Backup Success
### 3. Monitor Backup Success

Ensure backups are running successfully:

```bash
# Check recent backups (should see all components for recent dates)
ls -lt ~/backups/aurora/ | head -20

# Check backup log for errors
tail -100 ~/backups/aurora/backup.log
grep -i "error\|fail" ~/backups/aurora/backup.log

# Verify backup files aren't empty or corrupted
find ~/backups/aurora -name "*.gz" -size 0
find ~/backups/aurora -name "*.tar.gz" -size 0

# Test backup integrity
LATEST_DATE=$(ls -t ~/backups/aurora/postgres_*.sql.gz | head -1 | sed 's/.*postgres_\(.*\)\.sql\.gz/\1/')
gunzip -t ~/backups/aurora/postgres_${LATEST_DATE}.sql.gz
tar tzf ~/backups/aurora/neo4j_${LATEST_DATE}.tar.gz > /dev/null
tar tzf ~/backups/aurora/rabbitmq_data_${LATEST_DATE}.tar.gz > /dev/null
echo "✓ Latest backups are valid"

# Check backup completeness (all components present for latest date)
echo "Latest backup set:"
ls -lh ~/backups/aurora/*${LATEST_DATE}*
```

### 4. Document Your Restore Process

Keep an operations log with:

```bash
# Create operations log
cat > ~/aurora-operations-log.md << 'EOF'
# Aurora Operations Log

## Backup Test History
- **Last successful restore test:** YYYY-MM-DD
- **Test type:** Full system restore
- **Backup date tested:** YYYYMMDD_HHMMSS
- **Result:** Success/Failure
- **Notes:** Any issues encountered

## Restore History
- **Date:** YYYY-MM-DD
- **Reason:** Brief description
- **Backup used:** YYYYMMDD_HHMMSS
- **Components restored:** PostgreSQL, Neo4j, RabbitMQ
- **Result:** Success/Failure
- **Downtime:** X minutes
- **Lessons learned:** Notes for future reference

## Critical Data Points to Verify
- [ ] User count in PostgreSQL
- [ ] Node count in Neo4j (expected: ~X)
- [ ] Relationship count in Neo4j (expected: ~X)
- [ ] RabbitMQ queue message counts
- [ ] Application functionality: login, search, document processing

EOF

# Update after each test/restore
nano ~/aurora-operations-log.md
```

### 5. Off-Site and Cloud Backups

For production systems, implement off-site backup storage:

#### Option 1: SCP to Remote Server

```bash
# Sync backups to remote server (run after backup)
REMOTE_SERVER="backup-server.example.com"
REMOTE_USER="backup-user"

rsync -avz --delete \
  -e "ssh -i ~/.ssh/backup_key" \
  ~/backups/aurora/ \
  ${REMOTE_USER}@${REMOTE_SERVER}:/backups/aurora/

# Add to crontab (runs 30 minutes after backup)
30 2 * * * rsync -avz --delete -e "ssh -i ~/.ssh/backup_key" ~/backups/aurora/ backup-user@backup-server:/backups/aurora/ >> ~/backup-sync.log 2>&1
```

#### Option 2: AWS S3 (if applicable)

```bash
# Install AWS CLI
pip install awscli

# Configure AWS credentials
aws configure

# Sync to S3 bucket
aws s3 sync ~/backups/aurora/ s3://your-backup-bucket/aurora-backups/ \
  --storage-class STANDARD_IA

# Add to crontab
30 2 * * * aws s3 sync ~/backups/aurora/ s3://your-backup-bucket/aurora-backups/ >> ~/backup-s3-sync.log 2>&1
```

#### Option 3: Local Machine Download

```bash
# From your local machine (macOS/Linux)
# Download latest backups
scp -i your-key.pem -r ec2-user@your-ec2-ip:~/backups/aurora/ ./local-backups/

# Schedule with launchd (macOS) or cron (Linux)
# Create ~/local-backup-sync.sh
#!/bin/bash
TIMESTAMP=$(date +%Y%m%d)
scp -i ~/.ssh/your-key.pem -r ec2-user@your-ec2-ip:~/backups/aurora/ ~/local-backups/${TIMESTAMP}/
```

### 6. Disk Space Alerts and Monitoring

Set up disk space alerts to prevent backups from filling the disk:

```bash
# Create monitoring script
cat > ~/check-disk.sh << 'EOF'
#!/bin/bash
THRESHOLD=80
USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ $USAGE -gt $THRESHOLD ]; then
    echo "WARNING: Disk usage is ${USAGE}% (threshold: ${THRESHOLD}%)"
    echo "Backup directory size: $(du -sh ~/backups/aurora)"
    # Optional: Send email or notification
fi
EOF

chmod +x ~/check-disk.sh

# Add to crontab (runs every hour)
echo "0 * * * * ~/check-disk.sh" | crontab -
```

---

## Troubleshooting

### Backup Script Fails

**Error: Services not running**
```bash
# Check if containers are running
docker ps | grep aurora

# Start services if needed
cd ~/octo-rapid-aurora/prod-deployment
docker compose -f docker-compose.prod.yml up -d

# Wait for services to be ready
sleep 10
```

**Error: Permission denied**
```bash
# Make script executable
chmod +x ~/octo-rapid-aurora/prod-deployment/scripts/backup.sh

# Check backup directory permissions
ls -ld ~/backups/aurora
mkdir -p ~/backups/aurora
chmod 755 ~/backups/aurora
```

**Error: Disk full**
```bash
# Check disk space
df -h

# Check backup directory size
du -sh ~/backups/aurora

# Clean up old backups immediately (keep last 3 days)
find ~/backups/aurora -name "*.gz" -type f -mtime +3 -delete
find ~/backups/aurora -name "*.tar.gz" -type f -mtime +3 -delete

# Clean up Docker resources
docker system prune -af --volumes
```

**Error: Neo4j backup warnings about file changes**
```bash
# This is expected and safe - Neo4j uses transaction logs
# The backup script already handles this with --warning=no-file-changed
# Check that backup file was created
ls -lh ~/backups/aurora/neo4j_*.tar.gz | tail -1
```

**Error: RabbitMQ tar command fails**
```bash
# Check RabbitMQ container status
docker ps | grep rabbitmq
docker logs aurora-rabbitmq --tail 50

# Ensure RabbitMQ is fully started
until docker exec aurora-rabbitmq rabbitmqctl status; do
    sleep 5
done

# Retry backup
./scripts/backup.sh
```

### Restore Fails

**Error: Database/service still in use**
```bash
# Stop all Aurora services
cd ~/octo-rapid-aurora/prod-deployment
docker compose -f docker-compose.prod.yml down

# Or stop specific services
docker stop aurora-backend aurora-auth

# Then retry restore
```

**Error: Backup file corrupted or cannot extract**
```bash
# Test PostgreSQL backup integrity
gunzip -t ~/backups/aurora/postgres_20251218_143045.sql.gz
echo "Exit code: $?"  # 0 = OK, non-zero = corrupted

# Test Neo4j backup integrity
tar tzf ~/backups/aurora/neo4j_20251218_143045.tar.gz > /dev/null
echo "Exit code: $?"

# Test RabbitMQ backup integrity  
tar tzf ~/backups/aurora/rabbitmq_data_20251218_143045.tar.gz > /dev/null
echo "Exit code: $?"

# If corrupted, use an older backup
ls -lt ~/backups/aurora/postgres_*.sql.gz
ls -lt ~/backups/aurora/neo4j_*.tar.gz
```

**Error: Volume permission denied**
```bash
# When restoring, ensure proper permissions
# Neo4j requires 7474:7474
docker run --rm -v prod-deployment_neo4j-data:/data alpine chown -R 7474:7474 /data

# RabbitMQ requires 999:999
docker run --rm -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq alpine chown -R 999:999 /var/lib/rabbitmq

# Redis requires 999:999
docker run --rm -v prod-deployment_redis-data:/data alpine chown -R 999:999 /data
```

**Error: Neo4j fails to start after restore**
```bash
# Check Neo4j logs
docker logs aurora-neo4j --tail 100

# Common issues:
# 1. Wrong permissions
docker run --rm -v prod-deployment_neo4j-data:/data alpine chown -R 7474:7474 /data

# 2. Incomplete extraction - verify backup was fully extracted
docker run --rm -v prod-deployment_neo4j-data:/data alpine ls -la /data

# 3. Start Neo4j with more memory if needed
# Edit docker-compose.prod.yml to increase NEO4J_server_memory_heap_max__size
```

**Error: RabbitMQ fails to start after restore**
```bash
# Check RabbitMQ logs
docker logs aurora-rabbitmq --tail 100

# Verify mnesia database was restored
docker run --rm -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq alpine ls -la /var/lib/rabbitmq/mnesia

# If mnesia is corrupt or missing, may need to start fresh and lose queue data
docker run --rm -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq alpine rm -rf /var/lib/rabbitmq/*
docker start aurora-rabbitmq
```

---

## Emergency Recovery

If you experience catastrophic data loss, follow this emergency recovery procedure:

### Complete System Rebuild with Backup Restoration

```bash
# 1. Navigate to deployment directory
cd ~/octo-rapid-aurora/prod-deployment

# 2. Identify your most recent complete backup
BACKUP_DATE=$(ls -t ~/backups/aurora/postgres_*.sql.gz | head -1 | sed 's/.*postgres_\(.*\)\.sql\.gz/\1/')
echo "Using backup from: ${BACKUP_DATE}"

# Verify all components are present
echo "Verifying backup completeness..."
ls -lh ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz
ls -lh ~/backups/aurora/neo4j_${BACKUP_DATE}.tar.gz
ls -lh ~/backups/aurora/rabbitmq_data_${BACKUP_DATE}.tar.gz

# 3. Stop and remove all existing containers and volumes (⚠️ DESTRUCTIVE)
echo "⚠️  This will delete all current data!"
read -p "Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

docker compose -f docker-compose.prod.yml down -v

# 4. Pull latest images and recreate services
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d

# 5. Wait for initial startup
echo "Waiting for services to initialize..."
sleep 30

# 6. Follow the "Complete System Restore" procedure above
# See the detailed restoration steps in the previous section

# 7. Verify system health
echo ""
echo "=== System Health Check ==="
docker compose -f docker-compose.prod.yml ps

echo ""
echo "PostgreSQL:"
docker exec aurora-postgres psql -U aurora -c "SELECT version();"

echo ""
echo "Neo4j:"
docker exec aurora-neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD}" "CALL dbms.components() YIELD name, versions, edition;"

echo ""  
echo "RabbitMQ:"
docker exec aurora-rabbitmq rabbitmqctl status | grep "Status of node"

echo ""
echo "=== Emergency Recovery Complete ==="
echo ""
echo "Next steps:"
echo "1. Test application: http://your-server"
echo "2. Verify all data is present"
echo "3. Check processing pipelines are working"
echo "4. Create a new backup immediately"
echo ""
echo "Creating post-recovery backup..."
./scripts/backup.sh
```

### Partial Recovery (Single Component)

If only one component failed:

```bash
# PostgreSQL only
cd ~/octo-rapid-aurora/prod-deployment
docker compose -f docker-compose.prod.yml stop aurora-backend aurora-auth
docker exec -it aurora-postgres psql -U aurora -c "DROP DATABASE IF EXISTS aurora; CREATE DATABASE aurora;"
BACKUP_DATE="20251218_143045"
gunzip -c ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz | docker exec -i aurora-postgres psql -U aurora aurora
docker compose -f docker-compose.prod.yml start aurora-backend aurora-auth

# Neo4j only  
cd ~/octo-rapid-aurora/prod-deployment
docker compose -f docker-compose.prod.yml stop aurora-backend aurora-digester aurora-curator aurora-neo4j
docker run --rm -v prod-deployment_neo4j-data:/data alpine sh -c "rm -rf /data/*"
BACKUP_DATE="20251218_143045"
docker run --rm -v prod-deployment_neo4j-data:/data -v ~/backups/aurora:/backup:ro alpine sh -c "cd /data && tar xzf /backup/neo4j_${BACKUP_DATE}.tar.gz && chown -R 7474:7474 /data"
docker compose -f docker-compose.prod.yml start aurora-neo4j aurora-backend aurora-digester aurora-curator

# RabbitMQ only
cd ~/octo-rapid-aurora/prod-deployment  
docker compose -f docker-compose.prod.yml stop aurora-retriever aurora-digester aurora-rabbitmq
docker run --rm -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq alpine sh -c "rm -rf /var/lib/rabbitmq/*"
BACKUP_DATE="20251218_143045"
docker run --rm -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq -v ~/backups/aurora:/backup:ro alpine sh -c "cd /var/lib/rabbitmq && tar xzf /backup/rabbitmq_data_${BACKUP_DATE}.tar.gz && chown -R 999:999 /var/lib/rabbitmq"
docker compose -f docker-compose.prod.yml start aurora-rabbitmq aurora-retriever aurora-digester
```

### Recovery Priority

If you need to restore quickly under time pressure:

1. **First Priority - Core Data (15-20 minutes)**
   - PostgreSQL (user accounts, document metadata)
   - Neo4j (knowledge graph)

2. **Second Priority - Processing Pipeline (5-10 minutes)**
   - RabbitMQ (queued messages)

3. **Optional**
   - Redis (cache - will regenerate)

### Post-Recovery Checklist

After emergency recovery:

- [ ] Verify user login works
- [ ] Test document search functionality
- [ ] Check knowledge graph queries return results
- [ ] Verify scraping pipeline can process new content
- [ ] Review application logs for errors
- [ ] Create a fresh backup immediately
- [ ] Document what went wrong in operations log
- [ ] Update monitoring/alerting to prevent recurrence

---

## Quick Reference

### Makefile Commands (Recommended)

```bash
cd ~/octo-rapid-aurora/prod-deployment

# Setup automated backups (run once)
make backup-setup

# Run backup immediately
make backup

# Check backup status
make backup-status

# View backup logs
make backup-logs

# Full deployment (includes backup setup)
make deploy
```

### Direct Script Commands

```bash
cd ~/octo-rapid-aurora/prod-deployment

# Run backup manually
./scripts/backup.sh

# With custom settings
BACKUP_DIR=/mnt/backups BACKUP_REDIS=true ./scripts/backup.sh
```

### Restore Commands (Quick Reference)

```bash
# Set your backup date
BACKUP_DATE="20251218_143045"

# PostgreSQL
docker stop aurora-backend aurora-auth
docker exec -it aurora-postgres psql -U aurora -c "DROP DATABASE IF EXISTS aurora; CREATE DATABASE aurora;"
gunzip -c ~/backups/aurora/postgres_${BACKUP_DATE}.sql.gz | docker exec -i aurora-postgres psql -U aurora aurora
docker start aurora-backend aurora-auth

# Neo4j
docker stop aurora-backend aurora-digester aurora-curator aurora-neo4j
docker run --rm -v prod-deployment_neo4j-data:/data alpine sh -c "rm -rf /data/*"
docker run --rm -v prod-deployment_neo4j-data:/data -v ~/backups/aurora:/backup:ro alpine sh -c "cd /data && tar xzf /backup/neo4j_${BACKUP_DATE}.tar.gz && chown -R 7474:7474 /data"
docker start aurora-neo4j aurora-backend aurora-digester aurora-curator

# RabbitMQ
docker stop aurora-retriever aurora-digester aurora-rabbitmq
docker run --rm -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq alpine sh -c "rm -rf /var/lib/rabbitmq/*"
docker run --rm -v prod-deployment_rabbitmq-data:/var/lib/rabbitmq -v ~/backups/aurora:/backup:ro alpine sh -c "cd /var/lib/rabbitmq && tar xzf /backup/rabbitmq_data_${BACKUP_DATE}.tar.gz && chown -R 999:999 /var/lib/rabbitmq"
docker start aurora-rabbitmq aurora-retriever aurora-digester
```

### Key File Locations

- **Backup script:** `prod-deployment/scripts/backup.sh`
- **Backups:** `~/backups/aurora/` (default)
- **Configuration:** `prod-deployment/.env`
- **Logs:** `~/backups/aurora/backup.log`

### Backup Files Explained

| File Pattern | Component | Format | Contents |
|--------------|-----------|--------|----------|
| `postgres_DATE.sql.gz` | PostgreSQL | Compressed SQL | Database dump |
| `neo4j_DATE.tar.gz` | Neo4j | Compressed tar | Complete data directory |
| `rabbitmq_data_DATE.tar.gz` | RabbitMQ | Compressed tar | Data directory + messages |
| `redis_DATE.rdb.gz` | Redis | Compressed RDB | Cache snapshot (optional) |

### Environment Variables

```bash
# In prod-deployment/.env or command line
BACKUP_DIR=${HOME}/backups/aurora      # Backup location
BACKUP_RETENTION_DAYS=7                 # Days to keep backups
BACKUP_REDIS=false                      # Include Redis (true/false)
RABBITMQ_QUEUE=scraped_content         # Queue name for monitoring
```

---

## Changelog

### December 2025 Update

**Major Improvements:**

1. **Complete RabbitMQ Backup** 🎉
   - Now backs up entire data directory including message content
   - Previously only backed up queue configurations
   - Lost messages are no longer an issue!

2. **Improved Neo4j Backup**
   - Uses data directory backup instead of `neo4j-admin dump`
   - Faster and more reliable
   - Safe to backup while database is running

3. **Better Environment Variable Handling**
   - Properly expands variables like `${HOME}`
   - Sources `.env` file correctly
   - More flexible configuration

4. **Enhanced Status Reporting**
   - Color-coded output for better visibility
   - Shows queue message counts
   - Improved error messages

5. **Comprehensive Documentation**
   - Complete restore procedures for all components
   - Full system restore script
   - Emergency recovery procedures
   - Troubleshooting guide
   - Off-site backup options

**Breaking Changes:**
- Backup file names changed:
  - `neo4j_DATE.dump.gz` → `neo4j_DATE.tar.gz`
  - `rabbitmq_definitions_DATE.json.gz` → `rabbitmq_data_DATE.tar.gz`
- Restore procedures updated for new backup formats

---

## Questions?

For additional help:
- **Check logs:** `docker compose -f docker-compose.prod.yml logs -f`
- **Review deployment guide:** [DEPLOYMENT.md](../doc/DEPLOYMENT.md)
- **Backup script source:** [backup.sh](./backup.sh)
- **Setup automated backups:** [setup-backups.sh](./setup-backups.sh)

---

**Last Updated:** December 18, 2025
