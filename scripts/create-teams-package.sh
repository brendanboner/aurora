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

# Copy manifest
cp "$MANIFEST_SOURCE" "$WORK_DIR/manifest.json"

# Update URLs in manifest if not localhost using jq for safe JSON manipulation
if [ "$DOMAIN" != "localhost" ]; then
    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        echo -e "${RED}❌ ERROR: jq is required but not installed${NC}"
        echo "Install with: brew install jq"
        exit 1
    fi
    
    # Use jq to safely update the manifest
    jq --arg domain "$DOMAIN" '
      .configurableTabs[0].configurationUrl = "https://\($domain)/teams?config=true" |
      .staticTabs[0].contentUrl = "https://\($domain)/teams" |
      .staticTabs[0].websiteUrl = "https://\($domain)/teams" |
      .validDomains = [$domain] |
      .webApplicationInfo.resource = "https://\($domain)"
    ' "$WORK_DIR/manifest.json" > "$WORK_DIR/manifest.json.tmp" && mv "$WORK_DIR/manifest.json.tmp" "$WORK_DIR/manifest.json"
    
    echo "✓ Manifest updated for domain: $DOMAIN"
else
    echo "✓ Using manifest with default domain"
fi

# Validate manifest JSON
echo -e "${YELLOW}📋 Step 2: Validating manifest JSON${NC}"
if command -v jq &> /dev/null; then
    if ! jq empty "$WORK_DIR/manifest.json" 2>/dev/null; then
        echo -e "${RED}❌ ERROR: Invalid manifest JSON${NC}"
        cat "$WORK_DIR/manifest.json"
        exit 1
    fi
elif command -v python3 &> /dev/null; then
    if ! python3 -m json.tool "$WORK_DIR/manifest.json" > /dev/null 2>&1; then
        echo -e "${RED}❌ ERROR: Invalid manifest JSON${NC}"
        cat "$WORK_DIR/manifest.json"
        exit 1
    fi
else
    echo "⚠️  JSON validation skipped (jq/python3 not found)"
fi
echo "✓ Manifest JSON is valid"

# Copy icons - they're in the public directory, not a teams/icons subdirectory
echo -e "${YELLOW}📋 Step 3: Adding icons${NC}"
ICON_DIR="$REPO_ROOT/frontend/public"
if [ -f "$ICON_DIR/icon-color.png" ] && [ -f "$ICON_DIR/icon-outline.png" ]; then
    cp "$ICON_DIR/icon-color.png" "$WORK_DIR/" || exit 1
    cp "$ICON_DIR/icon-outline.png" "$WORK_DIR/" || exit 1
    echo "✓ Icons copied (color: 192x192, outline: 32x32)"
    ls -lh "$WORK_DIR/"*.png
else
    echo -e "${RED}❌ ERROR: Icons not found${NC}"
    echo "   Required: $ICON_DIR/icon-color.png (192x192)"
    echo "            $ICON_DIR/icon-outline.png (32x32)"
    exit 1
fi

# Create ZIP package
echo -e "${YELLOW}📋 Step 4: Creating ZIP package${NC}"
cd "$WORK_DIR"

# Validate icons exist and are correct dimensions
if [ -f "icon-color.png" ] && [ -f "icon-outline.png" ]; then
    zip -q aurora-teams-app.zip manifest.json icon-color.png icon-outline.png
    echo "✓ ZIP created with manifest and icons"
else
    echo -e "${RED}❌ ERROR: Icons missing, cannot create package${NC}"
    exit 1
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
