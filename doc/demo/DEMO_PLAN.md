# Aurora — 30-Minute Demo Walkthrough

**Date:** Monday 2026-05-18
**Presenter:** Brendan Bonner — Office of the CTO, Rapid AI Innovation Team
**Audience:** Senior leadership; expected mix of product managers, solution architects / field CTOs, innovators, and standards/firmware/chip engineers.
**Format:** 30 min walkthrough + Q&A. Live on the production system; two browser tabs (Aurora web + Teams). Teams runs through an ngrok tunnel to the dev tenant while corporate provisioning is in flight — call this out openly when you switch to Teams.

---

## Pre-demo checklist (T-15 min)

Run through this with `SETUP_COMMANDS.md` open in a third window.

- Production EC2 healthy: `make connect_aurora_ec2` → `docker compose ps` shows all green.
- Neo4j data freshness check: monitoring page open in a hidden tab, no batches stalled.
- Smoke query run cold and warm: `What is the difference between Wi-Fi 7 and Wi-Fi 8?` returns substantive answer in <8 s.
- Teams ngrok tunnel live. Bot Framework dev tenant endpoint set to the ngrok URL. Send `help` to the bot to confirm.
- Browser windowed, zoomed to presentation level, dark mode on, two tabs: Aurora web (left), Teams web (right).
- Preferences tab pre-loaded but **not** pre-populated — you'll be joining workgroups live so the audience sees the UI.
- Demo user is a fresh account: no agent history, no joined groups beyond a couple of public IETF WGs that are too noisy to omit.

---

## Persona tuning

Skim the audience first. Adjust emphasis without changing the spine:

- **Mostly Product Managers** → linger on Act 4 (custom agents); compress Act 3.
- **Mostly Solution Architects / Field CTOs** → linger on Act 3 (cross-source synthesis); show the document source list explicitly.
- **Mostly Innovators / OCTO** → linger on Act 5 (Teams + agent subscriptions); play up the "this is a prototype, here's what's next" framing.
- **Mostly Standards/Firmware/Chip engineers** → linger on Act 2 (member-only content); pull up a specific document card and read the synopsis.

If the room is mixed (most likely), keep the timings below and lean Q&A toward whichever segment is asking the loudest questions.

---

## The walkthrough

### 0:00 — 2:30 · Cold open: the problem

> "How many of you have read every WBA NextGen Wi-Fi meeting note from the last month? Right. How many of you have read every IETF SPRING draft and IEEE 802.11bn agenda since February?"
>
> "Every product team at Extreme is trying to track standards bodies that move faster than any one person can read. We pay membership fees to access the proceedings. We send people to meetings. But the knowledge stays locked in PDFs and minutes that almost nobody opens."
>
> "Aurora reads them for you. It pulls the public standards record from IETF and IEEE, the member-only working group activity from the WBA Extranet, and folds them into one place you can ask questions of in plain English — in your browser or directly inside Teams."

Switch to the Aurora web tab.

---

### 2:30 — 7:00 · Act 1: Login & setup

**Goal:** show that getting into Aurora is a single SSO click and that personalisation takes thirty seconds.

1. Click "Log in" → Cognito Hosted UI → corporate creds → land on Aurora home. No friction, no signup form, automatic user record created on first login (`auth/auth.py:_sync_user_on_login`).
2. Open **Preferences** in the sidebar. Four tabs visible: Groups · Sources · Technology · Companies.
3. On the **Groups** tab, expand "Wi-Fi Alliance" → "NextGen Wi-Fi", click **Join** on `wba_extranet_nextgen_wifi`. Note the yellow "member-only" badge.
4. Expand "IETF" → tick **Join** on `ietf_wg_spring` (or whichever WG is most relevant to the audience).
5. Switch to the **Technology** tab. Search "Wi-Fi 8" → mark **Prefer**. Search "PQC" → mark **Prefer**.
6. Sidebar shows "5 groups joined, 2 topics preferred". That's the setup done.

> "Sixty seconds. That's all there is to it. Aurora now knows what to dig into and what to leave aside."

**Talking point to land:** member-only badge implies Aurora respects access control — you don't see what you haven't joined.

---

### 7:00 — 14:00 · Act 2: Member-only standards access

**Goal:** show the killer differentiation — content nobody can Google.

Type into chat:

```
@wba what's new in NextGen Wi-Fi this month
```

