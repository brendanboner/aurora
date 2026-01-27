#!/bin/bash
echo "=== TEAMS AGENT LOGS ==="
docker logs aurora-teams-agent-dev --tail 50 2>&1 | tail -30

echo ""
echo "=== BACKEND LOGS ==="
docker logs aurora-backend --tail 50 2>&1 | tail -30

echo ""
echo "=== ORACLE LOGS ==="
docker logs aurora-oracle --tail 50 2>&1 | tail -30
