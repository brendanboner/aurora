#!/bin/bash
cd /Users/bbonner/code/octo/ops/octo-rapid-aurora

echo "=== Clearing Redis cache ==="
docker compose exec -T redis redis-cli FLUSHALL

echo ""
echo "=== Testing HaLow query ==="
./cli/aurora --mode answer "What workgroups are talking about Wi-Fi HaLow?"

echo ""
echo "=== Checking oracle logs for topics ==="
docker compose logs oracle --tail=100 | grep -E "(Extracted topics|route_id|topics\[)" | tail -10
