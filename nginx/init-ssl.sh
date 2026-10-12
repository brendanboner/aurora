#!/bin/bash
# =============================================================================
# SSL Certificate Initialization Script
# =============================================================================
# This script runs when the nginx container starts and:
# 1. Checks if SSL certificates exist
# 2. If not, creates self-signed certificates for initial startup
# 3. Obtains Let's Encrypt certificates after nginx is running
# 4. Reloads nginx with real certificates
# =============================================================================

set -e

DOMAIN="${DOMAIN:-localhost}"
EMAIL="${EMAIL:-admin@example.com}"
CERT_PATH="/etc/letsencrypt/live/$DOMAIN"

echo "===== SSL Certificate Initialization ====="
echo "Domain: $DOMAIN"
echo "Email: $EMAIL"

# Check if certificates already exist
if [ -d "$CERT_PATH" ] && [ -f "$CERT_PATH/fullchain.pem" ]; then
    echo "✓ SSL certificates already exist for $DOMAIN"
    exit 0
fi

echo "⚠ No SSL certificates found. Initializing..."

# Create directory for domain
mkdir -p "/etc/letsencrypt/live/$DOMAIN"

# Generate self-signed certificate for initial startup
echo "→ Generating self-signed certificate for initial startup..."
openssl req -x509 -nodes -newkey rsa:4096 \
    -days 1 \
    -keyout "$CERT_PATH/privkey.pem" \
    -out "$CERT_PATH/fullchain.pem" \
    -subj "/CN=$DOMAIN" \
    2>/dev/null

# Create chain.pem (copy of fullchain for self-signed)
cp "$CERT_PATH/fullchain.pem" "$CERT_PATH/chain.pem"

echo "✓ Self-signed certificate created"

# Background process to obtain real certificate after nginx starts
(
    echo "→ Waiting for nginx to start..."
    sleep 10

    echo "→ Requesting Let's Encrypt certificate..."
    if [ "$DOMAIN" != "localhost" ] && [ "$EMAIL" != "admin@example.com" ]; then
        # Request real Let's Encrypt certificate
        certbot certonly \
            --webroot \
            --webroot-path=/var/www/certbot \
            --email "$EMAIL" \
            --agree-tos \
            --no-eff-email \
            --force-renewal \
            -d "$DOMAIN" || {
                echo "⚠ Failed to obtain Let's Encrypt certificate"
                echo "   Using self-signed certificate"
                echo "   Make sure:"
                echo "   1. Domain is pointing to this server"
                echo "   2. Port 80 is accessible from internet"
                echo "   3. DOMAIN and EMAIL environment variables are set correctly"
                exit 0
            }

        echo "✓ Let's Encrypt certificate obtained successfully"
        
        # Reload nginx with new certificates
        echo "→ Reloading nginx..."
        nginx -s reload
        
        echo "✓ SSL certificate initialization complete"
    else
        echo "⚠ Domain is 'localhost' or email is not configured"
        echo "   Keeping self-signed certificate"
        echo "   Set DOMAIN and EMAIL environment variables for Let's Encrypt"
    fi
) &

exit 0
