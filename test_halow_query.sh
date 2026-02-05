#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${OCTO_RAPID_AURORA_ROOT:-$SCRIPT_DIR}"
cd "$PROJECT_ROOT"

echo "=== Clearing Redis cache ==="
docker compose exec -T redis redis-cli FLUSHALL

echo ""
echo "=== Testing HaLow query ==="
./cli/aurora --mode answer "What workgroups are talking about Wi-Fi HaLow?"

echo ""
echo "=== Checking oracle logs for topics ==="
docker compose logs oracle --tail=100 | grep -E "(Extracted topics|route_id|topics\[)" | tail -10