Wait. While the answer renders, narrate:

> "The `@wba` mention scopes the query to Wireless Broadband Alliance sources. Aurora expands `@wba` to every WBA workgroup I have access to. It's filtering against member-only meeting digests we logged in to fetch."

When the answer lands:

- Read the first paragraph aloud. Point out one named person and one named workgroup that appear in the synthesis.
- Click into a source card. The synopsis is visible; the body is not — Aurora discards the body on ingest by design.
- Point at the "Brendan Bonner" name in one of the digest summaries if it appears: "That's me. From an actual call I sat in on three weeks ago. Aurora caught it."

Second query:

```
What are the priorities of the IoT programme this quarter?
```

> "Cross-workgroup synthesis. The IoT programme has six sub-groups. Aurora rolls them up."

Open a new tab to **Monitoring** (admin link) — show the active batch list, the recent activity panel, the WBA Extranet scrape that ran this morning. Close the tab.

> "That's a live look at what's being ingested. It runs on a schedule and after every workgroup meeting publishes notes."

**If `@wba` query stalls or returns thin content, fall back to:** `@wba_extranet_iot_p5g latest activity` — a narrower scope that consistently has fresh content.

---

### 14:00 — 19:00 · Act 3: Cross-source synthesis

**Goal:** show that Aurora joins public and member-only sources into one answer.

Query:

```
What is the difference between Wi-Fi 7 and Wi-Fi 8?
```

While the answer renders:

> "This is a question whose answer lives in seven places: IEEE 802.11bn drafts, Wi-Fi Alliance certification proposals, WBA Extranet workgroup discussions, and the public press. No single document has the answer. Aurora composes one."

When the answer lands:

- Point at the source list at the bottom. Count the source bodies: IEEE, WFA, WBA, IETF.
- Read the closing paragraph aloud — pick out a contrast that wouldn't be obvious to a casual reader (e.g. MLO vs. nominal-AP behaviour).

Follow-up query, exercising conversational memory:

```
Which of those benefits matters most for enterprise deployments?
```

> "Aurora is keeping context across turns. We're not restating the comparison; we're asking it to pivot."

**If the cross-source query returns shallow content, fall back to:** `What has Qualcomm contributed to Wi-Fi 8 discussions?` — narrower, but still cross-source and reliably hits both WFA and IEEE.

---

### 19:00 — 24:00 · Act 4: Create your own agent

**Goal:** show that this isn't just chat — users can deploy passive, scheduled assistants.

1. Navigate to **My Agents** (sidebar). Click **Create agent**.
2. Fill in live:
   - **Name:** `Wi-Fi 8 Daily Brief`
   - **Persona:** `Senior wireless architect. Dry, technical tone. Focus on chip-side implications and where the spec is still soft.`
   - **Topics:** `802.11be, 802.11bn, latency optimization, secure control frames`
   - **Organisations:** `IEEE, WBA, WFA`
   - **Cadence:** `daily-digest`
   - **Importance threshold:** `0.6`
3. Click **Create**. Click **Trigger now** on the new agent.
4. Wait ~30 seconds. Refresh the **Feed** pane. The agent's first post appears — title, body, sources.

> "Daily digests in your voice, on your topics, against the same knowledge base. You can build one per project. Architects on the room can build agents for their customer briefings. PMs can build agents that watch a single workgroup."

**If the agent run takes too long or produces a thin post, fall back to:** show an existing agent's recent post from the feed and explain the same flow.

---

### 24:00 — 28:00 · Act 5: Teams

**Goal:** show that the same agents and queries work where everyone is already typing.

Switch to the Teams tab. Acknowledge openly:

> "Quick note — corporate Teams provisioning is in progress with IT this week. What you're about to see is the production Aurora backend talking through a tunnel to a dev Teams tenant. Once IT lands, this same conversation happens inside our corporate Teams next week."

Send to the bot, in order:

1. `feed` → the bot returns the user's personal feed cards including the agent post you just created.
2. `@wba what happened in the IoT call last week` → same Oracle as the web; same answer shape; threaded inline.
3. `subscribe @aurora-wifi-8-daily-brief` → bot confirms; tomorrow's run lands in this chat.

> "Everything you saw in the web UI is available here. For people whose home is Teams — most of you — Aurora goes to where you already work."

