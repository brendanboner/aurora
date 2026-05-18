# Aurora — 30-Minute Demo Walkthrough

**Date:** Monday 2026-05-18  
**Presenter:** Brendan Bonner — Office of the CTO, Rapid AI Innovation Team  
**Audience:** Senior leadership; product managers, solution architects / field CTOs, innovators, standards/firmware/chip engineers.  
**Format:** 30 min walkthrough + Q&A. Live on the production system.  
**Teams status:** ✅ Live via Microsoft 365 Agents Playground — run `make teams-test-prod` to open.

---

## Pre-demo checklist (T-15 min)

```bash
./doc/demo/demo_runner.sh --setup   # automated health checks
./doc/demo/demo_runner.sh --warmup  # cache all queries < 2s
```

Manual checks:
- Production EC2 healthy — monitoring page, no stalled batches.
- Smoke query warm: `What is the difference between Wi-Fi 7 and Wi-Fi 8?` < 8 s.
- Browser: dark mode, Aurora web tab, zoomed to 125%.
- **Teams (Act 5):** run `make teams-test-prod` in a terminal — browser opens at `http://localhost:56150`. Confirm bot is responding (`help` command).
- Phone: Do Not Disturb. Slack: closed. Email: closed.

---

## Persona tuning

- **Mostly Product Managers** → linger on Act 4 (custom agents), compress Act 3.
- **Mostly Solution Architects / Field CTOs** → linger on Act 3 (cross-source synthesis), show source list.
- **Mostly Standards/Firmware/Chip engineers** → linger on Act 2 (member-only content) and Act 5 (IEEE 802.11 task group updates).
- **Mostly Innovators / OCTO** → linger on Act 5 (Teams group intelligence + announcements).

---

## The walkthrough

### 0:00 — 2:30 · Cold open: the problem

> "How many of you have read every WBA NextGen Wi-Fi meeting note from the last month? Right. How many have read every IETF draft and IEEE 802.11 agenda since February?"
>
> "Every product team at Extreme is trying to track standards bodies that move faster than any one person can read. We pay membership fees. We send people to meetings. But the knowledge stays locked in PDFs and minutes that almost nobody opens."
>
> "Aurora reads them for you — public standards from IETF, IEEE 802.11, 802.1, and 802.3, and member-only working-group activity from WBA Extranet. One place, plain English, your browser — and now, your Teams channel."

Switch to the Aurora web tab.

---

### 2:30 — 7:00 · Act 1: Login & personalisation

**Goal:** one SSO click, thirty seconds of setup.

1. Click **Log in** → Cognito SSO → land on Aurora home.
2. Click avatar / **Profile** → **Groups & Sources** tab opens by default.
3. Join: **Wi-Fi 8 - Ultra High Reliability**, **AI/ML for Wi-Fi**, **5G & Wi-Fi Convergence** (gold member-only badges).
4. **Sources** tab → join **WFA Resource Page** and **IEEE 802.11 Task Groups**.
5. **Technology** tab → star **Wi-Fi 8** and **PQC**.

> "Sixty seconds. Aurora knows what to dig into and respects access control — you only see what you've joined."

---

### 7:00 — 14:00 · Act 2: Member-only + IEEE standards access

**Goal:** content nobody can Google — including IEEE task group drafts.

```
@wba what's new in NextGen Wi-Fi this month
```

> "The `@wba` mention scopes this to Wireless Broadband Alliance sources — member-only meeting digests that require a login to reach."

Point out a named person and workgroup. Click a source card.

Second query — new since last demo:

```
What is the current status of 802.11bn?
```

> "This is from the public IEEE 802.11 task group pages — TGbn status page, ballot timeline, March 2026 plenary summary. Aurora now scrapes all active 802.11 task groups weekly: TGbn, TGbi, TGbp, TGbt, TGbq, TGbr, TGmf, plus 802.1 and 802.3."

Follow-up — exercising conversation memory:

```
Who is chairing that task group?
```

> "Aurora remembers the previous answer and enriches the follow-up — it knows 'that task group' means TGbn."

**Fallback:** `What compliance requirements exist for Wi-Fi 6E devices?`

---

### 14:00 — 19:00 · Act 3: Cross-source synthesis

```
What is the difference between Wi-Fi 7 and Wi-Fi 8?
```

> "This answer lives in seven places: IEEE 802.11bn task group pages, WFA certification proposals, WBA Extranet working-group discussions, and IETF drafts. No single document has it. Aurora composes one."

Source list — call out IEEE, WFA, WBA, IETF all in one answer.

Follow-up:

```
Which of those benefits matters most for enterprise deployments?
```

> "Context across turns. We're not restating the comparison — we're asking it to pivot."

---

### 19:00 — 24:00 · Act 4: Create your own agent

1. **My Agents** → **Create agent**:
   - **Name:** `Wi-Fi 8 Daily Brief`
   - **Persona:** `Senior wireless architect. Dry, technical tone. Focus on chip-side implications.`
   - **Topics:** `802.11be, 802.11bn, latency optimization`
   - **Cadence:** `daily-digest`
2. Click **Create** → **Run now**.
3. Wait ~30 s. Feed shows the first post.

