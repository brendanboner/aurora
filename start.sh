#!/bin/bash

# Aurora Quick Start Script
# This script helps you get Aurora up and running quickly

set -e

echo "🌟 Aurora Quick Start"
echo "===================="
echo ""

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first:"
    echo "   https://docs.docker.com/get-docker/"
    exit 1
fi

# Check for Docker Compose
if ! docker compose version &> /dev/null && ! docker-compose --version &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose are installed"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.docker .env
    echo "✅ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: You need to configure your environment variables!"
    echo ""
    echo "Please edit the .env file and set:"
    echo "  1. POSTGRES_PASSWORD"
    echo "  2. NEO4J_PASSWORD"
    echo "  3. RABBITMQ_PASSWORD"
    echo "  4. AZURE_OPENAI_API_KEY"
    echo "  5. AZURE_OPENAI_ENDPOINT"
    echo "  6. AZURE_OPENAI_DEPLOYMENT"
    echo ""
    read -p "Press Enter when you've configured .env, or Ctrl+C to exit..."
else
    echo "✅ .env file exists"
fi

# Check critical environment variables
echo ""
echo "🔍 Validating environment configuration..."

if ! grep -q "AZURE_OPENAI_API_KEY=.*[^_here]" .env; then
    echo "⚠️  Warning: AZURE_OPENAI_API_KEY not configured"
    MISSING_CONFIG=1
fi

if ! grep -q "NEO4J_PASSWORD=.*[^_here]" .env; then
    echo "⚠️  Warning: NEO4J_PASSWORD not configured"
    MISSING_CONFIG=1
fi

if [ -n "$MISSING_CONFIG" ]; then
    echo ""
    echo "Some configuration values appear to be missing."
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Cancelled. Please configure .env and run this script again."
        exit 1
    fi
fi

echo "✅ Configuration looks good"
echo ""

# Start services
echo "🚀 Starting Aurora services..."
echo "This may take a few minutes on first run (downloading images)..."
echo ""

if docker compose version &> /dev/null; then
    docker compose up -d
else
    docker-compose up -d
fi

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 5

# Wait for backend
MAX_TRIES=30
TRIES=0
while [ $TRIES -lt $MAX_TRIES ]; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Backend is healthy"
        break
    fi
    TRIES=$((TRIES + 1))
    echo -n "."
    sleep 2
done

if [ $TRIES -eq $MAX_TRIES ]; then
    echo ""
    echo "⚠️  Backend didn't become healthy in time, but services are running"
    echo "Check logs with: docker-compose logs backend"
fi

echo ""
echo "✅ Aurora is now running!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📱 Access Points:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  🌐 Frontend:           http://localhost:3000"
echo "  ⚡ Backend API:         http://localhost:8000"
echo "  📚 API Documentation:  http://localhost:8000/docs"
echo "  🐰 RabbitMQ Management: http://localhost:15672"
echo "  🗄️  Neo4j Browser:      http://localhost:7474"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🛠️  Quick Commands:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  View logs:        docker-compose logs -f"
echo "  Stop services:    docker-compose down"
echo "  Restart:          docker-compose restart"
echo "  View status:      docker-compose ps"
echo ""
echo "  Or use Make:      make help"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📖 Next Steps:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  1. Open http://localhost:3000 in your browser"
echo "  2. Go to Admin page to create a user"
echo "  3. Go to Profile page to set preferences"
echo "  4. Start chatting in the main page!"
echo ""
echo "For detailed documentation, see:"
echo "  - DOCKER_COMPOSE.md (Docker Compose guide)"
echo "  - README.md (General overview)"
echo "  - frontend/README.md (Frontend details)"
echo ""
echo "🎉 Happy knowledge graphing!"