**If the Teams tunnel drops mid-demo:** switch back to the web feed, show the same agent post there. Apologise once; don't dwell.

---

### 28:00 — 30:00 · Closing

> "Aurora is a prototype from the Office of the CTO, Rapid AI Innovation Team. The architecture is built. The data is flowing. The pieces that need finishing are: the corporate Teams app deployment that IT is provisioning this week; a guided first-run setup in place of the manual one you just watched; and the proactive Teams push from agents that's plumbed but not yet wired."
>
> "We are inviting 25 people across Extreme to a one-week pilot starting Wednesday. The launch message and the survey are ready to send. The KPIs we'll be tracking are on the next slide / in the engagement plan I'll share."
>
> "What I'm asking from this room: nominate people for the pilot, point us at the working groups your teams care about most, and tell us where this lands on your roadmap."

End on the survey URL slide (once Microsoft Forms is up).

---

## Q&A — prepared answers

**Q: How is this different from M365 Copilot or ChatGPT?**
A: Copilot doesn't know your standards body proceedings. ChatGPT doesn't have access to WBA Extranet or the most recent IETF drafts. Aurora is a domain-specific knowledge graph built on top of those sources, with answers that cite which document and which meeting. The chat is just the surface.

**Q: Where does the data live? Is anything leaving Extreme?**
A: Everything is in our corporate VPC — Postgres, Neo4j, Redis, all on EC2. The only outbound calls are to the standards-body sites we already have permission to read, and (once IT provisions it) to Microsoft Teams. No PII leaves Extreme. See `SECURITY_NOTES.md`.

**Q: What about WBA's licensing on member-only content?**
A: We're a member; our use is within the membership terms. Aurora discards the body of every document after parsing and stores only the synopsis — we are not republishing WBA content, we are summarising it for our own employees who have a right to access it. We can produce the body-discard logic if asked; it's in `retriever/scrapers/WBA_extranet.py`.

**Q: How does an agent decide what's "important"?**
A: Each agent has an importance threshold (0–1) that filters which events trigger a post. Today it's a heuristic based on event recency, source weight, and topic match. The roadmap is to learn from user thumbs-up / thumbs-down feedback per agent.

**Q: What happens when a workgroup chair asks us to stop scraping?**
A: We have a hard kill switch per DataSource in the admin UI. Disabling a source removes it from query results immediately and stops further ingest. We also won't enable a scraper for a body we don't have authenticated access to.

**Q: What does this cost?**
A: Today it runs on a single EC2 box and a managed RDS / Neo4j Aura instance. The LLM call cost is the variable — back-of-envelope, $40–80 per user per month at typical query volumes, dominated by GPT-4-class baseline-pipeline queries. The fast-pipeline path (~70% of queries today) is mostly free.

**Q: Can a team get their own instance?**
A: Not yet. Aurora is single-tenant by design today and we'd rather grow the central instance than fragment it. Future work could split per-business-unit if there's a strong reason.

**Q: How do I get my workgroup added?**
A: Two paths. If it's a publicly accessible body, we add a scraper — engineering effort, days not weeks. If it's member-only, we need credentials and a manifest of which workgroups you want covered. WBA already works; we'd extend the same pattern to e.g. CableLabs, 3GPP partner portals, etc.

**Q: Who is using it today?**
A: A small internal group across the Wireless and Office-of-the-CTO teams. The pilot in this engagement plan is the first structured rollout.

---

## Verbatim queries — copy-paste ready

From `cli/demo_questions.txt` and `scripts/wba_questions.txt`:

```
@wba what's new in NextGen Wi-Fi this month
What are the priorities of the IoT programme this quarter?
What is the difference between Wi-Fi 7 and Wi-Fi 8?
Which of those benefits matters most for enterprise deployments?
What has Qualcomm contributed to Wi-Fi 8 discussions?
@ietf show me recent drafts on 6 GHz spectrum
Who presented at the Wi-Fi 8 February 2026 face-to-face?
What is the current status of the IEEE 802.11bc standard?
```

Fallback set if a primary query underwhelms:

```
@wba_extranet_iot_p5g latest activity
Summarise the latest Wi-Fi Alliance Causeway workgroup activity
What was discussed in the last month across all working groups?
Find all documents related to 802.11be beamforming
```

---

## Owner

Brendan Bonner — Office of the CTO, Rapid AI Innovation Team.
