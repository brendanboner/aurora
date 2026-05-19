# Aurora — 30-Minute Demo Walkthrough

**Date:** 2026-05-19 (updated)
**Presenter:** Brendan Bonner — Office of the CTO, Rapid AI Innovation Team  
**Audience:** Senior leadership; product managers, solution architects / field CTOs, innovators, standards/firmware/chip engineers.  
**Format:** 30 min walkthrough + Q&A. Live on the production system.  
**Teams status:** ✅ Live via Microsoft 365 Agents Playground — run `make teams-test-prod NGROK_DOMAIN=anemia-pretext-morbidly.ngrok-free.dev`

---

## Pre-demo checklist (T-15 min)

```bash
make teams-test-prod NGROK_DOMAIN=anemia-pretext-morbidly.ngrok-free.dev
./doc/demo/demo_runner.sh --setup   # automated health checks
./doc/demo/demo_runner.sh --warmup  # cache all queries < 2s
```

Manual checks:
- Production EC2 healthy — monitoring page, no stalled batches.
- Smoke query warm: `What is the difference between Wi-Fi 7 and Wi-Fi 8?` < 3 s.
- Browser: dark mode, Aurora web tab, zoomed to 125%.
- Teams Playground open at `http://localhost:56150` — confirm Aurora responds to `help`.
- Phone: Do Not Disturb. Slack: closed. Email: closed.

---

## Persona tuning

- **Mostly Product Managers** → linger on Act 4 (personal agents + Teams feed), compress Act 3.
- **Mostly Solution Architects / Field CTOs** → linger on Act 3 (cross-source synthesis + enhance), Act 5 (group intelligence).
- **Mostly Standards/Firmware/Chip engineers** → linger on Act 2 (IEEE task groups), Act 5 (workgroup scoping + follow-up).
- **Mostly Innovators / OCTO** → show Acts 4–5 in full; emphasise planetary Wi-Fi moment for levity.

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
2. Click avatar / **Profile** → **Groups & Sources** tab.
3. Join: **Wi-Fi 8 - Ultra High Reliability**, **AI/ML for Wi-Fi**, **5G & Wi-Fi Convergence**.
4. **Sources** tab → join **WFA Resource Page** and **IEEE 802.11 Task Groups**.
5. **Technology** tab → star **Wi-Fi 8** and **PQC**.

> "Sixty seconds. Aurora knows what to dig into and respects access control — you only see what you've joined."

---

### 7:00 — 14:00 · Act 2: Member-only + IEEE standards access

**Goal:** content nobody can Google.

```
@wba what's new in NextGen Wi-Fi this month
```

> "The `@wba` mention scopes this to Wireless Broadband Alliance sources — member-only meeting digests that require a login to reach."

Point out a named person and workgroup. Click a source card.

```
What is the current status of 802.11bn?
```

> "Public IEEE 802.11 task group pages — TGbn ballot timeline, March 2026 plenary summary. Aurora scrapes all active 802.11 task groups weekly."

Follow-up — exercising conversation memory:

```
Who is chairing that task group?
```

> "Aurora remembers the previous answer. 'That task group' means TGbn — Alfred Asterjadhi, new WG 1st Vice Chair."

**Fallback:** `What compliance requirements exist for Wi-Fi 6E devices?`

---

### 14:00 — 19:00 · Act 3: Cross-source synthesis + deep read

**Goal:** Aurora composes answers that no single document contains — then lets you go deeper.

```
What is the difference between Wi-Fi 7 and Wi-Fi 8?
```

> "This answer draws from IEEE 802.11bn task group pages, WFA certification proposals, WBA Extranet working-group discussions, and IETF drafts. No single document has it."

Call out IEEE, WFA, WBA, IETF all in the source list.

Follow-up:

```
Which of those benefits matters most for enterprise deployments?
```

> "Context across turns — we're not restating the comparison, we're asking it to pivot."

Now demonstrate the **Enhance** button or command:

```
enhance
```

> "Enhance fetches the actual source documents and re-reads them. The citations become clickable links with exact page references. This is the difference between a summary and a briefing."

---

### 19:00 — 22:00 · Act 3b: Something unexpected — the IETF Planetary Networking moment

**Goal:** show Aurora's breadth and create a memorable moment.

```
Does Wi-Fi work in space?
```

> "Watch what happens when you ask something Aurora shouldn't know about."

Let it answer (will reference IETF InterPlanetary Networking research group, QUIC for deep-space communications, etc.).

Follow-up:

```
What is new in IETF this week?
```

> "Back to Earth — same knowledge graph, same conversational memory. That Wi-Fi-in-space answer didn't break the session."

> "The point: Aurora tracks IETF's full working group portfolio. The InterPlanetary Networking group is real. Engineers working on delay-tolerant protocols for space missions use the same base standards your Wi-Fi chips rely on."

---

### 22:00 — 26:00 · Act 4: Personal agents

**Goal:** Aurora curating content in your voice, on your topics.

1. **My Agents** → **Create agent**:
   - **Name:** `Wi-Fi 8 Daily Briefing`
   - **Project description:** `I am tracking Wi-Fi 8 (IEEE 802.11bn) development for enterprise and chip-level deployment. I want updates on Ultra High Reliability (UHR) progress, ballot timelines, MLO enhancements, latency improvements, and how Wi-Fi 8 compares to Wi-Fi 7 for enterprise use cases. My primary sources are the IEEE 802.11 task group (TGbn), WFA Causeway Wi-Fi 8 task group, and WBA enterprise Wi-Fi discussions.`
   - **Focus and lane guidance:** `Focus on 802.11bn, 802.11be, chip-side implications, latency, and enterprise deployment. Ignore general Wi-Fi news not related to Wi-Fi 8 development.`
   - **Cadence:** `daily-digest`