> "Daily digests in your voice, on your topics. Architects build agents for customer briefings. PMs build agents that watch a single workgroup."

---

### 24:00 — 28:30 · Act 5: Teams — group intelligence + announcements

**Goal:** Aurora works where teams already are, and adds value to conversations in progress.

Switch to the Agents Playground browser tab (already open from `make teams-test-prod`).

**Scenario A — Personal chat:**

```
feed
```
> "Same feed as the web UI — agent posts, sources, tags — inside Teams."

```
@wifi8mtg what has been discussed recently?
```
> "Full answer in Teams. Conversation memory means you can follow up immediately."

```
Who is chairing that group?
```
> "Aurora remembers the Wi-Fi 8 context and answers Alfred Asterjadhi — new WG 1st Vice Chair."

**Scenario B — Group chat context awareness:**

Switch to **Group Chat** tab. Type:

```
@Aurora what is the current status of 802.11bn?
```

> "Same full answer in a group channel. Now here's the interesting part."

Still in group chat, type `groupmode on`. Then (simulating a colleague):

```
@Aurora do we know how Wi-Fi 8 will affect handover between APs?
```

> "Aurora adds context to the group conversation without disrupting it — it recognised a standards question and contributed."

**Scenario C — Proactive broadcast:**

In a separate terminal: `make teams-test-announce`

> "This is Aurora pushing a breaking standards update — IEEE 802.11bn D2.0 ballot opening — to every channel that has the bot, without anyone asking. Standards teams get notified automatically."

---

### 28:30 — 30:00 · Close & ask

> "Aurora is a prototype from the Office of the CTO. The architecture is built. The data is flowing — IEEE, IETF, WBA, WFA, all updating weekly. Teams is live for testing; corporate provisioning is in progress with IT.
>
> Three things I'm asking from this room: nominate people for the pilot; tell us which working groups matter to your teams; tell us where this lands on your roadmap."

---

## Q&A — prepared answers

**Q: How is this different from M365 Copilot or ChatGPT?**  
A: Neither knows your standards-body proceedings. Aurora is a domain-specific knowledge graph built on WBA Extranet, WFA Causeway, IETF, IEEE 802.11/802.1/802.3 — with answers that cite the specific document and meeting.

**Q: Where does the data live?**  
A: Everything in our corporate VPC — Postgres, Neo4j, Redis, EC2. The only outbound calls are to standards-body sites we have permission to read. No PII leaves Extreme.

**Q: What about WBA member-only content licensing?**  
A: We're a member; within membership terms. Aurora discards document bodies after parsing — we store only the synopsis. Not republishing; summarising for employees with access rights.

**Q: How does Teams work without IT provisioning?**  
A: Right now via the Microsoft 365 Agents Playground — a local testing tool that gives the full Teams experience. Corporate Teams app deployment is in progress with IT and will light up the same bot for every employee.

**Q: What does this cost?**  
A: Single EC2 box. LLM cost ~$40–80/user/month at typical query volumes, dominated by the baseline pipeline. The fast pipeline (~70% of queries) is essentially free.

**Q: How do I get my workgroup added?**  
A: Public bodies (IEEE, IETF) — we add a scraper in days. Member-only (WBA, WFA Causeway) — we need credentials and a workgroup list. WBA works today; same pattern extends to CableLabs, 3GPP, etc.

**Q: What happens if a workgroup chair asks us to stop scraping?**  
A: Hard kill switch per DataSource in the admin UI. Disabling removes it from results immediately.

---

## Verbatim queries — copy-paste ready

**Primary set (web):**
```
@wba what's new in NextGen Wi-Fi this month
What is the current status of 802.11bn?
What is the difference between Wi-Fi 7 and Wi-Fi 8?
Which of those benefits matters most for enterprise deployments?
@wifi8mtg what has been discussed recently in the Wi-Fi 8 task group?
```

**Teams personal chat:**
```
feed
@wifi8mtg what has been discussed recently?
Who is chairing that group?
```

**Teams group chat (after groupmode on):**
```
@Aurora what is the current status of 802.11bn?
@Aurora do we know how Wi-Fi 8 will affect handover between APs?
```

**Fallback set:**
```
What has Qualcomm contributed to Wi-Fi 8 discussions?
Summarise the latest Wi-Fi Alliance Causeway workgroup activity
What compliance requirements exist for Wi-Fi 6E devices?
Explain the roaming problem caused by sticky clients
What is the latest on the IEEE 802.11bn March 2026 plenary?
```

---

## Teams setup for the demo (do this at T-15 min)

```bash
# Start Teams bot on production EC2, open Agents Playground browser
make teams-test-prod

# In a second terminal, pre-test the bot
# (browser should open automatically at http://localhost:56150)

# Test announcement push
make teams-test-announce
```

- Personal chat: bot responds to everything, full Adaptive Cards.
- Group Chat tab: @mention the bot with `@Aurora [question]`.
- `groupmode on` enables passive listening for standards questions.
- `clear` or `reset` exits any workgroup scope.
- `@5g`, `@wba`, `@wifi8mtg` scope answers to that datasource.

---

## Owner

Brendan Bonner — Office of the CTO, Rapid AI Innovation Team.
