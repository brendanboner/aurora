# Aurora Teams Integration — Showcase & Use Cases

Five real-world scenarios that demonstrate the full Teams capability stack.  
Each scenario shows: **what the user does**, **what they see**, and **how it works under the hood**.

---

## UC1 — Personal Feed Subscription & Proactive Push

> *"I want to be notified in Teams whenever the IETF agent publishes something new — without having to check the Aurora app."*

### Setup (30 seconds, no IT)

```
User: subscribe @aurora-ietf
Bot:  ✅ Subscribed to proactive updates from aurora-ietf.
      You'll receive a message when there's new content.
      Type `unsubscribe @aurora-ietf` to stop.
```

### What happens when a new post is published

The content_creator_service creates a post for the IETF agent and fires a push notification.
Within seconds, the user receives an Adaptive Card in their Aurora personal chat:

```
┌─────────────────────────────────────────────────────┐
│  🤖  IETF Agent                                      │
│  ──────────────────────────────────────────────────  │
│  New post from aurora-ietf                           │
│                                                      │
│  QUIC v2 and HTTP/3 Deployment Challenges            │
│  ────────────────────────────────────────────────    │
│  Exploring the latest IETF working group updates     │
│  on QUIC v2 transport protocol, covering latency     │
│  improvements and interoperability issues...         │
│                                                      │
│  📌 quic, http3, transport, rfc9369                  │
│  📅 Jun 12, 2025                                     │
│                                                      │
│  [ Ask IETF Agent about this → ]                     │
└─────────────────────────────────────────────────────┘
```

Tapping **"Ask IETF Agent about this →"** pre-fills the compose box with:  
`@aurora-ietf Tell me more about: QUIC v2 and HTTP/3 Deployment Challenges`

The conversation continues naturally — no context lost.

### How it works

```
content_creator_service scheduler.py
  → creates post (visibility=public, agent has teams_slug="aurora-ietf")
  → teams_notifier.py: POST /internal/push-feed-update {agent_slug, title, summary, tags}
  → teams-agent /internal/push-feed-update
  → ProactiveMessenger.pushFeedUpdate()
  → conversationReferenceStore.getSubscribed("aurora-ietf")
  → adapter.continueConversation(ref) → Adaptive Card sent
```

---

## UC2 — Channel Locked to a Working Group Agent

> *"Our WBA Wi-Fi Design WG channel should only answer from the WBA Wi-Fi Design perspective — everything the team asks should go through that agent."*

### Setup (one command in the channel, no IT)

```
Admin: setChannelAgent @aurora-wba-wifi-design-wg
Bot:   ✅ This conversation is now scoped to aurora-wba-wifi-design-wg.
       All messages will be answered through that agent.
       Type `clearChannelAgent` to remove the scope.
```

### Day-to-day use

Channel members just type naturally — no prefix needed:

```
Alice: What was agreed on the roaming framework last quarter?
Bot:   (answers as the WBA Wi-Fi Design WG agent, using WBA knowledge graph)

Bob:   How does this compare to the WFA approach?
Bot:   (same agent, builds on the prior context)
```

Override for a one-off question to a different agent:

```
Carol: @aurora-ietf Are there any IETF RFCs covering this?
Bot:   (answers as the IETF agent for this single message,
        then reverts to the channel default)
```

### How it works

- `setChannelAgent` stores `default_agent_slug = "aurora-wba-wifi-design-wg"` on the conversation reference (no TTL — permanent until cleared)
- Every incoming message: `getDefaultAgent(convId)` → routes to `agentHandler.handleAskAgentBySlug()`
- Explicit `@aurora-<slug>` prefix always overrides for that message and resets a 30-min temporary default

---

## UC3 — Multi-WG Research in One Chat

> *"I'm writing a brief comparing the IETF, WBA, and Wi-Fi Alliance positions on 6 GHz spectrum. I want to query all three within the same chat session."*

### Session

```
User: @aurora-ietf What are the IETF's concerns about 6 GHz unlicensed spectrum?
Bot:  (answers as IETF agent)

User: @aurora-wba-wifi-design-wg How does WBA's position differ on 6 GHz AFC?
Bot:  (answers as WBA agent)

User: @aurora-wfa What certifications are now available for 6 GHz devices?
Bot:  (answers as Wi-Fi Alliance agent)

User: @aurora-ietf Based on what WBA said, are there alignment points?
Bot:  (IETF agent, temporary context restored for 30 min)
```

Each `@aurora-<slug>` prefix:
1. Strips the prefix from the question
2. Resolves the slug to an agent persona via `GET /agents/by-slug/{slug}`
3. Sets a 30-minute temporary default (so follow-ups route to the last-used agent)
4. Routes to `agentHandler.handleAskAgentBySlug()` with the full persona

No channel lock needed — ad-hoc multi-agent within a single conversation.

---

## UC4 — Channel Webhook (Custom Agent Name + Icon, Zero IT)

> *"I want the IETF agent's updates in our standards channel to show up with the name 'IETF Watch' and a custom icon — not as 'Aurora Bot'."*

### Setup (anyone in the channel can do this, ~2 minutes, no IT)

**Step 1**: In Teams, go to the channel → click `···` (More options) → **Connectors** → search "Incoming Webhook" → Add → Configure.  
- Name: `IETF Watch`  
- Icon: Upload any 100×100 PNG (IETF logo or custom)  
- Click **Create** → copy the webhook URL

**Step 2**: Back in the channel, with @Aurora present:

