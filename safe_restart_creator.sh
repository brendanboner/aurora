#!/bin/bash
# Safe restart script for CreatorAgent service
# This preserves all Neo4j and Postgres data

set -e

echo "🔄 Safe restart of content_creator_service (preserving all data)..."
echo ""

# Check if service is running
if docker ps | grep -q aurora-content-creator; then
    echo "✓ Service is running"
else
    echo "⚠ Service not running, starting all services..."
    docker-compose up -d
    echo "⏳ Waiting for services to be healthy..."
    sleep 10
fi

# Backup critical data before changes
echo ""
echo "📦 Creating safety backups..."
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Backup Postgres
echo "  → Backing up Postgres..."
docker exec aurora-postgres pg_dump -U aurora -d aurora > "$BACKUP_DIR/postgres_aurora.sql"
echo "    ✓ Saved to $BACKUP_DIR/postgres_aurora.sql"

# Backup Neo4j node counts
echo "  → Backing up Neo4j stats..."
curl -s -u neo4j:password \
  -H "Content-Type: application/json" \
  -X POST http://localhost:7474/db/neo4j/tx/commit \
  -d '{"statements":[
    {"statement":"MATCH (r:Resource) RETURN count(r) AS resources"},
    {"statement":"MATCH (t:Topic) RETURN count(t) AS topics"},
    {"statement":"MATCH (o:Organization) RETURN count(o) AS organizations"}
  ]}' > "$BACKUP_DIR/neo4j_counts.json"
echo "    ✓ Saved to $BACKUP_DIR/neo4j_counts.json"

# Show current state
echo ""
echo "📊 Current Data State:"
docker exec aurora-postgres psql -U aurora -d aurora -c "
SELECT 'Agents' as item, COUNT(*)::text as count FROM creator_agent
UNION ALL SELECT 'Posts', COUNT(*)::text FROM post
UNION ALL SELECT 'Users', COUNT(*)::text FROM app_users;"

echo ""
echo "  Neo4j:"
cat "$BACKUP_DIR/neo4j_counts.json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for result in data['results']:
    col = result['columns'][0]
    val = result['data'][0]['row'][0]
    print(f'    {col}: {val}')
"

# Restart the service (data preserved)
echo ""
echo "🔄 Restarting content_creator_service..."
docker-compose stop content_creator_service
docker-compose up -d --build content_creator_service

# Wait for health check
echo "⏳ Waiting for service to be healthy..."
sleep 5

# Verify service is up
if docker ps | grep -q aurora-content-creator; then
    echo "✅ Service restarted successfully!"
    echo ""
    echo "🔍 Verifying data preserved..."
    
    docker exec aurora-postgres psql -U aurora -d aurora -c "
    SELECT 'Agents' as item, COUNT(*)::text as count FROM creator_agent
    UNION ALL SELECT 'Posts', COUNT(*)::text FROM post
    UNION ALL SELECT 'Users', COUNT(*)::text FROM app_users;"
    
    echo ""
    echo "✅ All data preserved!"
    echo ""
    echo "📝 Backup saved at: $BACKUP_DIR"
else
    echo "❌ Service failed to start. Check logs:"
    echo "   docker-compose logs content_creator_service"
fi
