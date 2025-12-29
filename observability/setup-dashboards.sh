#!/bin/bash

# =============================================================================
# Aurora Grafana Dashboard Setup Script
# =============================================================================
# This script helps you set up and verify Grafana dashboards for the Aurora
# LLM-based knowledge graph monitoring system.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 Aurora Grafana Dashboard Setup"
echo "=================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if docker-compose is running
echo -e "${BLUE}1. Checking system status...${NC}"

if ! docker ps | grep -q aurora-grafana; then
    echo -e "${YELLOW}⚠️  Grafana container is not running.${NC}"
    echo "   Run: docker-compose up -d"
    exit 1
fi

echo -e "${GREEN}✓${NC} Grafana is running"

# Check if dashboards directory exists
if [ ! -d "$SCRIPT_DIR/dashboards" ]; then
    echo -e "${RED}✗${NC} Dashboards directory not found"
    exit 1
fi

DASHBOARD_COUNT=$(find "$SCRIPT_DIR/dashboards" -name "*.json" | wc -l)
echo -e "${GREEN}✓${NC} Found $DASHBOARD_COUNT dashboard files"

echo ""
echo -e "${BLUE}2. Verifying configuration...${NC}"

# Check if dashboards provisioning config exists
if [ ! -f "$SCRIPT_DIR/grafana-dashboards.yml" ]; then
    echo -e "${RED}✗${NC} grafana-dashboards.yml not found"
    exit 1
fi
echo -e "${GREEN}✓${NC} Dashboard provisioning config found"

# Check if datasources config exists
if [ ! -f "$SCRIPT_DIR/grafana-datasources.yml" ]; then
    echo -e "${RED}✗${NC} grafana-datasources.yml not found"
    exit 1
fi
echo -e "${GREEN}✓${NC} Data sources config found"

echo ""
echo -e "${BLUE}3. Checking Grafana health...${NC}"

# Wait for Grafana to be ready
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if curl -s http://localhost:3001/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Grafana is responding"
        break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    echo -n "."
    sleep 1
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo ""
    echo -e "${RED}✗${NC} Grafana failed to respond after 30 seconds"
    echo "   Check: docker logs aurora-grafana"
    exit 1
fi
echo ""

echo ""
echo -e "${BLUE}4. Verifying data sources...${NC}"

# Check Prometheus
if curl -s http://localhost:9090/-/healthy > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Prometheus is accessible"
else
    echo -e "${YELLOW}⚠️  Prometheus may not be ready yet${NC}"
fi

# Check Tempo
if curl -s http://localhost:3200/ready > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Tempo is accessible"
else
    echo -e "${YELLOW}⚠️  Tempo may not be ready yet${NC}"
fi

# Check Loki
if curl -s http://localhost:3100/ready > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Loki is accessible"
else
    echo -e "${YELLOW}⚠️  Loki may not be ready yet${NC}"
fi

echo ""
echo -e "${BLUE}5. Dashboard Summary${NC}"
echo ""

dashboards=(
    "llm-accuracy:LLM Accuracy & Generation Metrics"
    "knowledge-graph:Knowledge Graph (Neo4j) Performance"
    "microservices-overview:Microservices Overview"
    "distributed-traces:Distributed Traces (Tempo)"
    "logs-and-errors:Logs & Errors (Loki)"
)

for dashboard in "${dashboards[@]}"; do
    IFS=':' read -r uid title <<< "$dashboard"
    
    if [ -f "$SCRIPT_DIR/dashboards/${uid}.json" ]; then
        echo -e "  ${GREEN}✓${NC} $title"
        echo "     → http://localhost:3001/d/${uid}"
    fi
done

echo ""
echo -e "${GREEN}==================================${NC}"
echo -e "${GREEN}✓ Setup Complete!${NC}"
echo -e "${GREEN}==================================${NC}"
echo ""
echo "📊 Access Grafana:"
echo "   URL: http://localhost:3001"
echo "   Username: admin"
echo "   Password: (see GRAFANA_ADMIN_PASSWORD in .env)"
echo ""
echo "📖 Documentation:"
echo "   See: observability/DASHBOARDS_README.md"
echo ""
echo "🔍 Troubleshooting:"
echo "   • Check logs: docker logs aurora-grafana"
echo "   • Verify metrics: http://localhost:9090"
echo "   • Test traces: http://localhost:3200"
echo "   • Test logs: http://localhost:3100"
echo ""
