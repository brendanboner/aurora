# Aurora Teams Integration — IT Admin Guide

**Audience:** IT / Azure AD / Microsoft 365 administrators  
**Purpose:** Everything needed to deploy Aurora in Microsoft Teams — initial bot setup, SSO, per-agent personas, and proactive messaging.

---

## What Aurora Does in Teams

Aurora is a knowledge-graph AI assistant that works in Teams in two ways:

1. **Reactive Q&A** — users ask questions, Aurora answers using its knowledge graph and LLMs
2. **Proactive feed** — when a creator agent publishes new content, Aurora pushes it as a card to subscribed conversations — no user action required

### User Commands (quick reference)

| Command | What it does |
|---------|-------------|
| `feed` | Pull latest content feed |
| `@aurora-ietf What's new with QUIC?` | Ask a specific named agent by slug |
| `setChannelAgent @aurora-wba-wifi-design-wg` | Route all messages in this channel through one agent |
| `clearChannelAgent` | Remove the channel-scoped agent |
| `subscribe @aurora-ietf` | Receive proactive pushes from the IETF agent |
| `unsubscribe @aurora-ietf` | Stop receiving pushes |
| `agents` | List all available creator agents |
| `help` | Full command reference |

---

## Architecture

```
Teams User
  └── @Aurora Bot
        └── Teams message → Bot Framework webhook
              → https://aurora-octo.xcloudiq.com/bot/api/messages
              → teams-agent (Node.js, Docker)
                  ├── ChatHandler     → Oracle (LLM Q&A)
                  ├── AgentHandler    → Oracle with agent persona context
                  ├── FeedHandler     → content_creator_service
                  └── ProactiveMessenger ← content_creator_service (push)

content_creator_service
  └── on new post → POST /internal/push-feed-update (Docker-internal only)
        → ProactiveMessenger → adapter.continueConversation()
              → Adaptive Card pushed to all subscribed conversations
```

Conversation references (needed for proactive push) are stored in PostgreSQL when the bot joins any conversation.

---

## Prerequisites

- Global Admin or Teams Service Admin access in your Microsoft 365 tenant
- Azure subscription (same tenant as Teams)
- Aurora already deployed at a public HTTPS domain (e.g. `aurora-octo.xcloudiq.com`)
- `docker compose --profile teams up -d` running on the Aurora host

---

## Step 1 — Verify the Aurora Azure App Registration (Teams SSO)

Aurora's frontend uses Teams SSO (silent Azure AD login). This App Registration already exists:

- **App Client ID:** `5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b`  
  _(embedded in `frontend/public/manifest.json` → `webApplicationInfo.id`)_

**Check in Azure Portal → App registrations → find by client ID above:**

1. **Authentication** → Redirect URIs: must include `https://aurora-octo.xcloudiq.com/api/auth/callback`
2. **Expose an API**:
   - Application ID URI: `api://aurora-octo.xcloudiq.com/5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b`
   - Scope: `access_as_user` — Who can consent: **Admins and users**
3. **API permissions** (delegated): `openid`, `email`, `profile` — all consented
4. Note the **Tenant ID** from the Overview tab

**Update Aurora `.env`:**
```
AZURE_TENANT_ID=<your-tenant-guid>
AZURE_APP_CLIENT_ID=5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b
```

---

## Step 2 — Create the Azure Bot Registration (@Aurora Bot)

This registers the single Aurora bot that all conversations use.

1. **Azure Portal → Create a resource → Azure Bot**
2. Fill in:
   - **Bot handle:** `aurora-teams-bot`
   - **Pricing tier:** `F0` (free) for testing; `S1` for production
   - **Microsoft App type:** `Single tenant`
   - **Creation type:** `Create new Microsoft App ID`
3. After creation, go to **Configuration**:
   - **Messaging endpoint:** `https://aurora-octo.xcloudiq.com/bot/api/messages`
   - Note the **Microsoft App ID** → this is `BOT_ID`
4. **Configuration → Manage Password** → create a client secret → note it as `BOT_PASSWORD`
5. **Channels → Microsoft Teams → Save**

**Update Aurora `.env`:**
```
BOT_ID=<microsoft-app-id>
BOT_PASSWORD=<client-secret>
```

---

## Step 3 — Grant Microsoft Graph Permissions (Email Lookup)

The bot looks up user email addresses from AAD Object IDs via Graph API. Without this, Aurora creates users with synthetic IDs (`<aad-oid>@teams.aad`) — everything works but user profiles won't be linked by email.

In the **Bot's Azure App Registration** (same app created in Step 2):

1. **API permissions → Add a permission → Microsoft Graph → Application permissions**
2. Add: `User.Read.All`
3. Click **Grant admin consent** ← requires Global Admin

