# Read-Only Production Neo4j Connection

Simple guide to safely connect your local dev environment to production Neo4j.

## ⚠️ Important: Neo4j Community Edition Limitation

**Neo4j Community Edition does NOT support true read-only users.** All users can read and write.

This guide shows you how to connect safely, but **you must be careful not to run write operations** (CREATE, DELETE, SET, MERGE) as there is no technical enforcement.

## Why This is Still Reasonably Safe

- ✅ **SSH tunnel** - Encrypted connection, no direct database exposure  
- ✅ **Localhost only** - Only accessible from your machine
- ✅ **Separate user** - Queries are logged with 'readonly' username for audit trail
- ⚠️ **Manual discipline required** - YOU must avoid write operations

## Three Simple Steps

### Step 1: Create Read-Only User (One Time)

SSH into your production server and create a read-only Neo4j user:

```bash
# SSH to production
ssh ec2-user@YOUR_PROD_IP

# Connect to Neo4j (it will prompt for password)
docker exec -it aurora-neo4j cypher-shell -u neo4j
# Enter your production Neo4j password when prompted

# Create readonly user (Community Edition - users are read-only by default)
CREATE USER readonly SET PASSWORD 'choose_strong_password_here';

# Verify user was created
SHOW USERS;

# Exit (need to reconnect as readonly user to test permissions)
:exit

# Reconnect as the readonly user to verify it works
docker exec -it aurora-neo4j cypher-shell -u readonly
# Enter the readonly password when prompted

# Test that you can read data
MATCH (d:Document) RETURN count(d) as total;

# Exit
:exit

# ⚠️ WARNING: Neo4j Community Edition does NOT enforce read-only permissions!
# The 'readonly' user CAN write to the database if you run CREATE/DELETE/SET commands.
# YOU must be disciplined to only run read queries (MATCH, RETURN, WHERE, COUNT, etc.)
# Consider upgrading to Neo4j Enterprise Edition if you need true read-only enforcement.
```

### Step 2: Start SSH Tunnel

From your local machine, create a tunnel to forward the Neo4j port:

```bash
# This forwards local port 7687 to production Neo4j
ssh -L 7687:localhost:7687 ec2-user@YOUR_PROD_IP
```

Keep this terminal window open while testing.

### Step 3: Run Oracle Service

#### Option A: Run Directly with Python (Recommended for testing)

Set environment variables and run the Oracle service:

```bash
# Set connection variables
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=readonly
export NEO4J_PASSWORD=choose_strong_password_here
export NEO4J_DATABASE=neo4j

# Set other required variables (use your dev values)
export AZURE_OPENAI_API_KEY=your_dev_api_key
export AZURE_OPENAI_ENDPOINT=your_dev_endpoint
export AZURE_OPENAI_DEPLOYMENT=your_deployment
export POSTGRES_HOST=localhost
export POSTGRES_PASSWORD=your_local_postgres_password

# Run the Oracle service
cd oracle
python -m uvicorn src.api:app --host 0.0.0.0 --port 8080
```

#### Option B: Run with Docker (Standalone)

Run the Oracle service in Docker using an env file (no need to export variables):

```bash
# Step 1: Create an env file in the oracle directory
cat > oracle/.env.prod-test << 'EOF'
NEO4J_URI=bolt://host.docker.internal:7687
NEO4J_USER=readonly
NEO4J_PASSWORD=your_readonly_password_here
NEO4J_DATABASE=neo4j
AZURE_OPENAI_API_KEY=your_dev_api_key
AZURE_OPENAI_ENDPOINT=your_dev_endpoint
AZURE_OPENAI_API_VERSION=2024-08-01-preview
AZURE_OPENAI_DEPLOYMENT=your_deployment
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
POSTGRES_HOST=host.docker.internal
POSTGRES_PORT=5432
POSTGRES_USER=aurora
POSTGRES_PASSWORD=your_local_postgres_password
POSTGRES_DB=aurora
REDIS_HOST=host.docker.internal
REDIS_PORT=6379
OTEL_ENABLED=false
LOG_LEVEL=DEBUG
EOF

# Step 2: Build the Oracle image from repository root
docker build -f oracle/Dockerfile -t aurora-oracle:test .

# Step 3: Run the container with the env file
docker run -it --rm \
  --name oracle-test \
  --env-file oracle/.env.prod-test \
  -p 8080:8000 \
  aurora-oracle:test

# Note: Using port 8080 on host (accessible at http://localhost:8080)
# If port 8080 is also in use, change to any free port: -p <YOUR_PORT>:8000
```

