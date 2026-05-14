#!/usr/bin/env bash
# Build the Aurora Teams app package (aurora-teams-app.zip) from manifest.json
# + the staged PNG icons, substituting the BOT_ID and APP_ID provided by IT.
#
# Usage:
#   APP_ID=<aad-app-id> BOT_ID=<bot-framework-id> ./build.sh
#
# Output: aurora-teams-app.zip in this directory, ready for Teams upload.

set -euo pipefail

: "${APP_ID:?APP_ID is required (AAD application ID from Azure)}"
: "${BOT_ID:?BOT_ID is required (Bot Framework Microsoft App ID)}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

for f in manifest.json color.png outline.png; do
  [[ -f "$f" ]] || { echo "Missing required file: $f" >&2; exit 1; }
done

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

sed -e "s/{{APP_ID}}/${APP_ID}/g" \
    -e "s/{{BOT_ID}}/${BOT_ID}/g" \
    manifest.json > "$STAGE/manifest.json"
cp color.png outline.png "$STAGE/"

rm -f aurora-teams-app.zip
( cd "$STAGE" && zip -q "$HERE/aurora-teams-app.zip" manifest.json color.png outline.png )

echo "Built $HERE/aurora-teams-app.zip"
