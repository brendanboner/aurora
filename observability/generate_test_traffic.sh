#!/bin/bash
# Generate test traffic to populate Grafana dashboards

echo "🚀 Generating test traffic for Aurora dashboards..."
echo ""

# Test Auth Service
echo "📡 Testing Auth Service (port 8000)..."
for i in {1..3}; do
  response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "error")
  echo "  Request $i: HTTP $response"
  sleep 0.5
done
echo ""

# Test Content Creator Service
echo "📡 Testing Content Creator Service (port 8003)..."
for i in {1..3}; do
  response=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8003/health 2>/dev/null || echo "error")
  echo "  Request $i: HTTP $response"
  sleep 0.5
done
echo ""

# Wait for metrics to be scraped
echo "⏳ Waiting 15 seconds for Prometheus to scrape metrics..."
sleep 15

# Check metrics in Prometheus
echo ""
echo "📊 Checking metrics in Prometheus..."
echo ""

# HTTP Server Metrics
http_count=$(curl -s 'http://localhost:9090/api/v1/query?query=sum(aurora_http_server_duration_milliseconds_count)' | jq -r '.data.result[0].value[1] // "0"')
echo "  HTTP requests total: $http_count"

# LLM Metrics  
llm_count=$(curl -s 'http://localhost:9090/api/v1/query?query=sum(aurora_llm_request_count_total)' | jq -r '.data.result[0].value[1] // "0"')
echo "  LLM requests total: $llm_count"

# Graph Metrics
graph_count=$(curl -s 'http://localhost:9090/api/v1/query?query=sum(aurora_graph_query_count_total)' | jq -r '.data.result[0].value[1] // "0"')
echo "  Graph queries total: $graph_count"

echo ""
echo "✅ Test traffic generated!"
echo ""
echo "🌐 View dashboards at:"
echo "  - Overview: http://localhost:3001/d/aurora-overview"
echo "  - LLM Performance: http://localhost:3001/d/llm-performance-pro"
echo ""
echo "💡 Note: Dashboards use rate() functions, so you'll see data in the"
echo "   next 1-5 minutes as metrics accumulate. Refresh dashboards periodically."
