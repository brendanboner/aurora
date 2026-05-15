# Aurora — 30-Minute Demo Walkthrough

**Date:** Monday 2026-05-18  
**Presenter:** Brendan Bonner — Office of the CTO, Rapid AI Innovation Team  
**Audience:** Senior leadership; product managers, solution architects / field CTOs, innovators, standards/firmware/chip engineers.  
**Format:** 30 min walkthrough + Q&A. Live on the production system.  
**Teams status:** ⚠️ Corporate provisioning in progress — Teams is shown as a slides-only preview, not live. State this upfront and move on; it is not the main story.

---

## Pre-demo checklist (T-15 min)

Run `./doc/demo/demo_runner.sh --setup` for automated checks. Or manually:

- Production EC2 healthy: `make connect_aurora_ec2` → `docker compose ps` shows all green.
- Neo4j data freshness: monitoring page open in a hidden tab, no stalled batches.
- Smoke query warm and fast: `What is the difference between Wi-Fi 7 and Wi-Fi 8?` returns in <8 s.
- Browser: dark mode, one tab (Aurora web), zoomed to 125%, Preferences sidebar open but empty.
- Monitoring tab: open in hidden tab, confirm no stalled batches.
- Phone: Do Not Disturb. Slack: closed. Email: closed.

---

## Persona tuning

Skim the audience first. Adjust emphasis without changing the spine:

- **Mostly Product Managers** → linger on Act 4 (custom agents), compress Act 3.
- **Mostly Solution Architects / Field CTOs** → linger on Act 3 (cross-source synthesis), show source list explicitly.
- **Mostly Standards/Firmware/Chip engineers** → linger on Act 2 (member-only content), pull up a document card.
- **Mostly Innovators / OCTO** → linger on Act 4/5 (agents + roadmap), play up "this is a prototype".

---

## The walkthrough

### 0:00 — 2:30 · Cold open: the problem

> "How many of you have read every WBA NextGen Wi-Fi meeting note from the last month? Right. How many have read every IETF draft and IEEE 802.11 agenda since February?"
>
> "Every product team at Extreme is trying to track standards bodies that move faster than any one person can read. We pay membership fees to access the proceedings. We send people to meetings. But the knowledge stays locked in PDFs and minutes that almost nobody opens."
>
> "Aurora reads them for you. It pulls the public standards record from IETF and IEEE, the member-only working-group activity from the WBA Extranet, and folds them into one place you can ask questions of — in plain English, in your browser."

Switch to the Aurora web tab.

---

### 2:30 — 7:00 · Act 1: Login & personalisation

**Goal:** show that getting started is one SSO click and thirty seconds of setup.

1. Click **Log in** → Cognito SSO → land on Aurora home. Narrate: _"No signup form. Automatic account created on first login."_
2. Open **Preferences** → **Groups** tab.
3. Expand "Wi-Fi Alliance" → "NextGen Wi-Fi" → click **Join** on `wba_extranet_nextgen_wifi`. Note the yellow member-only badge.
4. Expand "IETF" → **Join** on `ietf_wg_spring`.
5. Switch to **Technology** tab → search "Wi-Fi 8" → **Prefer**. Search "PQC" → **Prefer**.
6. Sidebar shows "5 groups joined, 2 topics preferred".

> "Sixty seconds. Aurora now knows what to dig into and what to leave aside. And it respects access control — you only see what you've joined."

---

### 7:00 — 14:00 · Act 2: Member-only standards access

**Goal:** show the killer differentiator — content nobody can Google.

Type into chat:

```
@wba what's new in NextGen Wi-Fi this month
```

While the answer renders:

> "The `@wba` mention scopes this to Wireless Broadband Alliance sources. Aurora expands it to every WBA workgroup I have access to — filtering against member-only meeting digests that require a login to reach."

When the answer lands:
- Read the first paragraph aloud. Name one person and one workgroup that appear.
- Click a source card — synopsis visible, body is not (Aurora discards it on ingest by design).

Second query:

```
What are the priorities of the IoT programme this quarter?
```

> "Cross-workgroup synthesis. The IoT programme has six sub-groups. Aurora rolls them up."

Open **Admin → Monitoring** in a hidden tab. Show the active scrape list and recent activity panel briefly.

> "That's a live view of what's being ingested. It runs on a schedule and after every workgroup meeting publishes notes."

Close the monitoring tab.

**Fallback if @wba returns thin content:** `@wba_extranet_iot_p5g latest activity`

---

### 14:00 — 19:00 · Act 3: Cross-source synthesis

**Goal:** show that Aurora joins public and member-only sources into one answer.

```
What is the difference between Wi-Fi 7 and Wi-Fi 8?
```

While rendering:

> "This answer lives in seven places: IEEE 802.11bn drafts, Wi-Fi Alliance certification proposals, WBA Extranet working-group discussions, and the public press. No single document has it. Aurora composes one."

When landed:
- Point at the source list. Call out the mix: IEEE, WFA, WBA, IETF.
- Read the closing contrast aloud — e.g. MLO vs. nominal-AP behaviour.

Follow-up (exercising conversational memory):

```
Which of those benefits matters most for enterprise deployments?
```

