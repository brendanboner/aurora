# IT Provisioning Request — Aurora Teams Integration

**From:** Office of the CTO, Rapid AI Innovation Team
**Owner:** Brendan Bonner (bbonner@extremenetworks.com)
**Date raised:** 2026-05-13
**Required by:** Wed 2026-05-20 (to support Fri 2026-05-22 pilot launch)
**Acceptable Monday-demo fallback:** dev-tenant ngrok demo — no corporate Teams change required for the demo itself.

---

## What we are asking for

Aurora is a knowledge management prototype from the Office of the CTO. The web application is already running inside Extreme's corporate VPC. We need IT to provision a Microsoft Teams surface for it so employees can query Aurora and receive AI-agent digests inside Teams rather than only via the browser.

We need:

1. **Azure Bot Service registration** in Extreme's tenant.
   - Output: `BOT_ID` (Microsoft App ID) and `BOT_PASSWORD` (client secret), to be set as environment variables on the Aurora production host.
   - Endpoint we will register: `https://aurora.<corp-internal-domain>/api/messages` (see item 4).

2. **AAD / Entra ID app registration** for Microsoft Graph access.
   - Required permission: `User.Read.All` (application permission, admin consent required).
   - Used by the Teams agent to resolve `aadObjectId → email` so Teams users map cleanly to their Aurora identity. Code path: `teams-agent/src/services/auroraUserService.ts:184-223`.
   - Output: `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`.

3. **Teams custom-app upload approval.**
   - Today: ability to sideload the manifest at `teams-agent/appPackage/manifest.json` for the pilot cohort (25 users).
   - End-of-week target: publish to the tenant app catalogue so any Extreme employee can install the Aurora app.
   - Manifest scopes requested: `personal`, `team`, `groupchat`. Permissions: `identity`, `messageTeamMembers`. Manifest version 1.16.

4. **DNS + reverse proxy** to expose the bot endpoint.
   - DNS record `aurora.<corp-internal-domain>` → existing Aurora EC2 instance.
   - nginx reverse proxy already deployed; needs a `/api/messages` location proxying to the `teams-agent` container on port 3978.
   - Public HTTPS required (Teams will refuse plain HTTP).

5. **Outbound network egress from the Aurora EC2** to:
   - `*.botframework.com` (port 443) — Teams Bot Framework relays.
   - `graph.microsoft.com` (port 443) — Graph API for user resolution.
   - `*.azure.com` (port 443) — Bot Service operations and token endpoints.

---

## Why now

The boss has asked for a Teams-integrated Aurora demo on Monday 2026-05-18 and a soft launch to a 25-person pilot cohort by Friday 2026-05-22. The pilot includes Product Managers, Solution Architects / Field CTOs, Innovators / Office-of-CTO programmes, and Standards/Firmware/Chip engineers across the Wireless organisation.

If corporate Teams isn't provisioned by Wed 2026-05-20, the Monday demo will still proceed (via a dev-tenant tunnel) but the Friday launch will slip — we cannot ask non-technical pilot users to interact with a bot in a dev tenant.

---

## Business case

Aurora is the first prototype from the Rapid AI Innovation Team. It pulls together standards-body activity from the Wi-Fi Alliance, IETF, and IEEE — including member-only WBA Extranet content that Extreme already pays to access — into a single chat surface with user-defined AI agents. The product question we are testing is whether agents that produce daily and weekly standards-body digests can replace the meeting-attendance and PDF-reading workload that today falls on a small number of senior engineers.

Teams integration is the highest-leverage delivery channel: it puts Aurora in front of every employee who already lives in Teams, without asking them to learn a new app.

---

## Security and compliance summary

Full detail in `SECURITY_NOTES.md` in this directory. Headline points:

- All Aurora data stays inside the corporate VPC. PostgreSQL, Neo4j, Redis — all on EC2.
- Outbound network is limited to the standards-body sites Extreme already has permission to access, plus (with this request) Microsoft Teams endpoints.
- Document bodies are discarded after parsing; only synopses and metadata are persisted (`retriever/scrapers/WBA_extranet.py`).
- WBA Extranet authentication uses a per-source `auth_token` stored in Neo4j and configurable only by admins.
- Every Aurora query is logged with user, datasource set, and route — auditable from PostgreSQL.
- Bot trust model: the Teams Bot Framework validates incoming HTTPS POSTs from Teams as authentic; Aurora's internal services then trust the `X-User-*` headers the bot injects after Graph API user resolution.

The bot is internal to Extreme. No PII flows externally. The only third-party SaaS in scope is Microsoft itself (Teams + Graph).

---

## What we provide