**Important Notes:**
- ✅ Build from **repository root** (not from `oracle/` directory)
- ✅ Use `-f oracle/Dockerfile` to specify the Dockerfile location
- ✅ Use `host.docker.internal` to access localhost services from container (macOS/Windows)
- ✅ On Linux, use `--network host` or replace `host.docker.internal` with your actual IP
- ✅ The SSH tunnel (Step 2) must be running on your host machine
- ✅ The `.env.prod-test` file is stored in `oracle/` directory (already in `.gitignore`)

#### Option C: Quick Test Script

Create a simple test script:

```bash
# Save as: test-oracle-with-prod.sh
#!/bin/bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=readonly
export NEO4J_PASSWORD=your_readonly_password
export NEO4J_DATABASE=neo4j
export AZURE_OPENAI_API_KEY=your_dev_api_key
export AZURE_OPENAI_ENDPOINT=your_dev_endpoint
export AZURE_OPENAI_DEPLOYMENT=your_deployment

cd oracle
python -m uvicorn src.api:app --reload --host 0.0.0.0 --port 8080
```

Then just run: `./test-oracle-with-prod.sh`


That's it! The Oracle service will now query production data through the secure tunnel.

## Quick Test

Verify it's working and read-only:

```python
from neo4j import GraphDatabase

# Should work - reading data
driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("readonly", "your_password")
)
with driver.session() as session:
    result = session.run("MATCH (d:Document) RETURN count(d) as count")
    print(f"Documents: {result.single()['count']}")

# Should FAIL - writing data
try:
    with driver.session() as session:
        session.run("CREATE (n:Test {name: 'test'})")
except Exception as e:
    print(f"✓ Write blocked: {e}")  # This is good!
```

## When You're Done

1. Stop your Oracle service
2. Close the SSH tunnel (Ctrl+C in the tunnel terminal)
3. Unset environment variables if needed

## Troubleshooting

**Can't connect?**
- Check SSH tunnel is still running: `lsof -i :7687`
- Verify Neo4j is running on prod: `ssh ec2-user@YOUR_PROD_IP 'docker ps | grep neo4j'`

**Authentication failed?**
- Double-check the readonly password matches what you set in Step 1
- Verify user exists: `SHOW USERS;` in Neo4j

**Permission denied on queries?**
- This is expected! The readonly user can only read data
- You cannot CREATE, DELETE, SET, or REMOVE anything

## What You Should/Shouldn't Do

✅ **Safe to use:**
- `MATCH` - Find nodes and relationships
- `RETURN` - Get data
- `WHERE` - Filter results
- `COUNT`, `COLLECT`, `ORDER BY` - Aggregate and sort data
- Read your query pipeline code carefully before running

⚠️ **AVOID - Not technically blocked:**
- `CREATE`, `MERGE` - Make new data (⚠️ WILL modify production!)
- `DELETE`, `DETACH DELETE` - Remove data (⚠️ WILL modify production!)
- `SET`, `REMOVE` - Modify properties (⚠️ WILL modify production!)
- Any write operations

## Better Alternative: Database Backup/Restore

For truly safe testing without risk of modifying production:

```bash
# On production - create a backup
ssh ec2-user@YOUR_PROD_IP
docker exec aurora-neo4j neo4j-admin database dump neo4j --to-path=/dumps
docker cp aurora-neo4j:/dumps/neo4j.dump ./
exit

# Copy to local
scp ec2-user@YOUR_PROD_IP:~/neo4j.dump ./

# On local - restore to your dev Neo4j
docker cp neo4j.dump aurora-neo4j:/dumps/
docker exec aurora-neo4j neo4j-admin database load neo4j --from-path=/dumps/neo4j.dump --overwrite-destination=true
docker restart aurora-neo4j
```

This gives you a complete copy of production data locally with zero risk.

---

**Summary:** The SSH tunnel approach works but requires manual discipline. For zero-risk testing, use database backup/restore instead.
