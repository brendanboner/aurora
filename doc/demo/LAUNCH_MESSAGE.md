# Aurora — Launch Message Pack

**From:** Office of the CTO, Rapid AI Innovation Team
**For:** Internal Extreme Networks audiences — Product Managers (wireless/network/standards), Solution Architects / Field CTOs, Innovators / OCTO programmes, Standards/Firmware/Chip engineers.

This file contains the **company-wide launch message** plus four **audience-routed variants** (post the right variant to the right Teams channel / mailing list) plus the **survey questions** to put into a Microsoft Form before sending.

---

## Subject line — three A/B options

1. *Introducing Aurora — your AI partner for tracking the standards bodies you don't have time to read.*
2. *We built Aurora. It reads every WBA, IETF, and IEEE meeting so you don't have to.*
3. *Aurora is now open to a pilot — get standards-body intelligence in your browser and in Teams.*

Pick whichever lands cleanest for the channel.

---

## Company-wide launch message — long form

**Hi all,**

Tracking standards bodies is the kind of work that quietly shapes our roadmap and quietly burns out the people who do it. Every Wi-Fi Alliance NextGen call, every IETF SPRING draft, every IEEE 802.11bn agenda update — these are the inputs that decide what we build next, but almost nobody on a product team has time to read them as they happen.

The Office of the CTO Rapid AI Innovation Team has been building **Aurora**, a prototype that pulls together the public standards record from IETF and IEEE, the member-only working group activity from the WBA Extranet, and the public Wi-Fi Alliance press, and gives you a chat interface to ask questions of all of it in plain English. You can use it in your browser today and inside Microsoft Teams later this week.

Three things make Aurora different from a generic AI assistant:

- **Aurora has access to member-only content.** It logs in to the WBA Extranet on Extreme's behalf and reads workgroup digests that aren't on the public internet. Search Google all you want — you won't find what's in there.
- **Aurora is built on a knowledge graph.** Every answer is grounded in actual documents, with citations. We discard the document bodies after parsing so we don't redistribute member content, but we keep the metadata and synopsis you need to find the source.
- **Aurora lets you build your own agents.** Define an agent — give it a persona, the topics it cares about, the cadence (daily or weekly) — and it produces a digest that lands in your feed or in Teams. One per project, one per customer, one per workgroup. Yours, not ours.

This is a **prototype**. It is not feature-complete. We are looking for 25 pilot users this week, opening to the wider organisation the following week. The roadmap is being shaped by what the pilot users tell us.

**To get started:**

1. Log in at `<aurora-internal-url>` with your Extreme SSO. The user record is created on first login — no signup form.
2. Open Preferences, join the working groups you care about (Wi-Fi 8, IoT, NextGen Wi-Fi, IETF SPRING, etc.), mark the topics that matter to you.
3. Ask it something. *"What's new in NextGen Wi-Fi this month?"* — *"What's the difference between Wi-Fi 7 and Wi-Fi 8?"* — *"What has Qualcomm contributed to Wi-Fi 8 discussions?"*
4. Build yourself an agent in **My Agents** for daily digests on your projects.
5. (This week or next, depending on IT) Install the Aurora Teams app — same chat, same agents, in Teams.

**We want your feedback.** Please take five minutes for the survey: `<microsoft-forms-url>`. The pilot is sized so we can read every response.

Cheers,
**The Rapid AI Innovation Team — Office of the CTO**

---

## Audience-routed cuts

Send each of these to the channel / mailing list that matches the audience. They share the opening sentence and the same call to action, but the middle is tuned.

### Cut A — Product Managers (wireless / network / standards)

> Tracking standards bodies is the kind of work that quietly shapes our roadmap and quietly burns out the people who do it.
>
> Aurora is a prototype from the OCTO Rapid AI Innovation Team that turns standards-body activity into something you can actually use for roadmap conversations. Ask it what changed in WBA NextGen this month and get an answer with citations. Build a "Wi-Fi 8 weekly brief" agent that lands in your Teams chat every Monday morning. Stop wondering whether you missed a critical meeting note.
>
> We're piloting with 25 people this week. If you own roadmap for a wireless or network product, please try it: `<aurora-internal-url>`. Survey: `<microsoft-forms-url>`.

