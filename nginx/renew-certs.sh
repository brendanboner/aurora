#!/bin/bash
# =============================================================================
# SSL Certificate Renewal Script
# =============================================================================
# This script runs daily via cron to:
# 1. Attempt to renew Let's Encrypt certificates
# 2. Reload nginx if certificates were renewed
# =============================================================================

set -e

DOMAIN="${DOMAIN:-localhost}"

echo "===== SSL Certificate Renewal Check ====="
echo "Date: $(date)"
echo "Domain: $DOMAIN"

# Skip renewal for localhost
if [ "$DOMAIN" = "localhost" ]; then
    echo "⚠ Domain is 'localhost', skipping renewal"
    exit 0
fi

# Attempt certificate renewal
echo "→ Checking for certificate renewal..."
if certbot renew --webroot --webroot-path=/var/www/certbot --quiet; then
    echo "✓ Certificate renewal check completed"
    
    # Reload nginx if certificates were renewed
    echo "→ Reloading nginx..."
    nginx -s reload
    
    echo "✓ Nginx reloaded with renewed certificates"
else
    echo "⚠ Certificate renewal check failed (certificates may still be valid)"
fi

exit 0
