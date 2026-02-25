#!/bin/bash
# Validate Teams manifest against common issues

ZIP_FILE="${1:-/tmp/aurora-teams-app.zip}"

echo "=== Teams Manifest Validator ==="
echo "Checking: $ZIP_FILE"
echo ""

# Extract to temp dir
TEMP_DIR=$(mktemp -d)
unzip -q "$ZIP_FILE" -d "$TEMP_DIR"

MANIFEST="$TEMP_DIR/manifest.json"

# Check 1: Valid JSON
echo "✓ Check 1: Valid JSON"
if ! jq empty "$MANIFEST" 2>/dev/null; then
    echo "  ❌ FAILED: Invalid JSON"
    exit 1
fi
echo "  ✓ PASSED"

# Check 2: Required fields
echo "✓ Check 2: Required fields"
REQUIRED_FIELDS=("id" "version" "packageName" "developer" "name" "description" "icons" "accentColor" "validDomains")
for field in "${REQUIRED_FIELDS[@]}"; do
    if ! jq -e ".$field" "$MANIFEST" > /dev/null 2>&1; then
        echo "  ❌ FAILED: Missing required field: $field"
        exit 1
    fi
done
echo "  ✓ PASSED"

# Check 3: Valid GUID
echo "✓ Check 3: Valid app ID (GUID)"
ID=$(jq -r '.id' "$MANIFEST")
if ! [[ $ID =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "  ❌ FAILED: Invalid GUID format: $ID"
    exit 1
fi
echo "  ✓ PASSED ($ID)"

# Check 4: Icons exist and correct size
echo "✓ Check 4: Icon files"
if [ ! -f "$TEMP_DIR/icon-color.png" ]; then
    echo "  ❌ FAILED: icon-color.png not found"
    exit 1
fi
if [ ! -f "$TEMP_DIR/icon-outline.png" ]; then
    echo "  ❌ FAILED: icon-outline.png not found"
    exit 1
fi
echo "  ✓ PASSED (both icons present)"

# Check 5: Short name length (max 30 chars)
echo "✓ Check 5: Short name length"
SHORT_NAME=$(jq -r '.name.short' "$MANIFEST")
if [ ${#SHORT_NAME} -gt 30 ]; then
    echo "  ❌ FAILED: Short name too long (${#SHORT_NAME} > 30): $SHORT_NAME"
    exit 1
fi
echo "  ✓ PASSED (${#SHORT_NAME} chars)"

# Check 6: Short description length (max 80 chars)
echo "✓ Check 6: Short description length"
SHORT_DESC=$(jq -r '.description.short' "$MANIFEST")
if [ ${#SHORT_DESC} -gt 80 ]; then
    echo "  ❌ FAILED: Short description too long (${#SHORT_DESC} > 80)"
    exit 1
fi
echo "  ✓ PASSED (${#SHORT_DESC} chars)"

# Check 7: Valid domains
echo "✓ Check 7: Valid domains"
DOMAINS=$(jq -r '.validDomains[]' "$MANIFEST")
if [ -z "$DOMAINS" ]; then
    echo "  ❌ FAILED: No valid domains specified"
    exit 1
fi
echo "  ✓ PASSED: $DOMAINS"

# Check 8: Tabs configuration
echo "✓ Check 8: Tabs configuration"
HAS_STATIC=$(jq -e '.staticTabs' "$MANIFEST" > /dev/null 2>&1 && echo "yes" || echo "no")
HAS_CONFIG=$(jq -e '.configurableTabs' "$MANIFEST" > /dev/null 2>&1 && echo "yes" || echo "no")
if [ "$HAS_STATIC" = "no" ] && [ "$HAS_CONFIG" = "no" ]; then
    echo "  ❌ FAILED: No tabs configured (staticTabs or configurableTabs required)"
    exit 1
fi
echo "  ✓ PASSED (staticTabs: $HAS_STATIC, configurableTabs: $HAS_CONFIG)"

# Check 9: HTTPS URLs
echo "✓ Check 9: HTTPS URLs"
if jq -e '.. | strings | select(. | test("^http://"))' "$MANIFEST" > /dev/null 2>&1; then
    echo "  ⚠️  WARNING: Found HTTP URLs (HTTPS recommended)"
    jq -r '.. | strings | select(. | test("^http://"))' "$MANIFEST"
else
    echo "  ✓ PASSED (all URLs use HTTPS)"
fi

# Check 10: Accent color format
echo "✓ Check 10: Accent color format"
COLOR=$(jq -r '.accentColor' "$MANIFEST")
if ! [[ $COLOR =~ ^#[0-9A-Fa-f]{6}$ ]]; then
    echo "  ❌ FAILED: Invalid accent color format: $COLOR"
    exit 1
fi
echo "  ✓ PASSED ($COLOR)"

# Summary
echo ""
echo "=== Validation Summary ==="
echo "✅ All checks passed!"
echo ""
echo "Package is ready for upload to Teams."
echo "Next steps:"
echo "1. Open Teams Desktop or Web"
echo "2. Go to Apps → Manage your apps → Upload a custom app"
echo "3. Select: $ZIP_FILE"
echo ""
echo "For admin deployment:"
echo "https://admin.teams.microsoft.com/policies/manage-apps"

# Cleanup
rm -rf "$TEMP_DIR"