> "Aurora is keeping context across turns. We're not restating the comparison — we're asking it to pivot."

**Fallback:** `What has Qualcomm contributed to Wi-Fi 8 discussions?`

---

### 19:00 — 24:00 · Act 4: Create your own agent

**Goal:** show this isn't just chat — users deploy passive, scheduled assistants.

1. Navigate to **My Agents** → **Create agent**.
2. Fill in live:
   - **Name:** `Wi-Fi 8 Daily Brief`
   - **Persona:** `Senior wireless architect. Dry, technical tone. Focus on chip-side implications and where the spec is still soft.`
   - **Topics:** `802.11be, 802.11bn, latency optimization, secure control frames`
   - **Organisations:** `IEEE, WBA, WFA`
   - **Cadence:** `daily-digest`
3. Click **Create**. Click **Run now** on the new agent.
4. Wait ~30 s. Refresh the **Feed** pane. The first post appears — title, body, sources.

> "Daily digests in your voice, on your topics, against the same knowledge base. One per project. Architects build agents for customer briefings. PMs build agents that watch a single workgroup."

**Fallback if the run is slow:** show an existing agent post from the feed and walk through the same flow.

---

### 24:00 — 27:30 · Act 5: What's next — Teams

**Goal:** set the roadmap without pretending Teams works today.

> "The same agents and queries will be available directly in Microsoft Teams — where most of you already live."

Show the **TEAMS_SHOWCASE.md** slide (or paste the Adaptive Card mockup on screen):

> "This is what the Teams experience looks like. You ask the same questions, get the same answers, subscribe to an agent's feed — all inside a Teams chat. We have the backend plumbed; IT provisioning is in progress. Target: live in corporate Teams by end of next week."

Point at the key scenarios from the mockup:
- `feed` → personal digest card in Teams chat.
- `@wba what happened in the IoT call last week` → same Oracle, same answer, threaded inline.
- `subscribe @aurora-wifi-8-daily-brief` → tomorrow's agent post lands in the chat.

> "No new tool to learn. Aurora goes to where you already work."

---

### 27:30 — 30:00 · Close & ask

> "Aurora is a prototype from the Office of the CTO Rapid AI Innovation team. The architecture is built. The data is flowing. What needs finishing: corporate Teams deployment with IT this week, a guided first-run setup, and the proactive push from agents that's plumbed but not yet wired."
>
> "We are inviting 25 people across Extreme to a one-week pilot starting Wednesday. The launch message and survey are ready."
>
> "Three things I'm asking from this room: nominate people for the pilot; point us at the working groups your teams care about most; tell us where this lands on your roadmap."

End on the survey URL / pilot sign-up slide.

---

## Q&A — prepared answers

**Q: How is this different from M365 Copilot or ChatGPT?**  
A: Copilot doesn't know your standards-body proceedings. ChatGPT doesn't have WBA Extranet or recent IETF drafts. Aurora is a domain-specific knowledge graph built on those sources, with answers that cite which document and which meeting.

**Q: Where does the data live? Is anything leaving Extreme?**  
A: Everything is in our corporate VPC — Postgres, Neo4j, Redis, all on EC2. The only outbound calls are to standards-body sites we have permission to read, and to Microsoft's Graph API once IT provisions the Teams app. No PII leaves Extreme. See `SECURITY_NOTES.md`.

**Q: What about WBA licensing on member-only content?**  
A: We're a member; our use is within membership terms. Aurora discards the body of every document after parsing — we store only the synopsis. We're not republishing WBA content; we're summarising it for our own employees who have access rights.

**Q: How does an agent decide what's "important"?**  
A: Each agent has an importance threshold that filters which events trigger a post, based on event recency, source weight, and topic match. The roadmap is to learn from per-agent thumbs-up / thumbs-down feedback.

**Q: What happens when a workgroup chair asks us to stop scraping?**  
A: Hard kill switch per DataSource in the admin UI. Disabling a source removes it from query results immediately and stops further ingest.

**Q: What does this cost?**  
A: Today it runs on a single EC2 box. The LLM call cost is the variable — back-of-envelope $40–80 per user per month at typical query volumes, dominated by the baseline-pipeline path. The fast-pipeline path (~70% of queries) is essentially free.

**Q: How do I get my workgroup added?**  
A: If it's a public body, we add a scraper — days not weeks. If it's member-only, we need credentials and a workgroup manifest. WBA works today; we'd extend the same pattern to CableLabs, 3GPP partner portals, etc.

---

## Verbatim queries — copy-paste ready

Primary set:
```
@wba what's new in NextGen Wi-Fi this month
What are the priorities of the IoT programme this quarter?
What is the difference between Wi-Fi 7 and Wi-Fi 8?
Which of those benefits matters most for enterprise deployments?
@wifi8mtg what has been discussed recently in the Wi-Fi 8 task group?
```

Fallback set:
```
@wba_extranet_iot_p5g latest activity
Summarise the latest Wi-Fi Alliance Causeway workgroup activity
What has Qualcomm contributed to Wi-Fi 8 discussions?
What compliance requirements exist for Wi-Fi 6E devices?
Explain the roaming problem caused by sticky clients
```

---

## Owner

Brendan Bonner — Office of the CTO, Rapid AI Innovation Team.
