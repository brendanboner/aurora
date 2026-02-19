#!/bin/bash

# Create Microsoft Teams App Package for Aurora
# Usage: ./scripts/create-teams-package.sh [domain] [output-path]
#
# Examples:
#   ./scripts/create-teams-package.sh                          # Uses localhost, outputs to ./aurora-teams-app.zip
#   ./scripts/create-teams-package.sh aurora.company.com       # Uses custom domain
#   ./scripts/create-teams-package.sh aurora.company.com /tmp  # Custom output path

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
DOMAIN="${1:-localhost}"
OUTPUT_DIR="${2:-.}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_SOURCE="$REPO_ROOT/frontend/public/manifest.json"
ICONS_SOURCE="$REPO_ROOT/frontend/public/teams/icons"
WORK_DIR="/tmp/aurora-teams-build-$(date +%s)"

# Convert OUTPUT_DIR to absolute path
OUTPUT_DIR="$(cd "$OUTPUT_DIR" 2>/dev/null && pwd)" || OUTPUT_DIR="$(cd "$REPO_ROOT" && pwd)"

echo -e "${GREEN}=== Aurora Teams App Package Builder ===${NC}"
echo "Domain: $DOMAIN"
echo "Output: $OUTPUT_DIR"
echo "Working directory: $WORK_DIR"
echo ""

# Create working directory
mkdir -p "$WORK_DIR"

# Check if manifest exists
if [ ! -f "$MANIFEST_SOURCE" ]; then
    echo -e "${RED}❌ ERROR: Manifest not found at $MANIFEST_SOURCE${NC}"
    echo "Please ensure frontend/public/manifest.json exists"
    exit 1
fi

echo -e "${YELLOW}📋 Step 1: Preparing manifest${NC}"

# Copy and update manifest with domain
cp "$MANIFEST_SOURCE" "$WORK_DIR/manifest.json"

# Update URLs in manifest if not localhost
if [ "$DOMAIN" != "localhost" ]; then
    # Update contentUrl and websiteUrl
    sed -i '' "s|http://localhost|https://$DOMAIN|g" "$WORK_DIR/manifest.json"
    
    # Update validDomains
    sed -i '' "s|\"localhost\"|\"$DOMAIN\"|g" "$WORK_DIR/manifest.json"
    sed -i '' "s|\"127.0.0.1\"|\"$DOMAIN\"|g" "$WORK_DIR/manifest.json"
    
    # Remove cloudfront default if custom domain provided
    sed -i '' "s|\"d23ew7gbss3vnh.cloudfront.net\"||g" "$WORK_DIR/manifest.json"
    sed -i '' 's/,$//' "$WORK_DIR/manifest.json"
    
    echo "✓ Manifest updated for domain: $DOMAIN"
else
    echo "✓ Using manifest with localhost domain"
fi

# Validate manifest JSON
echo -e "${YELLOW}📋 Step 2: Validating manifest JSON${NC}"
if ! node -e "JSON.parse(require('fs').readFileSync('$WORK_DIR/manifest.json'))" 2>/dev/null; then
    echo -e "${RED}❌ ERROR: Invalid manifest JSON${NC}"
    exit 1
fi
echo "✓ Manifest JSON is valid"

# Copy icons if they exist
echo -e "${YELLOW}📋 Step 3: Adding icons${NC}"
if [ -d "$ICONS_SOURCE" ]; then
    mkdir -p "$WORK_DIR/icons"
    if cp "$ICONS_SOURCE"/*.png "$WORK_DIR/icons/" 2>/dev/null; then
        echo "✓ Icons copied from $ICONS_SOURCE"
        ls -lh "$WORK_DIR/icons/"
    else
        echo "⚠️  No PNG icons found in $ICONS_SOURCE"
        echo "   You can create icons later before submitting to Teams Admin Center"
    fi
else
    echo "⚠️  Icons directory not found at $ICONS_SOURCE"
    echo "   You can create icons later before submitting to Teams Admin Center"
fi

# Create ZIP package
echo -e "${YELLOW}📋 Step 4: Creating ZIP package${NC}"
cd "$WORK_DIR"

if [ -d "icons" ] && [ "$(ls -A icons)" ]; then
    zip -r aurora-teams-app.zip manifest.json icons/ > /dev/null
    echo "✓ ZIP created with icons"
else
    zip -r aurora-teams-app.zip manifest.json > /dev/null
    echo "✓ ZIP created (no icons - add them before final submission)"
fi

# Prepare output directory and copy file BEFORE cleanup
mkdir -p "$OUTPUT_DIR"
OUTPUT_FILE="$OUTPUT_DIR/aurora-teams-app.zip"

# Only copy if not the same directory
if [ "$WORK_DIR" != "$(cd "$OUTPUT_DIR" && pwd)" ]; then
    cp aurora-teams-app.zip "$OUTPUT_FILE" || { echo -e "${RED}❌ Failed to copy ZIP file${NC}"; exit 1; }
else
    # Already in output directory
    mv aurora-teams-app.zip "$OUTPUT_FILE" || { echo -e "${RED}❌ Failed to move ZIP file${NC}"; exit 1; }
fi

FILE_SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)

echo ""
echo -e "${GREEN}✅ Package created successfully!${NC}"
echo ""
echo "📦 Package Details:"
echo "   Location: $OUTPUT_FILE"
echo "   Size: $FILE_SIZE"
echo "   Domain: $DOMAIN"
echo ""

echo "📋 Package Contents:"
unzip -l "$OUTPUT_FILE" | tail -n +4

echo ""
echo -e "${GREEN}=== Next Steps ===${NC}"
echo ""
echo "1️⃣  Test locally in Teams (immediate):"
echo "   - Open Teams Desktop"
echo "   - Apps → Manage your apps"
echo "   - Upload a custom app"
echo "   - Select: $OUTPUT_FILE"
echo ""
echo "2️⃣  Submit to Teams Admin Center (enterprise rollout):"
echo "   - Go to: https://admin.teams.microsoft.com"
echo "   - Teams apps → Manage apps → Publish an app"
echo "   - Upload the ZIP file"
echo "   - Wait for IT approval (2-5 business days)"
echo ""
echo "3️⃣  Before final submission:"
echo "   - Ensure icons are included (color.png 192x192, outline.png 32x32)"
echo "   - Test the contentUrl loads: https://$DOMAIN/teams"
echo "   - Verify icons are served at icon URLs"
echo ""

# Verify file exists and show full path
if [ -f "$OUTPUT_FILE" ]; then
    echo -e "${GREEN}✓ Package ready: $(cd "$(dirname "$OUTPUT_FILE")" && pwd)/$(basename "$OUTPUT_FILE")${NC}"
else
    echo -e "${RED}❌ ERROR: ZIP file not found at $OUTPUT_FILE${NC}"
    exit 1
fi

# Cleanup temp directory (now that file is copied)
rm -rf "$WORK_DIR"
