#!/bin/bash
# =============================================================================
# Aurora Backup Script
# =============================================================================
# Creates backups of PostgreSQL, Neo4j, and RabbitMQ
#
# Usage:
#   ./scripts/backup.sh
#
# Configuration via environment variables:
#   BACKUP_DIR              - Local backup directory (default: ~/backups/aurora)
#   BACKUP_RETENTION_DAYS   - Days to keep backups (default: 7)
#   BACKUP_REDIS            - Set to 'true' to backup Redis (default: false)
#
# See doc/BACKUP_RESTORE.md for restore instructions
# =============================================================================

set -e

# Load environment variables from .env if it exists
ENV_FILE="$(dirname "$0")/../.env"
if [ -f "$ENV_FILE" ]; then
    # Only export valid environment variable lines (KEY=VALUE format)
    # No variable expansion - values are used as-is
    while IFS='=' read -r key value; do
        # Skip empty lines, comments, and invalid keys
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && continue
        # Export directly without any eval or expansion
        export "$key=$value"
    done < "$ENV_FILE"
fi

# Configuration
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/aurora}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
BACKUP_REDIS="${BACKUP_REDIS:-false}"
DATE=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo -e "${GREEN}===== Aurora Backup Started =====${NC}"
echo "Date: $(date)"
echo "Backup directory: $BACKUP_DIR"
echo ""

# Check if services are running
if ! docker ps | grep -q "aurora-postgres"; then
    echo -e "${RED}Error: Aurora services are not running${NC}"
    exit 1
fi

# 1. Backup PostgreSQL
echo -e "${YELLOW}→ Backing up PostgreSQL...${NC}"
POSTGRES_USER="${POSTGRES_USER:-aurora}"
POSTGRES_DB="${POSTGRES_DB:-aurora}"
docker exec aurora-postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > "$BACKUP_DIR/postgres_$DATE.sql"
gzip "$BACKUP_DIR/postgres_$DATE.sql"
echo -e "${GREEN}✓ PostgreSQL backup complete: postgres_$DATE.sql.gz${NC}"

# 2. Backup Neo4j
echo ""
echo -e "${YELLOW}→ Backing up Neo4j...${NC}"
NEO4J_DATABASE="${NEO4J_DATABASE:-neo4j}"

# Backup Neo4j data directory directly
# This is the most efficient method and works while database is running
# Neo4j uses transaction logs and checkpoints, so copying files is safe
echo "   Copying Neo4j data directory..."

# Backup the entire data directory
# Use --warning=no-file-changed to ignore warnings about files changing during backup
# This is expected and safe for Neo4j - it uses transaction logs for consistency
if docker exec aurora-neo4j tar --warning=no-file-changed -czf /tmp/neo4j_backup.tar.gz -C /data . 2>&1 | grep -v "file changed as we read it"; then
    docker cp aurora-neo4j:/tmp/neo4j_backup.tar.gz "$BACKUP_DIR/neo4j_$DATE.tar.gz"
    docker exec aurora-neo4j rm /tmp/neo4j_backup.tar.gz
    echo -e "${GREEN}✓ Neo4j backup complete: neo4j_$DATE.tar.gz${NC}"
    echo "   Note: This is a data directory backup. Restore by extracting to /data volume"
else
    # Check if the backup file was created (ignore file-changed warnings)
    if docker exec aurora-neo4j test -f /tmp/neo4j_backup.tar.gz; then
        docker cp aurora-neo4j:/tmp/neo4j_backup.tar.gz "$BACKUP_DIR/neo4j_$DATE.tar.gz"
        docker exec aurora-neo4j rm /tmp/neo4j_backup.tar.gz
        echo -e "${GREEN}✓ Neo4j backup complete: neo4j_$DATE.tar.gz${NC}"
    else
        echo -e "${RED}✗ Failed to backup Neo4j data directory${NC}"
        exit 1
    fi
fi