**Update Aurora `.env`:**
```
GRAPH_TENANT_ID=<your-tenant-guid>
GRAPH_CLIENT_ID=<bot-app-id>
GRAPH_CLIENT_SECRET=<bot-client-secret>
```

> `User.Read.All` requires admin consent. This is the only permission in the entire Aurora stack that does.

---

## Step 4 — Build and Deploy the Teams App Package

On the Aurora server or a developer machine with the repo:

```bash
# Start the teams-agent container (if not already running)
docker compose --profile teams up -d teams-agent

# Build the app package (substitutes domain and BOT_ID into manifest.json)
BOT_ID=<your-bot-app-id> ./scripts/create-teams-package.sh aurora-octo.xcloudiq.com
# Output: aurora-teams-app.zip
```

**Upload to Teams Admin Center:**

1. Go to `https://admin.teams.microsoft.com`
2. **Teams apps → Manage apps → Upload new app**
3. Select `aurora-teams-app.zip`
4. Click **Publish** to make it available org-wide
5. Optionally use **App setup policies** to pre-install Aurora for specific users/groups

**For testing (sideload without admin approval):**  
Teams → Apps → Upload a custom app → select `aurora-teams-app.zip`

---

## Step 5 — Set Agent Teams Slugs

For `@aurora-<slug>` routing to work, each creator agent needs a `teams_slug` set in the database. This is done by the Aurora team, not IT:

```sql
-- Run on the Aurora PostgreSQL instance
UPDATE creator_agent SET teams_slug = 'aurora-ietf'                WHERE name = 'IETF Monitor';
UPDATE creator_agent SET teams_slug = 'aurora-wba-wifi-design-wg'  WHERE name = 'WBA Wi-Fi Design';
UPDATE creator_agent SET teams_slug = 'aurora-mister-multipath'    WHERE name = 'Mister Multipath';
```

Users can then type `@aurora-ietf What's happening with QUIC?` and the message routes through the IETF agent persona.

---

## Step 6 — Start the Bot and Verify

```bash
# Start teams-agent
docker compose --profile teams up -d teams-agent

# Verify
docker compose logs -f teams-agent

# Test the health endpoint
curl https://aurora-octo.xcloudiq.com/bot/api/health
```

---

## Phase 2 (Optional) — Per-Agent Bot Identities

By default, all agent personas (`@aurora-ietf`, `@aurora-wba-wifi-design-wg`) are served by the **single `@Aurora` bot**. The agent identity appears in the message body.

If you want each agent to appear as a **distinct named bot** in Teams (own avatar, display name in @mention dropdown), each agent needs its own Azure Bot App Registration.

### What IT needs to create (once per agent)

#### 1 — Azure AD App Registration

1. **Azure Portal → App registrations → New registration**
2. Name: `Aurora — <Agent Display Name>` (e.g. `Aurora — IETF Agent`)
3. Supported account types: **Single tenant**
4. Click **Register** → note the **Application (client) ID**
5. **Certificates & secrets → New client secret** → note the value

#### 2 — Azure Bot Service

1. **Azure Portal → Create → Azure Bot**
2. Bot handle: `aurora-<slug>` (e.g. `aurora-ietf`)
3. Microsoft App ID: **Use existing** → paste the App ID from above
4. Messaging endpoint: `https://aurora-octo.xcloudiq.com/bot/api/messages/aurora-ietf`
   > The slug in the URL path tells Aurora which agent persona to use
5. **Channels → Microsoft Teams → Save**

#### 3 — Teams App Package

```bash
# Run from Aurora repo root
./scripts/create-agent-manifest.sh aurora-ietf <app-id> <bot-id>
# Output: dist/teams-packages/aurora-ietf.zip
```

Deploy the .zip via Teams Admin Center (same as Step 4).

#### 4 — Provide credentials to Aurora team

```
AGENT_BOT_AURORA_IETF_APP_ID=<app-id>
AGENT_BOT_AURORA_IETF_APP_SECRET=<client-secret>
```

Naming convention: `AGENT_BOT_<SLUG_UPPERCASE_UNDERSCORED>_APP_ID` / `_APP_SECRET`

### Recommended agents for Phase 2 (priority order)

| Slug | Display Name | Domain |
|------|-------------|--------|
| `aurora-ietf` | IETF Agent | QUIC, HTTP/3, internet standards |
| `aurora-wba-wifi-design-wg` | WBA Wi-Fi Design WG | Wi-Fi design, 6 GHz, Hotspot 2.0 |
| `aurora-ieee-802` | IEEE 802 Agent | 802.11be, 802.1Q, Ethernet |
| `aurora-mister-multipath` | Mister Multipath | MPTCP, QUIC, multipath networking |