### Cut B — Solution Architects / Field CTOs

> Customers ask us "what does Wi-Fi 8 mean for me" and we don't always have a clean answer because the spec is moving.
>
> Aurora is a prototype from the OCTO Rapid AI Innovation Team. It composes answers across IETF, IEEE, WBA Extranet, and Wi-Fi Alliance press into a single grounded answer with the actual document sources. Useful for briefing customers, useful for diffing standards versions, useful for finding the one named person who's actually driving a thread.
>
> Try it: `<aurora-internal-url>`. Pilot is open this week — five minutes to set up. Survey: `<microsoft-forms-url>`.

### Cut C — Innovators / Office of CTO programmes

> Aurora is a prototype from inside the OCTO Rapid AI Innovation Team — a working example of putting a knowledge graph and LLMs on top of internal standards activity.
>
> The architecture is intentionally generalisable: any data source with an authenticated feed can be added; any user can define their own AI agent against the graph. We've used Wireless standards as the first vertical because the pain is real and the membership data already exists. But the same pattern would extend to any vertical Extreme operates in.
>
> Try it: `<aurora-internal-url>`. We're particularly interested in feedback from people who think about platform reusability. Survey: `<microsoft-forms-url>`.

### Cut D — Standards / Firmware / Chip engineers

> If you're tracking 802.11bn, BSS coloring, secure control frames, or PQC, Aurora has been quietly reading the WBA Extranet workgroup digests, the IETF drafts, and the IEEE working-group output and building a knowledge graph over them.
>
> Ask it `@wba_extranet_iot_p5g latest activity` or `@ietf show me recent drafts on 6 GHz spectrum` and get back a synopsis with the actual source documents — no body redistribution, just the metadata. Build a custom agent for the working group you'd otherwise need to dial into every Tuesday.
>
> It's a prototype from the OCTO Rapid AI Innovation Team. Live now: `<aurora-internal-url>`. Survey: `<microsoft-forms-url>`.

---

## Survey questions for Microsoft Forms

Put these into a Microsoft Form in the corporate tenant, then paste the URL back into both this file and `ADVERTISEMENT.md`. Keep the form to ~10 questions; respondent should finish in five minutes.

1. **What is your primary role at Extreme?** *(Choice, single)*
   - Product Manager
   - Solution Architect / Field CTO
   - Innovator / Office of CTO programmes
   - Standards / Firmware / Chip engineer
   - Other (please specify)

2. **Which working groups or standards topics do you care most about?** *(Free text, optional)*

3. **In your first week of using Aurora, how often did you query it?** *(Choice, single)*
   - Daily
   - A few times this week
   - Once or twice
   - I haven't tried it yet

4. **How useful were Aurora's answers?** *(Rating 1–5)*
   - 1 — Not useful
   - 5 — Saved me significant time

5. **How much time did Aurora save you this week (rough estimate)?** *(Choice, single)*
   - None / can't tell yet
   - <30 min
   - 30 min – 2 hours
   - 2 – 5 hours
   - 5+ hours

6. **Did you create a custom agent? If so, what was its purpose?** *(Free text, optional)*

7. **Would you prefer daily digests, weekly digests, or "important only" notifications?** *(Choice, single)*
   - Daily
   - Weekly
   - Important only
   - I prefer to query on demand
   - Mix — different agents for different cadences

8. **Did you use Aurora in Teams, in the browser, or both?** *(Choice, multi-select)*
   - Browser
   - Teams
   - I haven't installed Teams yet
   - I didn't know it was in Teams

9. **What is the single most useful thing Aurora did for you this week?** *(Free text)*

10. **On a scale of 0–10, how likely are you to recommend Aurora to a colleague who tracks standards bodies?** *(Rating 0–10 — used as NPS)*

11. **What is the one thing you most want Aurora to do that it can't today?** *(Free text)*

12. **(Optional) May we follow up with you for a 15-minute conversation?** *(Choice — Yes / No, and email field if Yes)*

(Questions 11 and 12 are bonus — drop one if you want to keep to ten exactly.)

---

## Sign-off

All variants end with:

> **From the Office of the CTO, Rapid AI Innovation Team.**

Don't strip the origin — it both attributes the work and frames Aurora honestly as a prototype, which sets the right expectations for feedback.
