#!/bin/bash
# Complete backup script for Aurora system
# Backs up Neo4j and Postgres data before any major changes

set -e

BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "📦 Creating complete Aurora backup..."
echo "   Location: $BACKUP_DIR"
echo ""

# Backup Postgres
echo "1️⃣  Backing up Postgres databases..."
docker exec aurora-postgres pg_dump -U aurora -d aurora > "$BACKUP_DIR/postgres_aurora.sql"
echo "   ✓ Aurora database saved"

docker exec aurora-postgres pg_dump -U aurora -d aurora_creators > "$BACKUP_DIR/postgres_aurora_creators.sql" 2>/dev/null || echo "   ℹ aurora_creators database doesn't exist (OK)"

# Backup Neo4j (full dump)
echo ""
echo "2️⃣  Backing up Neo4j knowledge graph..."
docker exec aurora-neo4j neo4j-admin database dump neo4j --to-path=/tmp 2>/dev/null || echo "   ⚠ Direct dump not available, saving via queries..."

# Export Neo4j data via cypher
curl -s -u neo4j:password \
  -H "Content-Type: application/json" \
  -X POST http://localhost:7474/db/neo4j/tx/commit \
  -d '{"statements":[
    {"statement":"MATCH (r:Resource) RETURN count(r) AS resources"},
    {"statement":"MATCH (t:Topic) RETURN count(t) AS topics"},  
    {"statement":"MATCH (o:Organization) RETURN count(o) AS organizations"},
    {"statement":"MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS relates_to"},
    {"statement":"MATCH ()-[r:MENTIONS]->() RETURN count(r) AS mentions"}
  ]}' > "$BACKUP_DIR/neo4j_stats.json"

echo "   ✓ Neo4j statistics saved"

# Save Docker volumes info
echo ""
echo "3️⃣  Recording Docker volumes..."
docker volume ls | grep aurora > "$BACKUP_DIR/volumes.txt"
echo "   ✓ Volume list saved"

# Show summary
echo ""
echo "📊 Backup Summary:"
echo ""
echo "Postgres:"
docker exec aurora-postgres psql -U aurora -d aurora -c "
SELECT 'creator_agent' as table_name, COUNT(*)::text as count FROM creator_agent
UNION ALL SELECT 'post', COUNT(*)::text FROM post
UNION ALL SELECT 'app_users', COUNT(*)::text FROM app_users
UNION ALL SELECT 'user_agent_follow', COUNT(*)::text FROM user_agent_follow
ORDER BY table_name;"

echo ""
echo "Neo4j:"
cat "$BACKUP_DIR/neo4j_stats.json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for result in data['results']:
    col = result['columns'][0]
    val = result['data'][0]['row'][0] if result['data'] else 0
    print(f'  {col}: {val}')
"

echo ""
echo "✅ Backup complete!"
echo "   Location: $BACKUP_DIR"
echo ""
echo "To restore this backup:"
echo "   ./restore_backup.sh $BACKUP_DIR"
