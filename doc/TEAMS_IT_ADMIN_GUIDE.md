# Aurora Teams Integration — IT Admin Guide

**Audience:** IT / Azure AD / Microsoft 365 administrators  
**Purpose:** Everything needed to deploy the Aurora Teams app (tab + bot) in your Microsoft 365 tenant.

---

## Overview

Aurora is deployed as a **single Microsoft Teams App** containing:
- A **Teams Tab** (React web app with chat + content feed)
- An **@Aurora Bot** (natural language Q&A + content agent commands)

Both surfaces share the same Azure App Registration. The tab uses Teams SSO (silent login via Azure AD). The bot uses the Bot Framework with a separate Bot Channel Registration.

---

## Prerequisites

- Global Admin or Teams Service Admin access
- Azure subscription (for Bot registration)
- Aurora application already deployed at a public HTTPS domain (e.g., `aurora-octo.xcloudiq.com`)

---

## Step 1: Verify the Existing Azure App Registration

Aurora's frontend already has an Azure App Registration (created during initial SSO setup):

- **App Client ID:** `5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b`  
  _(This ID is embedded in `frontend/public/manifest.json` → `webApplicationInfo.id`)_

**Verify / update these settings in the Azure Portal:**

1. Go to **Azure Portal** → **Azure Active Directory** → **App registrations**
2. Find the Aurora app (search by client ID above)
3. Check **Authentication** → **Redirect URIs**:
   - Should include: `https://aurora-octo.xcloudiq.com/api/auth/callback`
4. Check **Expose an API**:
   - Application ID URI should be: `api://aurora-octo.xcloudiq.com/5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b`
   - If missing, click **Add a scope** and set the Application ID URI as above
   - Add scope: `access_as_user`
   - Who can consent: **Admins and users**
5. Check **API permissions** (delegated):
   - `openid`, `email`, `profile` (Microsoft Graph) — all consented
6. Note the **Tenant ID** (shown in the Overview tab) — you'll need it for `.env`

**Update `.env` with the tenant info (for Teams SSO endpoint):**
```bash
AZURE_TENANT_ID=<your-tenant-guid>
AZURE_APP_CLIENT_ID=5f9b6a4d-2e1c-4c9f-a5b3-1d7e9c2f8a4b
```

---

## Step 2: Create an Azure Bot Registration (for @Aurora Bot)

> **Note:** Skip this step if you only want the Teams Tab (no bot messaging). The tab works independently.

1. Go to **Azure Portal** → **Create a resource** → search for **"Azure Bot"**
2. Click **Create**
3. Fill in:
   - **Bot handle:** `aurora-teams-bot` (or any unique name)
   - **Subscription / Resource Group:** as appropriate
   - **Pricing tier:** `F0` (free) for testing, `S1` for production
   - **Microsoft App type:** `Single tenant`
   - **Creation type:** `Create new Microsoft App ID`
4. Click **Review + Create** → **Create**
5. Once deployed, go to the bot resource → **Configuration**:
   - **Messaging endpoint:** `https://aurora-octo.xcloudiq.com/bot/api/messages`
   - Note the **Microsoft App ID** (this is your `BOT_ID`)
6. Go to **Configuration** → **Manage Password** → create a client secret
   - Note the secret value (this is your `BOT_PASSWORD`)
7. Go to **Channels** → click **Microsoft Teams** → **Save**

**Update `.env` with the bot credentials:**
```bash
BOT_ID=<microsoft-app-id-from-step-5>
BOT_PASSWORD=<client-secret-from-step-6>
```

---

## Step 3: Grant Microsoft Graph Permissions (for Email Lookup)

The bot resolves Teams user AAD Object IDs to email addresses via Graph API. This requires:

1. In the **Bot's Azure App Registration** (different from the Aurora app registration):
   - Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Application permissions**
   - Add: `User.Read.All`
2. Click **Grant admin consent** for your tenant
3. Optionally set these in `.env` for bot Graph API access:
   ```bash
   GRAPH_TENANT_ID=<your-tenant-guid>
   GRAPH_CLIENT_ID=<bot-app-id>
   GRAPH_CLIENT_SECRET=<bot-client-secret>
   ```

> **Note:** `User.Read.All` requires admin consent. Without it, the bot falls back to using the AAD Object ID as a synthetic identifier. Users will still work, but their Aurora profile won't be linked by email.

---

## Step 4: Create the Teams App Package

On the Aurora application server (or a developer machine with repo access):

```bash
# Basic tab-only package (no bot)
./scripts/create-teams-package.sh aurora-octo.xcloudiq.com

# Full package with bot
BOT_ID=<your-bot-app-id> ./scripts/create-teams-package.sh aurora-octo.xcloudiq.com

# Output: aurora-teams-app.zip in repo root
```

