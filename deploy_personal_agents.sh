#!/bin/bash
# Deploy Personal Agents Backend Implementation

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         Deploying Personal Agents Backend                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Error: docker-compose.yml not found. Run this script from repository root."
    exit 1
fi

echo "📦 Stopping content_creator_service..."
docker-compose stop content_creator_service

echo ""
echo "🔨 Building content_creator_service with new code..."
docker-compose build content_creator_service

echo ""
echo "🚀 Starting content_creator_service..."
docker-compose up -d content_creator_service

echo ""
echo "⏳ Waiting for service to be ready..."
sleep 5

echo ""
echo "📋 Checking service logs..."
docker logs --tail=50 aurora-content-creator

echo ""
echo "🔍 Verifying database migration..."
docker exec aurora-postgres psql -U aurora -d aurora -c "SELECT COUNT(*) as user_agent_table_exists FROM information_schema.tables WHERE table_name = 'user_agent';" 2>/dev/null || echo "⚠️  Could not verify migration - check manually"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Check logs: docker logs -f aurora-content-creator"
echo "2. Test API: curl -X GET http://localhost/content_creator_service/user_agents -H 'X-User-Id: test-user'"
echo "3. Review PERSONAL_AGENTS_IMPLEMENTATION.md for testing guide"
echo ""