- **Manifest template** — `teams-agent/appPackage/manifest.json` with `{{APP_ID}}` and `{{BOT_ID}}` placeholders ready to substitute with the provisioned values.
- **App package icons** — `teams-agent/appPackage/color.png` (192×192) and `outline.png` (32×32) are pre-staged at the Teams-required sizes and formats.
- **Container** — `teams-agent/Dockerfile`, included in the production `docker-compose.yml` behind the `teams` profile.
- **Operational readiness** — bot supports a graceful fallback (`USE_MOCK_DATA=true`) for dry-runs; runs healthcheck on `GET /api/health`; PostgreSQL backs conversation references for proactive messaging (`teams-agent/src/services/conversationReferenceStore.ts`).
- **Network diagram (inline):**

```
   ┌───────────────────────────┐
   │  Microsoft Teams (cloud)  │
   └────────────┬──────────────┘
                │  HTTPS (Bot Framework)
                ▼
   ┌─────────────────────────────────┐
   │  aurora.<corp-domain>           │
   │  nginx reverse proxy            │
   │  /api/messages → teams-agent:3978│
   └────────────┬────────────────────┘
                │  internal Docker network
                ▼
   ┌─────────────────────────────────┐
   │  Aurora services (oracle,       │
   │  backend, neo4j, postgres,      │
   │  redis, retriever, ...)         │
   │  All in corp VPC, no public IPs │
   └─────────────────────────────────┘
                │
                │  outbound HTTPS (already permitted)
                ▼
   ┌───────────────────────────────────────────┐
   │  Standards body sites                     │
   │  (datatracker.ietf.org, wi-fi.org,        │
   │   extranet.wballiance.com, ieee.org, ...) │
   └───────────────────────────────────────────┘
```

---

## Deliverable handoff — how the Teams app package is built

The Teams app upload (item 3 above) requires a `.zip` containing `manifest.json` + `color.png` + `outline.png`. Two of those three are already staged. The third — `manifest.json` with the real `BOT_ID` and `APP_ID` substituted — can only be produced **after** IT returns the values from the Bot Service registration (item 1).

To minimise handoff time we will:

1. **Before IT returns anything** — keep the manifest template + PNGs in `teams-agent/appPackage/` ready to assemble.
2. **Within 10 minutes of receiving `BOT_ID` and `APP_ID`** — substitute the placeholders, build the zip, and return it to IT for upload:

   ```bash
   cd teams-agent/appPackage

   # Substitute the values IT provides into a working copy of the manifest.
   sed -e "s/{{APP_ID}}/$APP_ID/g" \
       -e "s/{{BOT_ID}}/$BOT_ID/g" \
       manifest.json > manifest.built.json

   # Bundle into the upload-ready archive.
   zip aurora-teams-app.zip manifest.built.json color.png outline.png
   ```

   The build script will be checked into the repo at `teams-agent/appPackage/build.sh` so the procedure is reproducible.

3. **IT (or the Aurora technical owner under sideload permission) uploads** `aurora-teams-app.zip`:
   - **For the pilot** (week of 2026-05-18): sideload to the 25 pilot users via Teams Admin Center → Manage apps → Upload custom app.
   - **For the launch** (Fri 2026-05-22): publish to the tenant app catalogue so any Extreme employee can install it from the in-Teams app search.

There is **no chicken-and-egg loop**: the Bot Service registration in item 1 does not require the manifest. IT can provision the Bot Service and return the credentials immediately; we then return the zip the same day.

### What IT does *not* need from us up-front

- The zip itself — can only be built after the Bot Service returns its identifiers.
- The bot endpoint URL — the DNS record in item 4 is owned by IT and only known once the reverse proxy is configured. We will register that URL with the Bot Service via the Azure portal once the DNS is live.

---

## Timeline ask

| Date | Milestone | Owner |
|---|---|---|
| Wed 2026-05-13 | This request forwarded to IT | OCTO / Rapid AI |
| Thu–Fri 2026-05-14/15 | Initial provisioning conversation; manifest details confirmed | IT |
| Mon 2026-05-18 | Demo runs against dev tenant if corporate not yet ready | OCTO / Rapid AI |
| Wed 2026-05-20 | `BOT_ID`, `BOT_PASSWORD`, Graph app credentials delivered; DNS + reverse proxy live | IT |
| Thu 2026-05-21 | Manifest sideloaded for 25 pilot users; smoke tests pass | OCTO / Rapid AI + IT |
| Fri 2026-05-22 | Launch message sent; pilot begins | OCTO / Rapid AI |

If any of these slip, the Friday launch slips with them. Please flag risks early.

---

## Points of contact

- **Aurora technical owner / this request:** Brendan Bonner — bbonner@extremenetworks.com
- **Office of the CTO sponsor:** [to be filled in by sender before forwarding]
- **Escalation path:** [to be filled in by sender before forwarding]