The script substitutes the domain and Bot ID into `manifest.json` and packages it with the app icons.

---

## Step 5: Submit to Teams Admin Center

1. Go to **https://admin.teams.microsoft.com**
2. Navigate to **Teams apps** → **Manage apps**
3. Click **Upload new app** (top right)
4. Click **Upload** → select `aurora-teams-app.zip`
5. Review the app details and click **Submit**
6. The app will appear in the list with status **Submitted**

**For admin-approved apps (recommended for org-wide rollout):**
- Click the app → **Publish** to make it available in the org app catalog
- Optionally use **App setup policies** to pre-install Aurora for specific teams or users

---

## Step 6: User Installation

Once published:
- Users can find Aurora in **Teams Apps** (search for "Aurora")
- To add to a **team channel:** Click **+** in the channel tab bar → search "Aurora" → Add
- To use the **bot:** In any channel or chat, type `@Aurora` to mention the bot

---

## Step 7: Start the Bot Service

On the Aurora host server:

```bash
# Start with the teams profile (brings up teams-agent container)
docker compose --profile teams up -d teams-agent

# Verify it's running
docker compose logs teams-agent
```

The bot will be accessible at `https://aurora-octo.xcloudiq.com/bot/api/messages` (via nginx).

---

## Configuration Reference

| Environment Variable | Description | Required For |
|---|---|---|
| `AZURE_TENANT_ID` | Azure AD tenant GUID | Teams SSO tab auth |
| `AZURE_APP_CLIENT_ID` | Azure App Registration client ID | Teams SSO tab auth |
| `BOT_ID` | Bot Framework App ID (from Azure Bot) | @Aurora bot |
| `BOT_PASSWORD` | Bot Framework client secret | @Aurora bot |
| `GRAPH_TENANT_ID` | Azure tenant for Graph API | Bot email lookup |
| `GRAPH_CLIENT_ID` | Bot app ID for Graph API | Bot email lookup |
| `GRAPH_CLIENT_SECRET` | Bot client secret for Graph API | Bot email lookup |

---

## Required Azure Permissions Summary

| Permission | Type | Used By | Admin Consent Required |
|---|---|---|---|
| `openid`, `email`, `profile` | Delegated | Teams SSO tab login | No |
| `access_as_user` | Delegated (custom) | Teams SSO token validation | No (user consent) |
| `User.Read.All` | Application | Bot → Graph API email lookup | **Yes** |
| Teams channel (Bot Framework) | Channel | Bot messaging in Teams | No |

---

## Troubleshooting

### Tab shows login button instead of auto-logging in
- Confirm `AZURE_TENANT_ID` and `AZURE_APP_CLIENT_ID` are set in Aurora's `.env`
- Verify the `webApplicationInfo` section in `manifest.json` has the correct `id` (must match Azure App Registration client ID)
- Verify the **Expose an API** scope (`access_as_user`) is configured on the Azure App Registration

### Bot doesn't respond in Teams
- Check `BOT_ID` and `BOT_PASSWORD` are correct in `.env`
- Verify the messaging endpoint in Azure Bot points to `https://aurora-octo.xcloudiq.com/bot/api/messages`
- Check teams-agent logs: `docker compose logs teams-agent`
- Verify the Microsoft Teams channel is enabled in Azure Bot → Channels

### Bot can't find user email
- This is expected without `GRAPH_CLIENT_SECRET` configured
- Configure Graph API credentials in `.env` and grant `User.Read.All` admin consent
- Without Graph API, bot creates users with synthetic identifiers (`<aad-oid>@teams.aad`)

### "App not found" in Teams
- The app package may not have been submitted/approved yet
- Check Teams Admin Center: **Teams apps** → **Manage apps** → filter by "Custom apps"
- App approval may take up to 24 hours after initial submission

---

## Architecture Reference

```
Teams User
  ├── Tab (Aurora web app)
  │     └── https://aurora-octo.xcloudiq.com/teams
  │           → Azure AD SSO token (via Teams SDK)
  │           → POST /api/auth/teams-sso (exchange for Aurora session)
  │           → All /api/* calls with teams_session cookie
  │
  └── @Aurora Bot
        └── Teams message → Bot Framework → Azure Bot Webhook
              → https://aurora-octo.xcloudiq.com/bot/api/messages
              → teams-agent Docker container (Node.js)
              → Aurora backend services
```

---

## Contacts

- **Aurora App Team:** bbonner (Extreme Networks)
- **Teams Admin Center:** https://admin.teams.microsoft.com
- **Azure Portal:** https://portal.azure.com
