#!/usr/bin/env bash
# scripts/create-agent-manifest.sh
#
# Generates a Teams app package (.zip) for a named Aurora agent.
# Each agent gets its own bot identity — a separate app package that IT can deploy.
#
# Usage:
#   ./scripts/create-agent-manifest.sh <teams-slug> <app-id> <bot-id> [output-dir]
#
# Arguments:
#   teams-slug   e.g. aurora-ietf, aurora-wba-wifi-design-wg, aurora-mister-multipath
#   app-id       Azure AD App Registration ID for this agent's app (the "App (client) ID")
#   bot-id       Azure Bot Service Bot ID (often the same as app-id for single-tenant bots)
#   output-dir   Directory to write the .zip into (default: ./dist/teams-packages)
#
# Prerequisites:
#   - zip (brew install zip on macOS)
#   - ImageMagick convert (brew install imagemagick) — optional, for auto-generating placeholder icons
#
# Example:
#   ./scripts/create-agent-manifest.sh aurora-ietf 00000000-0000-0000-0000-000000000001 00000000-0000-0000-0000-000000000001

set -euo pipefail

SLUG="${1:-}"
APP_ID="${2:-}"
BOT_ID="${3:-${APP_ID}}"
OUTPUT_DIR="${4:-./dist/teams-packages}"

if [[ -z "$SLUG" || -z "$APP_ID" ]]; then
  echo "Usage: $0 <teams-slug> <app-id> [bot-id] [output-dir]"
  echo "  teams-slug  e.g. aurora-ietf"
  echo "  app-id      Azure AD App Registration ID"
  echo "  bot-id      Azure Bot Service Bot ID (default: same as app-id)"
  exit 1
fi

# Derive human-readable display name from slug:  aurora-wba-wifi-design-wg → WBA Wifi Design Wg
AGENT_SUFFIX="${SLUG#aurora-}"                          # strip "aurora-" prefix
DISPLAY_WORDS=$(echo "$AGENT_SUFFIX" | tr '-' ' ')     # hyphens → spaces
# Title-case each word
DISPLAY_NAME=$(echo "$DISPLAY_WORDS" | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2)); print}')

APP_FULL_NAME="Aurora — ${DISPLAY_NAME}"
APP_SHORT_NAME="${DISPLAY_NAME}"
PKG_NAME="com.aurora.teams.${AGENT_SUFFIX//-/}"       # valid package name (no hyphens)
# Unique version per build
VERSION="1.0.0"

WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

mkdir -p "$OUTPUT_DIR"

echo "Building Teams package for: ${SLUG}"
echo "  Display name : ${APP_FULL_NAME}"
echo "  App ID       : ${APP_ID}"
echo "  Bot ID       : ${BOT_ID}"

# ── Manifest ──────────────────────────────────────────────────────────────────
cat > "${WORK_DIR}/manifest.json" << EOF
{
  "\$schema": "https://developer.microsoft.com/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
  "manifestVersion": "1.16",
  "version": "${VERSION}",
  "id": "${APP_ID}",
  "packageName": "${PKG_NAME}",
  "developer": {
    "name": "Aurora Team",
    "websiteUrl": "https://github.com/extremenetworks/octo-rapid-aurora",
    "privacyUrl": "https://github.com/extremenetworks/octo-rapid-aurora/blob/main/PRIVACY.md",
    "termsOfUseUrl": "https://github.com/extremenetworks/octo-rapid-aurora/blob/main/TERMS.md"
  },
  "name": {
    "short": "${APP_SHORT_NAME}",
    "full": "${APP_FULL_NAME}"
  },
  "description": {
    "short": "Aurora agent: ${DISPLAY_NAME} — personalized knowledge updates",
    "full": "This is the Aurora ${DISPLAY_NAME} agent. It provides proactive content updates, intelligent Q&A, and topic insights from the Aurora knowledge graph — scoped to the ${DISPLAY_NAME} domain. Use @${SLUG} in any Teams chat or channel."
  },
  "icons": {
    "color": "color.png",
    "outline": "outline.png"
  },
  "accentColor": "#4A90E2",
  "bots": [
    {
      "botId": "${BOT_ID}",
      "scopes": ["personal", "team", "groupchat"],
      "supportsFiles": false,
      "isNotificationOnly": false,
      "commandLists": [
        {
          "scopes": ["personal", "team", "groupchat"],
          "commands": [
            {
              "title": "feed",
              "description": "Show your latest content from ${DISPLAY_NAME}"
            },
            {
              "title": "help",
              "description": "Show available commands"
            }
          ]
        }
      ]
    }
  ],
  "permissions": ["identity", "messageTeamMembers"],
  "validDomains": []
}
EOF

# ── Icons ─────────────────────────────────────────────────────────────────────
# Use existing Aurora icons as base; generate agent-specific ones if ImageMagick available
ICON_SRC="./teams-agent/appPackage"
if [[ -f "${ICON_SRC}/color.png" ]]; then
  cp "${ICON_SRC}/color.png" "${WORK_DIR}/color.png"
  cp "${ICON_SRC}/outline.png" "${WORK_DIR}/outline.png"
  echo "  Icons        : copied from Aurora base"
  # Attempt to add a label overlay if ImageMagick is available
  if command -v convert &>/dev/null; then
    LABEL="${DISPLAY_NAME:0:4}"  # first 4 chars as label
    convert "${WORK_DIR}/color.png" \
      -gravity SouthEast -pointsize 18 -fill white \
      -annotate +4+4 "${LABEL}" \
      "${WORK_DIR}/color.png" 2>/dev/null && \
      echo "  Icons        : label '${LABEL}' added via ImageMagick" || true
  fi
else
  # Fallback: create minimal 192x192 placeholder
  echo "  Icons        : source not found at ${ICON_SRC} — creating placeholders"
  # Write a minimal 1x1 transparent PNG as placeholder
  printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82' \
    > "${WORK_DIR}/color.png"
  cp "${WORK_DIR}/color.png" "${WORK_DIR}/outline.png"
fi

# ── Package ───────────────────────────────────────────────────────────────────
OUTPUT_FILE="${OUTPUT_DIR}/${SLUG}.zip"
(cd "$WORK_DIR" && zip -q "${OLDPWD}/${OUTPUT_FILE}" manifest.json color.png outline.png)

echo ""
echo "✅ Package written: ${OUTPUT_FILE}"
echo ""
echo "Next steps:"
echo "  1. Sideload for testing: Teams → Apps → Upload a custom app → ${OUTPUT_FILE}"
echo "  2. Org-wide deployment: Teams Admin Center → Manage apps → Upload"
echo "  3. Assign the bot endpoint in Azure Bot Service:"
echo "     https://<your-domain>/api/messages/${SLUG}"
echo ""
echo "Make sure the bot's messaging endpoint URL includes the slug so Aurora"
echo "can route to the correct agent persona."
