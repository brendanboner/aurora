# Aurora Teams — Agent Personas & Proactive Messaging

**Audience:** IT / Azure AD administrators and Aurora development team  
**Purpose:** How Aurora's creator agents appear as named Teams identities and push proactive updates.

---

## Overview

Aurora supports two tiers of agent identity in Teams:

| Tier | What users see | IT required | Status |
|------|---------------|-------------|--------|
| **Phase 1 — Slug routing** | Single `@Aurora` bot; agent identity shown in message text; `@aurora-ietf your question` routes to IETF agent | None | ✅ Built |
| **Phase 2 — Per-agent bots** | Separate `@aurora-ietf` identity in Teams with own avatar, name, @mention | Azure AD App Registration per agent | Documented below |

Phase 1 is fully functional. Phase 2 upgrades the UX to give each agent a distinct Teams presence.

---

## Phase 1: What Works Today (No IT Required)

### Proactive feed updates

When a creator agent publishes new content, it is automatically pushed as a Teams message to subscribed conversations. No user action required after initial subscription.

**How users subscribe:**

```
subscribe @aurora-ietf          # receive pushes from the IETF agent
subscribe @aurora-wba-wifi-design-wg
unsubscribe @aurora-ietf        # stop pushes
```

**What they receive:**
- An Adaptive Card with: agent name, post title, summary, tags, and a "Ask [Agent] about this →" button
- Tapping the button opens a conversation with that agent pre-filled

### Conversation-scoped agents

Users can lock a Teams channel to a specific agent. All messages in that channel are answered in that agent's voice/expertise:

```
setChannelAgent @aurora-wba-wifi-design-wg   # lock this channel to the WBA Wi-Fi Design agent
clearChannelAgent                             # remove the lock
```

### Direct agent queries

```
@aurora-ietf What's happening with QUIC transport?
@aurora-wba-wifi-design-wg Latest 6 GHz spectrum updates?
@aurora-mister-multipath Compare MPTCP and QUIC multipath
```

---

## Phase 2: Per-Agent Bot Identities (IT Required)

To give each agent a distinct `@mention` identity (own name, avatar, description in Teams), you need one Azure Bot App Registration per agent.

### What IT needs to create (once per agent)

#### Step 1 — Azure AD App Registration

1. Open [Azure Portal → App Registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Name: `Aurora — <Agent Display Name>` (e.g. `Aurora — IETF Agent`)
4. Supported account types: **Accounts in this organizational directory only (Single tenant)**
5. Redirect URI: leave blank
6. Click **Register**
7. Note the **Application (client) ID** — this is the `app-id`
8. Go to **Certificates & secrets** → **New client secret** → note the secret value

Repeat for each agent.

#### Step 2 — Azure Bot Service Registration

1. Open [Azure Portal → Azure Bot](https://portal.azure.com/#create/Microsoft.BotServiceConnectivityGallery)
2. Bot handle: `aurora-<slug>` (e.g. `aurora-ietf`)
3. Subscription / Resource Group: your Aurora resource group
4. Microsoft App ID: select **Use existing app registration** → paste the `app-id` from Step 1
5. Messaging endpoint: `https://<aurora-domain>/api/messages/<slug>` (e.g. `https://aurora-octo.xcloudiq.com/api/messages/aurora-ietf`)
6. Click **Create**
7. Go to **Channels** → **Microsoft Teams** → Enable and save

#### Step 3 — Teams App Package

Run this from the Aurora repository root:

```bash
./scripts/create-agent-manifest.sh aurora-ietf <app-id> <bot-id>
# Output: dist/teams-packages/aurora-ietf.zip
```

Deploy the package:
- **Testing**: Teams → Apps → Upload a custom app → select the .zip
- **Org-wide**: Teams Admin Center → Manage apps → Upload an app

#### Step 4 — Provide credentials to Aurora team

The Aurora team needs to add these to the `.env` file:

```
AGENT_BOT_AURORA_IETF_APP_ID=<app-id>
AGENT_BOT_AURORA_IETF_APP_SECRET=<client-secret>
```

The naming convention is `AGENT_BOT_<SLUG_UPPERCASE_UNDERSCORED>_APP_ID` and `_APP_SECRET`.

---

## Recommended Agents for Phase 2 (Priority Order)

| Slug | Display Name | Domain | Justification |
|------|-------------|--------|---------------|
| `aurora-ietf` | IETF Agent | Internet standards, QUIC, HTTP/3 | Highest query volume; users ask IETF questions frequently |
| `aurora-wba-wifi-design-wg` | WBA Wi-Fi Design WG | Wi-Fi design, 6 GHz, hotspot 2.0 | Key working group for enterprise Wi-Fi |
| `aurora-ieee-802` | IEEE 802 Agent | 802.11be, 802.1Q, Ethernet standards | Foundation of all Wi-Fi and Ethernet specs |
| `aurora-mister-multipath` | Mister Multipath | MPTCP, QUIC, multipath networking | Distinctive persona; conversation starter |

---

## Teams Use Case Summary

| Use case | Teams feature | IT action |
|----------|--------------|-----------|
| Personal chat with Aurora | Bot, personal scope | Install Aurora app |
| Q&A in a team channel | Bot, team scope | Add Aurora bot to the channel |
| Proactive feed updates (personal) | Proactive messaging | None — Aurora side only |
| Scope a channel to one WG agent | Bot command (`setChannelAgent`) | None — Aurora side only |
| `@aurora-ietf` as distinct identity | Per-agent bot + app package | One App Registration per agent |
| Agent-specific icons/avatars in mentions | Per-agent app package | IT deploys each package |
| Org-wide deployment (no sideloading) | Teams Admin Center app policy | Teams Admin + optionally Global Admin |

---

## Security Notes

- The internal `/internal/push-feed-update` endpoint on the Teams agent is **not** exposed via the auth gateway — it is only reachable from within the Docker network (content_creator_service → teams-agent).
- Bot Framework credentials (App ID + Secret) are stored as environment variables, never in the codebase.
- Each per-agent bot is scoped to a single tenant and can only be added to conversations in that tenant.

---

## Troubleshooting

**Bot added to channel but no welcome message**
- Check that the bot's messaging endpoint is reachable from Microsoft's servers (must be public HTTPS)
- Verify `BOT_ID` and `BOT_PASSWORD` in the Aurora `.env` match the App Registration

**Proactive push not arriving**
- Check `TEAMS_AGENT_URL` is set in content_creator_service environment
- Check `teams-agent` logs: `docker compose logs -f teams-agent`
- Verify the user has typed `subscribe @aurora-<slug>` in the conversation

**Slug not resolving (`@aurora-ietf` shows error)**
- Ensure the creator agent has `teams_slug = 'aurora-ietf'` set in the database
- Run: `psql -U aurora -c "SELECT name, teams_slug FROM creator_agent WHERE teams_slug IS NOT NULL;"`
