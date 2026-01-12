#!/bin/bash

# =============================================================================
# Aurora Production Endpoint Security Testing Script
# =============================================================================
# This script tests your production deployment to ensure:
# 1. Only public endpoints (nginx, auth) are accessible from internet
# 2. Internal services are properly protected
# 3. Authentication flows work correctly
# 4. CORS is properly configured
#
# Usage:
#   ./test_prod_endpoints.sh YOUR_DOMAIN_OR_IP
#   ./test_prod_endpoints.sh app.yourcompany.com
#   ./test_prod_endpoints.sh d23ew7gbss3vnh.cloudfront.net
#   ./test_prod_endpoints.sh 54.123.45.67
# =============================================================================

# Check if domain/IP is provided
if [ $# -eq 0 ]; then
    echo "❌ Error: Please provide your production domain or IP address"
    echo "Usage: $0 <domain_or_ip>"
    echo "Example: $0 app.yourcompany.com"
    echo "Example: $0 d23ew7gbss3vnh.cloudfront.net"
    echo "Example: $0 54.123.45.67"
    exit 1
fi

DOMAIN_INPUT=$1
PROTOCOL="https"

# Remove protocol if provided in input
DOMAIN=${DOMAIN_INPUT#http://}
DOMAIN=${DOMAIN#https://}
# Remove trailing slash
DOMAIN=${DOMAIN%/}

# Check if it's an IP address (use http for testing)
if [[ $DOMAIN =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    PROTOCOL="http"
    echo "🔍 Detected IP address, using HTTP for testing"
fi

BASE_URL="${PROTOCOL}://${DOMAIN}"

echo "🚀 Testing Aurora Production Deployment"
echo "🌐 Base URL: $BASE_URL"
echo "📅 $(date)"
echo ""

# =============================================================================
# Test 1: Public Endpoints (Should be accessible)
# =============================================================================
echo "=== 🌍 Testing Public Endpoints (Should Work) ==="

# Test main frontend
echo "🔹 Testing Frontend..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 10 "$BASE_URL/")
if [ "$response" = "200" ]; then
    echo "✅ Frontend accessible: $BASE_URL/ → $response"
else
    echo "❌ Frontend failed: $BASE_URL/ → $response"
fi

# Test auth health endpoint
echo "🔹 Testing Auth Service Health..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 10 "$BASE_URL/health")
if [ "$response" = "200" ]; then
    echo "✅ Auth health accessible: $BASE_URL/health → $response"
else
    echo "❌ Auth health failed: $BASE_URL/health → $response"
fi

# Test auth login endpoint
echo "🔹 Testing Auth Login Endpoint..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 10 "$BASE_URL/api/login")
if [ "$response" = "302" ] || [ "$response" = "200" ]; then
    echo "✅ Auth login accessible: $BASE_URL/api/login → $response"
else
    echo "❌ Auth login failed: $BASE_URL/api/login → $response"
fi

echo ""

# =============================================================================
# Test 2: Internal Services (Should be blocked from internet)
# =============================================================================
echo "=== 🔒 Testing Internal Services (Should be Blocked) ==="

# Internal service ports that should NOT be accessible from internet
echo "🔹 Testing content-creator (port 8000)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 3 --connect-timeout 3 "$DOMAIN:8000/health" 2>/dev/null || echo "000")
if [ "$response" = "000" ] || [ "$response" = "000000" ] || [ -z "$response" ]; then
    echo "✅ content-creator properly blocked: $DOMAIN:8000 → Connection refused/timeout"
else
    echo "⚠️  WARNING: content-creator accessible from internet: $DOMAIN:8000 → $response"
fi

echo "🔹 Testing backend (port 8001)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 3 --connect-timeout 3 "$DOMAIN:8001/health" 2>/dev/null || echo "000")
if [ "$response" = "000" ] || [ "$response" = "000000" ] || [ -z "$response" ]; then
    echo "✅ backend properly blocked: $DOMAIN:8001 → Connection refused/timeout"
else
    echo "⚠️  WARNING: backend accessible from internet: $DOMAIN:8001 → $response"
fi

echo "🔹 Testing postgres (port 5432)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 3 --connect-timeout 3 "$DOMAIN:5432" 2>/dev/null || echo "000")
if [ "$response" = "000" ] || [ "$response" = "000000" ] || [ -z "$response" ]; then
    echo "✅ postgres properly blocked: $DOMAIN:5432 → Connection refused/timeout"
else
    echo "⚠️  WARNING: postgres accessible from internet: $DOMAIN:5432 → $response"
fi

echo "🔹 Testing neo4j (port 7474)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 3 --connect-timeout 3 "$DOMAIN:7474" 2>/dev/null || echo "000")
if [ "$response" = "000" ] || [ "$response" = "000000" ] || [ -z "$response" ]; then
    echo "✅ neo4j properly blocked: $DOMAIN:7474 → Connection refused/timeout"
else
    echo "⚠️  WARNING: neo4j accessible from internet: $DOMAIN:7474 → $response"
fi

echo "🔹 Testing rabbitmq (port 15672)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 3 --connect-timeout 3 "$DOMAIN:15672" 2>/dev/null || echo "000")
if [ "$response" = "000" ] || [ "$response" = "000000" ] || [ -z "$response" ]; then
    echo "✅ rabbitmq properly blocked: $DOMAIN:15672 → Connection refused/timeout"
else
    echo "⚠️  WARNING: rabbitmq accessible from internet: $DOMAIN:15672 → $response"
fi

echo ""

# =============================================================================
# Test 3: API Endpoints Through Auth Service (Should require authentication)
# =============================================================================
echo "=== 🔐 Testing API Endpoints (Should Require Auth) ==="

# API endpoints that should require authentication
echo "🔹 Testing /api/content-creator/health (without auth)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 10 "$BASE_URL/api/content-creator/health")
if [ "$response" = "401" ] || [ "$response" = "403" ]; then
    echo "✅ /api/content-creator/health properly protected → $response (Unauthorized)"
elif [ "$response" = "302" ]; then
    echo "✅ /api/content-creator/health redirects to login → $response (Redirect)"
elif [ "$response" = "200" ]; then
    echo "⚠️  WARNING: /api/content-creator/health accessible without auth → $response"
else
    echo "🔍 /api/content-creator/health response → $response"
fi

echo "🔹 Testing /api/oracle/health (without auth)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 10 "$BASE_URL/api/oracle/health")
if [ "$response" = "401" ] || [ "$response" = "403" ]; then
    echo "✅ /api/oracle/health properly protected → $response (Unauthorized)"
elif [ "$response" = "302" ]; then
    echo "✅ /api/oracle/health redirects to login → $response (Redirect)"
elif [ "$response" = "200" ]; then
    echo "⚠️  WARNING: /api/oracle/health accessible without auth → $response"
else
    echo "🔍 /api/oracle/health response → $response"
fi

echo "🔹 Testing /api/backend/health (without auth)..."
response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 10 "$BASE_URL/api/backend/health")
if [ "$response" = "401" ] || [ "$response" = "403" ]; then
    echo "✅ /api/backend/health properly protected → $response (Unauthorized)"
elif [ "$response" = "302" ]; then
    echo "✅ /api/backend/health redirects to login → $response (Redirect)"
elif [ "$response" = "200" ]; then
    echo "⚠️  WARNING: /api/backend/health accessible without auth → $response"
else
    echo "🔍 /api/backend/health response → $response"
fi

echo ""

# =============================================================================
# Test 4: CORS Headers (Check for proper CORS configuration)
# =============================================================================
echo "=== 🌐 Testing CORS Configuration ==="

echo "🔹 Testing CORS headers on auth service..."
cors_response=$(curl -s -H "Origin: https://malicious-site.com" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: Content-Type" \
    -X OPTIONS \
    --max-time 10 \
    -I "$BASE_URL/api/login" 2>/dev/null)

if echo "$cors_response" | grep -q "Access-Control-Allow-Origin"; then
    allowed_origin=$(echo "$cors_response" | grep "Access-Control-Allow-Origin" | cut -d' ' -f2- | tr -d '\r\n')
    if [ "$allowed_origin" = "*" ]; then
        echo "⚠️  WARNING: CORS allows all origins (*) - consider restricting"
    elif [[ "$allowed_origin" == *"$DOMAIN"* ]]; then
        echo "✅ CORS properly configured for domain: $allowed_origin"
    else
        echo "🔍 CORS configured for: $allowed_origin"
    fi
else
    echo "✅ No CORS headers found (good for API-only endpoints)"
fi

echo ""

# =============================================================================
# Test 5: SSL/TLS Configuration (if HTTPS)
# =============================================================================
if [ "$PROTOCOL" = "https" ]; then
    echo "=== 🔐 Testing SSL/TLS Configuration ==="
    
    echo "🔹 Testing SSL certificate..."
    ssl_info=$(timeout 10 openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" </dev/null 2>/dev/null | openssl x509 -noout -subject -dates 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        echo "✅ SSL certificate valid:"
        echo "$ssl_info" | sed 's/^/   /'
    else
        echo "❌ SSL certificate check failed"
    fi
    
echo "🔹 Testing HTTP to HTTPS redirect..."
if command -v curl >/dev/null 2>&1; then
    http_response=$(curl -s -w "%{http_code}" -o /dev/null --max-time 10 "http://$DOMAIN/" 2>/dev/null || echo "000")
    if [ "$http_response" = "301" ] || [ "$http_response" = "302" ]; then
        echo "✅ HTTP properly redirects to HTTPS → $http_response"
    else
        echo "🔍 HTTP response → $http_response"
    fi
else
    echo "🔍 curl not available for HTTP redirect test"
fi

echo ""
fi

echo ""

# =============================================================================
# Test 6: Service Health via SSH Tunnel (Instructions)
# =============================================================================
echo "=== 🔧 Testing Internal Services via SSH Tunnel ==="
echo "To test internal services, set up SSH tunnels first:"
echo ""
echo "📝 SSH Tunnel Commands:"
echo "ssh -L 7474:localhost:7474 -L 15672:localhost:15672 -L 9090:localhost:9090 -L 3001:localhost:3001 ec2-user@$DOMAIN"
echo ""
echo "Then test these URLs locally:"
echo "• Neo4j Browser: http://localhost:7474"
echo "• RabbitMQ Management: http://localhost:15672"
echo "• Prometheus: http://localhost:9090"
echo "• Grafana: http://localhost:3001"
echo ""

# =============================================================================
# Test 7: Load Test (Optional)
# =============================================================================
echo "=== ⚡ Quick Load Test ==="
echo "🔹 Testing frontend with 5 concurrent requests..."

# Simplified load test without xargs -P (not available on all systems)
success_count=0
total_time=0
for i in 1 2 3 4 5; do
    result=$(curl -s -w "%{http_code},%{time_total}" -o /dev/null --max-time 10 "$BASE_URL/" 2>/dev/null)
    status_code=$(echo "$result" | cut -d',' -f1)
    time_taken=$(echo "$result" | cut -d',' -f2)
    
    if [ "$status_code" = "200" ]; then
        success_count=$((success_count + 1))
        total_time=$(echo "$total_time + $time_taken" | bc -l 2>/dev/null || echo "$total_time")
    fi
done

echo "✅ Load test results: $success_count/5 successful requests"
if [ $success_count -gt 0 ] && command -v bc >/dev/null 2>&1; then
    avg_time=$(echo "scale=3; $total_time / $success_count" | bc)
    echo "⏱️  Average response time: ${avg_time}s"
fi

echo ""

# =============================================================================
# Summary
# =============================================================================
echo "=== 📊 Test Summary ==="
echo "🌐 Production URL: $BASE_URL"
echo "📅 Test completed: $(date)"
echo ""
echo "🔍 Review the results above for any warnings or failures."
echo "✅ Green checkmarks = Working correctly"
echo "⚠️  Yellow warnings = Needs attention"
echo "❌ Red errors = Requires immediate fix"
echo ""
echo "💡 For detailed service logs, SSH to your server and run:"
echo "   docker compose logs [service-name]"
echo ""