> **Note:** Phase 1 (slug routing via single bot) gives identical *functionality* to Phase 2 — the only difference is whether the bot appears as `@Aurora` or as `@aurora-ietf` in the Teams mention dropdown. Start with Phase 1; upgrade later with no code changes.

---

## Full Use Case Summary

| Use case | Teams feature | IT action |
|----------|--------------|-----------|
| Personal chat with Aurora | Bot, personal scope | Install Aurora app |
| Q&A in a team channel | Bot, team scope | Add bot to channel |
| Proactive feed pushes to personal chat | Bot Framework proactive messaging | None — Aurora handles this |
| Proactive feed pushes to a channel | Same | Add bot to channel, user subscribes |
| Ask named agent (`@aurora-ietf ...`) | Single bot + slug routing | Set `teams_slug` in DB (Aurora team) |
| Lock channel to one agent | `setChannelAgent` command | None |
| True per-agent identity in @mention dropdown | Per-agent app registration | One App Registration + package per agent |
| Org-wide pre-install (no user action needed) | App setup policies | Teams Admin — App setup policies |

---

## Environment Variables Reference

| Variable | Description | Required For |
|----------|-------------|-------------|
| `AZURE_TENANT_ID` | Azure AD tenant GUID | Teams SSO tab auth |
| `AZURE_APP_CLIENT_ID` | Azure App Registration client ID | Teams SSO tab auth |
| `BOT_ID` | Bot Framework App ID | @Aurora bot |
| `BOT_PASSWORD` | Bot Framework client secret | @Aurora bot |
| `GRAPH_TENANT_ID` | Azure tenant for Graph API | Bot email lookup |
| `GRAPH_CLIENT_ID` | Bot app ID for Graph API | Bot email lookup |
| `GRAPH_CLIENT_SECRET` | Bot client secret for Graph API | Bot email lookup |
| `POSTGRES_HOST/USER/PASSWORD/DB` | PostgreSQL connection | Conversation reference store (proactive push) |
| `TEAMS_AGENT_URL` | Internal URL to teams-agent (set on content_creator_service) | Proactive push trigger |

---

## Azure Permissions Summary

| Permission | Type | Purpose | Admin Consent |
|------------|------|---------|---------------|
| `openid`, `email`, `profile` | Delegated | Teams SSO login | No |
| `access_as_user` | Delegated (custom scope) | Teams SSO token validation | No (user consent) |
| `User.Read.All` | Application | Bot → Graph API email lookup | **Yes** |
| Teams Bot channel | Channel | Bot messaging in Teams | No |

---

## Troubleshooting

**Tab shows login button instead of auto-logging in**
- Confirm `AZURE_TENANT_ID` and `AZURE_APP_CLIENT_ID` are set in `.env`
- Verify `webApplicationInfo.id` in `manifest.json` matches the Azure App Registration client ID
- Check **Expose an API** scope (`access_as_user`) is configured

**Bot doesn't respond in Teams**
- Verify `BOT_ID` and `BOT_PASSWORD` in `.env`
- Confirm messaging endpoint in Azure Bot → Configuration: `https://aurora-octo.xcloudiq.com/bot/api/messages`
- Check logs: `docker compose logs -f teams-agent`
- Confirm Microsoft Teams channel is enabled: Azure Bot → Channels → Teams ✓

**`@aurora-ietf` returns "agent not found"**
- Check `teams_slug` is set: `SELECT name, teams_slug FROM creator_agent WHERE teams_slug IS NOT NULL;`
- Confirm the slug matches exactly (e.g. `aurora-ietf` not `ietf`)

**Proactive pushes not arriving**
- Check `TEAMS_AGENT_URL` is set in the content_creator_service environment
- Check logs: `docker compose logs -f teams-agent | grep ProactiveMessenger`
- Confirm the user typed `subscribe @aurora-<slug>` in the target conversation
- Verify the PostgreSQL `teams_conversation_references` table has the conversation: `SELECT conversation_id, subscribed_agent_slugs FROM teams_conversation_references;`

**Bot can't find user email**
- Expected if `GRAPH_CLIENT_SECRET` is not configured — bot falls back to synthetic ID
- Grant `User.Read.All` admin consent and set Graph API env vars in `.env`

**"App not found" in Teams**
- Check Teams Admin Center: **Manage apps → filter by Custom apps**
- App approval can take up to 24 hours after first submission

---

## Contacts

- **Aurora App Team:** bbonner (Extreme Networks)
- **Teams Admin Center:** https://admin.teams.microsoft.com
- **Azure Portal:** https://portal.azure.com

