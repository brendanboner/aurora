#!/bin/bash
# =============================================================================
# Automated Backup Setup Script
# =============================================================================
# This script configures automated backups via cron (every other day at 2 PM)
# Safe to run multiple times - will update existing cron job
#
# Usage:
#   ./scripts/setup-backups.sh
#   or
#   make backup-setup
# =============================================================================

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}===== Automated Backup Setup =====${NC}"
echo ""

# Get the directory where Aurora is installed
AURORA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_SCRIPT="$AURORA_DIR/scripts/backup.sh"

# Load environment variables from .env if it exists
if [ -f "$AURORA_DIR/.env" ]; then
    # Only export valid environment variable lines (KEY=VALUE format)
    # No variable expansion - values are used as-is
    while IFS='=' read -r key value; do
        # Skip empty lines, comments, and invalid keys
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# || ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && continue
        # Export directly without any eval or expansion
        export "$key=$value"
    done < "$AURORA_DIR/.env"
fi

# Get backup directory from env or use default
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/aurora}"

echo "Aurora directory: $AURORA_DIR"
echo "Backup script: $BACKUP_SCRIPT"
echo "Backup directory: $BACKUP_DIR"
echo ""

# Make backup script executable
chmod +x "$BACKUP_SCRIPT"
echo -e "${GREEN}✓ Backup script is executable${NC}"

# Create backup log directory
mkdir -p "$BACKUP_DIR"
echo -e "${GREEN}✓ Backup directory created: $BACKUP_DIR${NC}"

# Check if cron job already exists
CRON_JOB="0 14 */2 * * cd $AURORA_DIR && ./scripts/backup.sh >> $BACKUP_DIR/backup.log 2>&1"
CRON_EXISTS=$(crontab -l 2>/dev/null | grep -F "scripts/backup.sh" || echo "")

if [ -n "$CRON_EXISTS" ]; then
    echo -e "${YELLOW}⚠️  Backup cron job already exists:${NC}"
    echo "   $CRON_EXISTS"
    echo ""
    echo -e "${CYAN}Updating to new schedule (2 PM every other day)...${NC}"
    
    # Remove old backup cron jobs
    crontab -l 2>/dev/null | grep -v "scripts/backup.sh" | crontab -
    echo -e "${GREEN}✓ Removed old backup cron job${NC}"
fi

# Add new cron job
(crontab -l 2>/dev/null || echo "") | { cat; echo "$CRON_JOB"; } | crontab -
echo -e "${GREEN}✓ Added backup cron job (2 PM every other day)${NC}"

# Verify cron job was added
echo ""
echo -e "${CYAN}Installed Cron Jobs:${NC}"
crontab -l | grep -i backup || echo "  (none found - this shouldn't happen)"

# Run initial test backup
echo ""
read -p "Run a test backup now? (Y/n): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo ""
    echo -e "${CYAN}Running test backup...${NC}"
    cd "$AURORA_DIR"
    ./scripts/backup.sh
fi

echo ""
echo -e "${GREEN}===== Setup Complete! =====${NC}"
echo ""
echo "Automated backups are now configured:"
echo "  • Schedule: Every other day at 2:00 PM"
echo "  • Location: $BACKUP_DIR"
echo "  • Retention: ${BACKUP_RETENTION_DAYS:-7} days (automatic cleanup)"
echo "  • Log file: $BACKUP_DIR/backup.log"
echo ""
echo "Commands:"
echo "  make backup         - Run backup now"
echo "  make backup-status  - Check backup status"
echo "  make backup-logs    - View backup logs"
echo ""
echo "To modify the schedule, run:"
echo "  crontab -e"
echo ""
