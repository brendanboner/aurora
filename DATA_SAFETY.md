# Data Safety Guide for Aurora Development

## ⚠️ CRITICAL: Avoiding Data Loss

### ❌ NEVER USE (Will Delete All Data)
```bash
docker-compose down -v    # The -v flag DELETES VOLUMES
docker volume prune       # Deletes unused volumes
docker system prune -a --volumes  # Nuclear option
```

### ✅ SAFE COMMANDS (Preserve Data)

**Restart a single service:**
```bash
docker-compose restart content_creator_service
# or
./safe_restart_creator.sh
```

**Rebuild a service:**
```bash
docker-compose stop content_creator_service
docker-compose up -d --build content_creator_service
```

**Stop all services (keeps volumes):**
```bash
docker-compose stop
```

**Start again (uses existing volumes):**
```bash
docker-compose up -d
```

**View logs without affecting containers:**
```bash
docker-compose logs -f content_creator_service
```

## 📦 Backup Before Major Changes

**Quick backup:**
```bash
./backup_all.sh
```

This creates a timestamped backup in `./backups/YYYYMMDD_HHMMSS/` with:
- Postgres dumps (all databases)
- Neo4j statistics and counts
- Docker volume information

**Manual Postgres backup:**
```bash
docker exec aurora-postgres pg_dump -U aurora -d aurora > backup.sql
```

**Manual Postgres restore:**
```bash
docker exec -i aurora-postgres psql -U aurora -d aurora < backup.sql
```

## 🔍 Check Data Exists Before Changes

**Check Neo4j:**
```bash
curl -s -u neo4j:password \
  -H "Content-Type: application/json" \
  -X POST http://localhost:7474/db/neo4j/tx/commit \
  -d '{"statements":[
    {"statement":"MATCH (r:Resource) RETURN count(r)"},
    {"statement":"MATCH (t:Topic) RETURN count(t)"},
    {"statement":"MATCH (o:Organization) RETURN count(o)"}
  ]}' | python3 -m json.tool
```

**Check Postgres:**
```bash
docker exec aurora-postgres psql -U aurora -d aurora -c "
SELECT 'Resources' as item, (SELECT COUNT(*) FROM creator_agent)::text as count
UNION ALL SELECT 'Posts', (SELECT COUNT(*) FROM post)::text
UNION ALL SELECT 'Users', (SELECT COUNT(*) FROM app_users)::text;"
```

## 🆘 Data Recovery

If you accidentally deleted volumes:

1. **Check if backups exist:**
   ```bash
   ls -lt backups/
   ```

2. **Restore from most recent backup:**
   ```bash
   # Postgres
   docker exec -i aurora-postgres psql -U aurora -d aurora < backups/YYYYMMDD_HHMMSS/postgres_aurora.sql
   ```

3. **Re-run scrapers** to rebuild Neo4j knowledge graph:
   ```bash
   # Trigger retriever to fetch new data
   # (depends on your scraper setup)
   ```

## 📝 Development Workflow

### Safe Testing Workflow:

1. **Backup current state:**
   ```bash
   ./backup_all.sh
   ```

2. **Make code changes** (edit files)

3. **Restart service safely:**
   ```bash
   ./safe_restart_creator.sh
   ```

4. **Test changes** (all data preserved)

5. **Verify data still exists:**
   ```bash
   # Check counts match backup
   ```

### When Intentionally Resetting Data:

Only use `docker-compose down -v` when you explicitly want to:
- Test fresh database migrations
- Clear out test data
- Start completely from scratch

Before doing so:
1. Backup if needed: `./backup_all.sh`
2. Document what you're doing
3. Run `docker-compose down -v`
4. Run `docker-compose up -d`
5. Wait for initialization
6. Re-run migrations/seeders as needed

## 🎯 Current Data Status

As of last check:
- **Neo4j**: 3 Resources, 19 Topics, 6 Organizations
- **Postgres**: 5 users, 3 agents, 0 posts

This is minimal seed data. If you had more data before, it was lost during `docker-compose down -v`.

## 📚 Docker Volume Management

**List Aurora volumes:**
```bash
docker volume ls | grep aurora
```

**Inspect a volume:**
```bash
docker volume inspect octo-rapid-aurora_neo4j-data
docker volume inspect octo-rapid-aurora_postgres-data
```

**See volume disk usage:**
```bash
docker system df -v | grep -A 5 "VOLUME NAME"
```

Remember: Volumes persist data between container restarts. Deleting them = deleting data!