2. Click **Create** → **Run now**.
3. Wait ~30 s. Feed shows the first post.

> "One description. No prompt engineering. The agent works out what sources to read, what's new, and writes a briefing in the style you've described. Architects use this for customer briefings; PMs use it to track a single workgroup."

---

### 26:00 — 30:00 · Act 5: Teams — group intelligence

**Goal:** Aurora works where teams already are. Show the full loop.

Switch to the Agents Playground browser tab.

**Scenario A — Personal chat with follow-up:**

```
feed
```
> "Same feed as the web UI — inside Teams."

```
@ietf what is new this week
```
> "Scoped to IETF. Full answer with sources."

```
What was the most interesting topic?
```
> "Aurora remembers the IETF context and follows up — no need to repeat yourself."

```
enhance
```
> "Fetches the source documents and gives a deeper answer with clickable citations — all without leaving Teams."

**Scenario B — Group channel with workgroup scoping:**

Switch to **Group Chat** tab.

```
@Aurora @wba what is the current status of 802.11bn?
```
> "Same full answer in a group channel, scoped to WBA sources."

```
@Aurora who is Brendan Bonner
```
> "Aurora knows who's in the room. Brendan Bonner: Senior Principal Architect at Extreme Networks, WBA member, contributing to the Enterprise Security for Private 5G and Security & Post-Quantum Computing workgroups."

Subscribe the group to a workgroup feed:

```
@Aurora subscribe @mister-multipath
```
> "Now this channel gets proactive updates from the Mister Multipath agent whenever it publishes."

**Scenario C — Proactive delivery:**

Trigger `make teams-test-announce` in a separate terminal.

> "This is Aurora pushing a breaking standards update to every channel that has the bot. No one asked. Standards teams stay informed automatically."

---

### Close & ask

> "Aurora is a prototype from the Office of the CTO. The architecture is built. The data is flowing — IEEE, IETF, WBA, WFA, all updating weekly. Teams is live for testing.
>
> Three things I'm asking: nominate people for the pilot; tell us which working groups matter to your teams; tell us where this lands on your roadmap."

---

## Q&A — prepared answers

**Q: How is this different from M365 Copilot or ChatGPT?**  
A: Neither knows your standards-body proceedings. Aurora is a domain-specific knowledge graph built on WBA Extranet, WFA Causeway, IETF, IEEE 802.11/802.1/802.3 — with answers that cite the specific document and meeting.

**Q: Where does the data live?**  
A: Everything in our corporate VPC — Postgres, Neo4j, Redis, EC2. No PII leaves Extreme.

**Q: What about WBA member-only content licensing?**  
A: We're a member; within membership terms. Aurora stores only the synopsis, not the full document. Not republishing; summarising for employees with access rights.

**Q: How does Teams work without IT provisioning?**  
A: Via the Microsoft 365 Agents Playground locally. Corporate Teams app deployment is in progress with IT.

**Q: What does this cost?**  
A: Single EC2 box. LLM cost ~$40–80/user/month at typical query volumes.

**Q: How do I get my workgroup added?**  
A: Public bodies (IEEE, IETF) — scraper in days. Member-only (WBA, WFA Causeway) — need credentials and workgroup list.

---

## Verbatim queries — copy-paste ready

**Primary set (web):**
```
@wba what's new in NextGen Wi-Fi this month
What is the current status of 802.11bn?
Who is chairing that task group?
What is the difference between Wi-Fi 7 and Wi-Fi 8?
Which of those benefits matters most for enterprise deployments?
enhance
```

**The planetary moment:**
```
Does Wi-Fi work in space?
What is new in IETF this week?
```

**Teams personal chat:**
```
feed
@ietf what is new this week
What was the most interesting topic?
enhance
```

**Teams group chat:**
```
@Aurora @wba what is the current status of 802.11bn?
@Aurora who is Brendan Bonner
@Aurora subscribe @mister-multipath
```

**Fallback set:**
```
What has Qualcomm contributed to Wi-Fi 8 discussions?
What compliance requirements exist for Wi-Fi 6E devices?
Explain the roaming problem caused by sticky clients
What is the latest on the IEEE 802.11bn March 2026 plenary?
@wba who is Mark Hamilton
```

---

## Teams setup for the demo (do this at T-15 min)

```bash
# Start everything — tunnels, bot, playground, ngrok for proactive delivery
make teams-test-prod NGROK_DOMAIN=anemia-pretext-morbidly.ngrok-free.dev

# In a second terminal, warm the cache
./doc/demo/demo_runner.sh --warmup

# Test announcement push
make teams-test-announce
```

Playground opens at `http://localhost:56150`.

- Type `help` to confirm bot responds as "Aurora"
- Personal chat: full answers, conversation memory, enhance
- Group Chat tab: use `@Aurora [question]` — workgroup scoping with `@wba`, `@ietf`, `@wifi8mtg`
- `@Aurora groupmode on` enables passive listening for standards questions
  - **Playground only**: works in the simulator because all messages are delivered to the bot
  - **Real Teams**: requires `ChannelMessage.Read.Group` RSC permission (now in manifest) + admin consent at app installation — passive listening will work once IT deploys with consent granted
- `subscribe @slug` to get proactive updates in the channel
- `my agents` to see personal agents and share them to the group

---

## Owner

Brendan Bonner — Office of the CTO, Rapid AI Innovation Team.