# 3. Backup Redis (optional)
if [ "$BACKUP_REDIS" = "true" ]; then
    echo ""
    echo -e "${YELLOW}→ Backing up Redis (cache/session data)...${NC}"
    
    # Trigger Redis save and copy the dump file
    docker exec aurora-redis redis-cli SAVE > /dev/null
    docker cp aurora-redis:/data/dump.rdb "$BACKUP_DIR/redis_$DATE.rdb"
    gzip "$BACKUP_DIR/redis_$DATE.rdb"
    echo -e "${GREEN}✓ Redis backup complete: redis_$DATE.rdb.gz${NC}"
fi

# 5. Backup RabbitMQ (always - critical for scraping pipeline)
echo ""
echo -e "${YELLOW}→ Backing up RabbitMQ...${NC}"

# Get RabbitMQ queue name from environment or use default
RABBITMQ_QUEUE="${RABBITMQ_QUEUE:-scraped_content}"

# Backup RabbitMQ data directory (includes definitions, messages, and all state)
echo "   Backing up RabbitMQ data directory..."
docker exec aurora-rabbitmq tar czf /tmp/rabbitmq_data.tar.gz -C /var/lib/rabbitmq . 2>/dev/null && \
    docker cp aurora-rabbitmq:/tmp/rabbitmq_data.tar.gz "$BACKUP_DIR/rabbitmq_data_$DATE.tar.gz" && \
    docker exec aurora-rabbitmq rm /tmp/rabbitmq_data.tar.gz && \
    echo -e "${GREEN}✓ RabbitMQ data directory backup complete: rabbitmq_data_$DATE.tar.gz${NC}" || {
        echo -e "${RED}✗ Failed to backup RabbitMQ data directory${NC}"
        exit 1
    }

# Get queue statistics using rabbitmqctl (for informational purposes)
echo "   Checking queue status..."
# rabbitmqctl output has a header line and possibly multiple queues
# We need to match the exact queue name (not partial matches like scraped_content-dlq)
QUEUE_INFO=$(docker exec aurora-rabbitmq rabbitmqctl list_queues name messages 2>/dev/null | grep -v "^Listing" | grep -v "^name" | grep "^$RABBITMQ_QUEUE[[:space:]]" || echo "$RABBITMQ_QUEUE 0")
MSG_COUNT=$(echo "$QUEUE_INFO" | awk '{print $2}' | tr -d '\n\r')

# Ensure MSG_COUNT is a valid integer
MSG_COUNT=${MSG_COUNT:-0}

if [ "$MSG_COUNT" -gt 0 ] 2>/dev/null; then
    echo -e "${GREEN}   ✓ Queue '$RABBITMQ_QUEUE' contains $MSG_COUNT messages (backed up in data directory)${NC}"
else
    echo "   ✓ Queue '$RABBITMQ_QUEUE' is empty"
fi

# 6. Calculate backup sizes
echo ""
echo -e "${GREEN}===== Backup Files Created =====${NC}"
ls -lh "$BACKUP_DIR" | grep "$DATE"

# 7. Cleanup old local backups
echo ""
echo -e "${YELLOW}→ Cleaning up old local backups (keeping last $RETENTION_DAYS days)...${NC}"
find "$BACKUP_DIR" -name "*.gz" -type f -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "*.txt" -type f -mtime +$RETENTION_DAYS -delete
echo -e "${GREEN}✓ Local cleanup complete${NC}"

echo ""
echo -e "${GREEN}===== Backup Complete =====${NC}"
echo "Local backup location: $BACKUP_DIR"
echo "Backup date: $DATE"
echo ""
echo "Backed up:"
echo "  ✓ PostgreSQL (user data, document metadata)"
echo "  ✓ Neo4j (knowledge graph with processed content)"
echo "  ✓ RabbitMQ (configuration + data directory with persistent messages)"
if [ "$BACKUP_REDIS" = "true" ]; then
    echo "  ✓ Redis (cache/sessions)"
fi
echo ""
echo "Total backup folder size:"
du -sh "$BACKUP_DIR" 2>/dev/null || echo "  $BACKUP_DIR"
echo ""
echo "📖 For restore instructions, see: scripts/BACKUP_RESTORE.md"