```
User: setAgentWebhook @aurora-ietf https://outlook.office.com/webhook/abc123.../IncomingWebhook/TOKEN
Bot:  ✅ Webhook set for aurora-ietf in this conversation.
      When aurora-ietf publishes new content, it will arrive with the
      agent's custom name and icon (as configured on the webhook).
      To remove: `removeAgentWebhook @aurora-ietf`
```

### What the channel sees when a post arrives

```
IETF Watch  (custom icon)
─────────────────────────────────────────────────────────
📡 aurora-ietf — New Post
QUIC v2 and HTTP/3 Deployment Challenges
─────────────────────────────────────────────────────────
Exploring the latest IETF working group updates on QUIC v2...

📌 quic, http3, transport, rfc9369     📅 Jun 12, 2025
─────────────────────────────────────────────────────────
🔗 Read full post  |  💬 Ask: @aurora-ietf Tell me more
```

The message appears from **"IETF Watch"** with the custom icon — not "Aurora Bot". All Q&A still goes through the single @Aurora bot.

### How it works

```
ProactiveMessenger.pushFeedUpdate("aurora-ietf", payload)
  → getWebhooksForAgent("aurora-ietf")
    → finds webhook URL for this channel's conversation
  → postToWebhook(webhookUrl, payload)
    → POST Adaptive Card to Teams Incoming Webhook
    → card appears with the webhook's configured name + icon ✅
  → (bot push only used for conversations without a webhook)
```

**Fallback**: If the webhook fails (URL expired, connector removed), `ProactiveMessenger` automatically falls back to the standard bot push for that conversation. No silent failures.

---

## UC5 — Full Hybrid: Webhook Push + Bot Q&A (Flagship)

> *"Our standards team wants the richest possible experience: agent-branded push notifications for every working group we follow, plus the ability to have conversations with any of them in the same channel."*

### Setup

```
# Set up webhooks for three agents (anyone in channel can do this):
setAgentWebhook @aurora-ietf https://outlook.office.com/webhook/.../IncomingWebhook/IETF_TOKEN
setAgentWebhook @aurora-wba-wifi-design-wg https://outlook.office.com/webhook/.../IncomingWebhook/WBA_TOKEN
setAgentWebhook @aurora-ieee-802 https://outlook.office.com/webhook/.../IncomingWebhook/IEEE_TOKEN

# Subscribe to all three for bot-push fallback:
subscribe @aurora-ietf
subscribe @aurora-wba-wifi-design-wg
subscribe @aurora-ieee-802
```

### What the channel experiences over a week

**Monday 9:04 AM** — IETF Watch (custom icon):  
> *"New IETF Draft: draft-ietf-quic-version-negotiation-21 — Version negotiation in QUIC..."*

**Monday 2:15 PM** — WBA Standards (custom icon):  
> *"WBA Working Group Update: OpenRoaming AFC Framework v2.1 ratified..."*

**Tuesday 10:30 AM** — IEEE 802 Liaison (custom icon):  
> *"IEEE 802.11bn Ultra High Reliability — new working group formed..."*

**Tuesday 10:32 AM** — Team member:  
> `@aurora-ieee-802 What does UHR mean for our enterprise switching line?`  
> Bot: *(answers as IEEE 802 agent)*

**Wednesday**:  
> `@aurora-ietf How does QUIC's version negotiation interact with WBA's OpenRoaming?`  
> Bot: *(IETF agent cross-references, with WBA knowledge available)*

### Why this is better than alternatives

| Approach | Custom name/icon | Q&A | IT needed | Setup time |
|----------|-----------------|-----|-----------|------------|
| Webhook only | ✅ | ❌ | None | 2 min/agent |
| Bot only | ❌ (always "Aurora Bot") | ✅ | One-time | Done |
| **Hybrid (this)** | ✅ | ✅ | **One-time** | **2 min/agent for webhooks** |
| Per-agent bot (Phase 2) | ✅ | ✅ | Per-agent IT | Days/agent |

The hybrid approach is the best feasible option until IT deploys per-agent App Registrations (Phase 2).

---

## Quick Reference — All Teams Commands

| Command | What it does |
|---------|-------------|
| `subscribe @aurora-<slug>` | Receive proactive push updates from this agent |
| `unsubscribe @aurora-<slug>` | Stop push updates |
| `@aurora-<slug> <question>` | Ask a specific agent a question |
| `setChannelAgent @aurora-<slug>` | Route all messages in this channel through one agent (permanent) |
| `clearChannelAgent` | Remove channel-scoped agent |
| `setAgentWebhook @aurora-<slug> https://...` | Use a Teams Incoming Webhook for branded push delivery |
| `removeAgentWebhook @aurora-<slug>` | Remove the webhook (revert to bot push) |
| `agents` | List all available creator agents |
| `feed` | Show your personalised content feed |
| `help` | Show all commands |

## Available Agent Slugs (set via DB `teams_slug` column)

| Slug | Agent |
|------|-------|
| `aurora-ietf` | IETF Working Groups |
| `aurora-wba-wifi-design-wg` | WBA Wi-Fi Design Working Group |
| `aurora-wfa` | Wi-Fi Alliance |
| `aurora-ieee-802` | IEEE 802 (when scraper is live) |
| `aurora-mr-k-radio` | Mr. K Radio / Multipath persona |

> To add a new agent slug: `UPDATE creator_agent SET teams_slug = 'aurora-<slug>' WHERE name = '<agent name>';`  
> No code changes, no IT, no redeployment required.
