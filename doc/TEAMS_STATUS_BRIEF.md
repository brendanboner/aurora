# Aurora × Microsoft Teams — Status Brief

**Date:** May 2026  
**Prepared by:** OCTO Dev Team  
**Audience:** Management / Project Sponsor  
**Production URL:** https://aurora-octo.xcloudiq.com

---

## TL;DR

Aurora already runs as a web application with Microsoft Entra (Azure AD) SSO. We have now built a complete **Microsoft Teams integration** — a tab with chat and content feed, plus an @Aurora bot users can message in any channel. The tab is **deployable today**. The bot needs two IT/Azure actions (< 1 hour) before it's live.

---

## What We Have Built

### 1. Teams Tab ✅ Ready to deploy
A Teams-native panel that embeds directly in any team channel:
- **Left side:** Chat interface — ask questions about Wi-Fi Alliance content
- **Right side:** Content feed from AI agents (curated industry posts)
- Users can like posts and comment inline
- Silently logs in using existing Entra SSO — no second login prompt

### 2. @Aurora Bot ✅ Code complete, needs Azure Bot registration
A native Teams bot users can @mention in any channel or chat:
- Ask questions: *"@Aurora What is Wi-Fi 7?"*
- List agents: *"@Aurora agents"*
- Follow/unfollow agents: *"@Aurora follow TechWatcher"*
- Chat with a specific agent: *"@Aurora ask TechWatcher What's new in Wi-Fi 8?"*
- Show feed: *"@Aurora feed"*

### 3. Unified App Package ✅ Ready to build
A single `aurora-teams-app.zip` that IT uploads to Teams Admin Center — one install gives users both the tab and the bot.

---

## Current Status by Component

| Component | Status | Blocker |
|---|---|---|
| Teams Tab (chat + feed) | ✅ Deployable now | None |
| Teams SSO (silent login) | ✅ Code done | AZURE_TENANT_ID env var |
| Feed likes & comments | ✅ Code done | DB migration to run |
| @Aurora Bot (all commands) | ✅ Code done | Azure Bot Registration |
| Bot email lookup (Graph API) | ✅ Code done | IT admin consent |
| App package builder | ✅ Done | BOT_ID env var (after registration) |
| Teams Admin Center submission | ⏳ Pending | IT action |

---

## What We Need to Ask

### From IT / Azure AD Admin (< 1 hour total work)

**1. Confirm existing Azure App Registration settings** (10 min)
> App ID: `5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b`
> - In Azure Portal → App registrations → this app → "Expose an API"
> - Confirm Application ID URI is set to: `api://aurora-octo.xcloudiq.com/5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b`
> - If not, add it (this enables silent SSO inside Teams)
> - Also confirm `access_as_user` scope exists on this URI

**2. Provide the Azure Tenant ID** (2 min)
> Azure Portal → Azure Active Directory → Overview → copy "Tenant ID" (a GUID)
> We need this set in our production `.env` as `AZURE_TENANT_ID`

**3. Create an Azure Bot Registration** (20 min)
> - Azure Portal → Create resource → "Azure Bot"
> - Name: `aurora-teams-bot`, Type: Single tenant, Tier: F0 (free) 
> - Messaging endpoint: `https://aurora-octo.xcloudiq.com/bot/api/messages`
> - Enable "Microsoft Teams" channel
> - Share with us: **App ID** (→ `BOT_ID`) and **client secret** (→ `BOT_PASSWORD`)
> - Full instructions: `doc/TEAMS_IT_ADMIN_GUIDE.md`

**4. Grant admin consent for email lookup** (5 min, optional but recommended)
> On the bot's Azure App Registration → API permissions → Add:
> Microsoft Graph → Application → `User.Read.All` → Grant admin consent
> *(Without this, the bot still works but creates users by ID rather than email)*

**5. Submit app package to Teams Admin Center** (15 min)
> Once we provide the `aurora-teams-app.zip`, IT uploads it at:
> https://admin.teams.microsoft.com → Teams apps → Manage apps → Upload new app

---

## What We Can Do Right Now (Without IT)

### Test the Teams Tab immediately
The tab is live at:
```
https://aurora-octo.xcloudiq.com/teams
```
Open this in any browser while logged in — it works now. You can also sideload it into Teams for testing without IT approval:

1. Build the package: `./scripts/create-teams-package.sh aurora-octo.xcloudiq.com`
2. In Teams Desktop → Apps → Manage your apps → Upload a custom app
3. Select `aurora-teams-app.zip`
4. The tab installs in your personal Teams — you can test chat and feed

> **Note:** Sideloading may require your Teams tenant to allow custom app uploads.  
> Setting: Teams Admin Center → Teams apps → Setup policies → allow custom app uploads.

### Test the bot locally (developer only)
```bash
# Start Aurora services
docker compose up -d

# Start the bot (tab-only, no Azure registration needed for local emulator testing)
cd teams-agent && npm install && npm run dev

# Connect Bot Framework Emulator to http://localhost:3978/api/messages
```

---

## Steps to Full Production Deployment

Once IT provides BOT_ID and BOT_PASSWORD:

```bash
# 1. Add to production .env on EC2
AZURE_TENANT_ID=<tenant-guid>
AZURE_APP_CLIENT_ID=5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b
BOT_ID=<bot-app-id>
BOT_PASSWORD=<bot-client-secret>

# 2. Run database migration (adds post comments table)
# On EC2:
psql $DATABASE_URL < content_creator_service/migrations/007_add_post_comments.sql
# Or via make:
make migrate

# 3. Rebuild and deploy updated services
make build-push-all
cd prod-deployment && make update

# 4. Start the Teams bot service
docker compose --profile teams up -d teams-agent

# 5. Build and hand the app package to IT
BOT_ID=<bot-app-id> ./scripts/create-teams-package.sh aurora-octo.xcloudiq.com
# → aurora-teams-app.zip
```

IT then uploads `aurora-teams-app.zip` to Teams Admin Center and publishes it.

---

## Timeline Estimate

| Phase | Who | Estimated Time |
|---|---|---|
| IT Azure actions (items 1-4 above) | IT team | ~1 hour |
| We set env vars + deploy updated containers | Dev team | ~30 min |
| IT submits app to Teams Admin Center | IT team | ~15 min |
| Teams approval process | IT/Microsoft | 1–2 business days |
| **Teams available org-wide** | All users | — |

---

## What Users Will Experience

Once deployed, users go to any Teams channel, click **+** to add a tab, search for "Aurora", and add it. They also get access to @Aurora in any channel. First-time use silently logs them in using their existing Entra credentials — no separate sign-up or password.

---

## Is localhost:3000/teams Still Needed?

**No — not for users.** That's a developer-only URL for testing during local development.

Production users access the tab through Teams (which loads `aurora-octo.xcloudiq.com/teams`). Developers can use `localhost:3000/teams` to test UI changes before deploying.

---

## Key Documentation

| Document | Purpose | Audience |
|---|---|---|
| `doc/TEAMS_IT_ADMIN_GUIDE.md` | Step-by-step Azure + Teams Admin setup | IT team |
| `doc/IT/SECURITY_OVERVIEW.md` | Security architecture, auth flow, compliance | IT Security |
| `doc/IT/ARCHITECTURE_DIAGRAM.md` | System components and network layout | IT Infrastructure |
| `TEAMS_INTEGRATION_GUIDE.md` | Full technical integration reference | Dev team |
| `doc/DEPLOYMENT.md` | Production deployment procedures | Dev/Ops team |
