# Aurora — Engagement Plan, KPIs & Enablement

**Owner:** Office of the CTO, Rapid AI Innovation Team
**Plan window:** 2026-05-13 → 2026-06-15 (four weeks)
**Goal:** move Aurora from internal prototype to a tool that 100+ Extreme employees use weekly, with documented success metrics and a feedback loop that drives the next iteration.

---

## Phases

### Phase 0 — Preparation (this week, 2026-05-13 → 2026-05-17)

| Day | Action | Owner |
|---|---|---|
| Wed 13 May | Forward `IT_PERMISSIONS_REQUEST.md` to IT / Entra / Teams admins. Begin escalation clock. | Aurora technical owner |
| Wed 13 May | Capture KPI baselines (see *Baselines* below). | Aurora technical owner |
| Thu 14 May | Microsoft Form created from `LAUNCH_MESSAGE.md` question list; URL pasted into the launch and advertisement files. | Comms partner |
| Thu 14 May | Pilot cohort identified — 25 names across the four audience tiers (target mix: 8 PMs, 7 architects, 5 innovators, 5 engineers). | Aurora technical owner + sponsor |
| Fri 15 May | Demo dry-run with one trusted colleague following `DEMO_PLAN.md`. Iterate on weak queries. | Aurora technical owner |
| Mon 18 May | Boss-facing demo. Reference success of the demo as a green-light gate before Phase 1. | Aurora technical owner |

### Phase 1 — Pilot (week of 2026-05-18 → 2026-05-22)

- **Cohort size:** 25 hand-picked users across the four personas.
- **Onboarding model:** **White-glove**. Schedule a 15-min 1:1 with each pilot user. Walk them through SSO login → Preferences setup → first query → first agent. This compensates for the missing in-app onboarding wizard.
- **Dedicated feedback channel:** create a private Teams channel `aurora-pilot-feedback`. Pin the survey and a "what works / what didn't" template message.
- **Daily check-in:** Aurora technical owner posts one observation per day in the channel — a query that surprised them, a feature being used unexpectedly, a stall.
- **End-of-week ritual:** Friday at 16:00, post the week-1 KPI snapshot to the channel.
- **Launch message:** send Cut A/B/C/D from `LAUNCH_MESSAGE.md` to the corresponding pilot sub-cohorts on **Wed 2026-05-20**, after most pilot users have done their white-glove onboarding.

### Phase 2 — Soft launch (week of 2026-05-25 → 2026-05-29)

- **Audience:** open to wider Wireless / OCTO / standards-adjacent organisations. Target ~100 invited users.
- **Onboarding model:** self-serve. The launch message + `ADVERTISEMENT.md` page + a 90-second screen recording are the entire kit.
- **Office hours:** twice-weekly 30-min drop-ins on Tue and Thu. Pin to the intranet info page.
- **In-app feedback:** every chat answer gets thumbs-up / thumbs-down already. Surface a "leave a comment" prompt on thumbs-down (post-MVP — flag if not landed by 2026-05-22).
- **Survey:** keep the same Microsoft Form running. Aggregate week 1 vs week 2 cohort responses separately.

### Phase 3 — Iterate (2026-06-01 → 2026-06-15)

- First feedback-driven release: top three asks from the pilot survey, implemented and shipped.
- Public retrospective: post the survey aggregates (anonymised) to the intranet page. Show what changed.
- Decision gate: based on Phase 2 KPIs, either request budget for full productionisation or fold the project back into OCTO research.

---

## Success KPIs

All metrics measured weekly, compared to baseline (Phase 0) and prior week.

| KPI | Definition | Target | How measured |
|---|---|---|---|
| **Activation** | % of invited pilot users who log in at least once within 7 days of invitation | 60% | PostgreSQL `users` table + invitation list |
| **Setup completion** | % of activated users who have joined ≥1 workgroup AND set ≥1 topic preference | 50% | `user_source_preferences` + `user_topic_preferences` tables |
| **Weekly active users (WAU)** | Users with ≥1 chat query in the last 7 days | 30% of invited by week 2 | Oracle query log |
| **Custom agents created** | Count of unique user-created agents (CreatorAgent or MyAgent) | ≥5 within first two weeks; ≥15 by Phase 2 end | `creator_agents`, `my_agents` tables |
| **Teams adoption** | % of WAU who have sent ≥3 messages to the Teams bot | 40% (gated on IT provisioning landing) | `teams-agent` conversation log |
| **Query quality signal** | % of chat answers receiving a thumbs-down | <15% | Oracle feedback log |
| **NPS-equivalent** | Microsoft Forms Q10 — "0-10 likely to recommend" | ≥+20 | Survey aggregate |
| **Time-saved (self-report)** | Median of Q5 — "time Aurora saved you this week" | ≥2 hours/user/week by week 4 | Survey aggregate |
| **Source coverage signal** | Count of distinct DataSources accessed via queries in last 7 days | ≥15 by week 2 | Oracle query log |
| **Stickiness** | WAU / MAU (rolling 4-week monthly) | ≥0.4 by Phase 3 | PostgreSQL query log |

### Baselines to capture before Phase 1 begins

Run these on Wed 2026-05-13 and record the result in this file:

- Daily active user count (last 7 days): **TBD**
- Total Aurora user accounts: **TBD**
- Total queries last 7 days: **TBD**
- Total agents (CreatorAgent + MyAgent): **TBD**
- Top 5 most-queried DataSources: **TBD**

The Phase 1 deltas need a baseline to be meaningful.

---

## Enablement artefacts

Each of these is a tangible deliverable for Phase 1/2. Owners listed; date is when it must be ready.

| Artefact | Format | Ready by | Owner |
|---|---|---|---|
| **1-pager quick-start** | Single-page PDF — login, set preferences, ask, build agent. Screenshot-heavy. | Wed 2026-05-20 | Aurora technical owner |
| **90-second screen recording** | MP4, no audio narration (or optional voice-over). Hosted on internal video portal. Same flow as `DEMO_PLAN.md` Acts 1–4 compressed. | Thu 2026-05-21 | Aurora technical owner |
| **FAQ** | Markdown page on intranet info site. Seeded from `DEMO_PLAN.md` Q&A section; grows with pilot questions. | Live by Mon 2026-05-18, maintained weekly | Aurora technical owner |
| **Teams pinned-post template** | Short markdown for pilot channel — links to all artefacts. | Mon 2026-05-18 | Aurora technical owner |
| **Office-hours agenda template** | Markdown; 30-min slot, three pre-set demo topics, 15 min open Q&A. | Mon 2026-05-25 | Aurora technical owner |
| **Cohort tracker spreadsheet** | Pilot user list with onboarding date, first-query date, agent count, survey-returned flag. | Wed 2026-05-13 | Aurora technical owner |
| **Weekly KPI digest** | Internal markdown post in the pilot channel + emailed to the OCTO sponsor every Friday. | Fri 2026-05-22 onwards | Aurora technical owner |
| **Retrospective doc (Phase 3)** | Markdown — what worked, what didn't, what we changed, what's next. | Mon 2026-06-15 | Aurora technical owner |

---

## Owner matrix

Fill in the names before sending the launch message.

| Role | Responsibility | Name |
|---|---|---|
| **Aurora technical owner** | All Aurora-side work — code, deployment, monitoring, weekly KPI digest | Brendan Bonner |
| **OCTO sponsor** | Stakeholder management, demo introduction, budget escalation, decision gate at Phase 3 | _________________ |
| **Comms partner** | Microsoft Forms creation, intranet page publish, launch-message send | _________________ |
| **IT liaison** | Tracking the Teams provisioning request from `IT_PERMISSIONS_REQUEST.md` | _________________ |
| **Pilot cohort owner per persona** | Picking names, doing 15-min white-glove onboardings, collecting feedback | PMs: _____ · Architects: _____ · Innovators: _____ · Engineers: _____ |

---

## Risk register and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Corporate Teams not provisioned by Fri 2026-05-22 | Medium | High — pilot is harder without Teams | Hybrid demo path on Monday uses ngrok; pilot can run web-only for a week if needed. Adjust Teams KPI window. |
| WBA Extranet credentials expire mid-pilot | Low | Medium — member-only content stops updating | HLLogin cookie has 7-day expiry; calendar reminder every Friday to refresh from browser. |
| LLM cost balloons with usage | Low (small cohort) | Medium long-term | Fast pipeline handles ~70% of queries at near-zero cost. Monitor; escalate before Phase 3 decision gate. |
| Pilot users disengage after week 1 | Medium | High | White-glove onboarding + daily check-ins + Friday KPI ritual are designed to surface this early. |
| In-app onboarding missing → pilot users get stuck | High (we know it's a gap) | Medium | White-glove 15-min walkthroughs in Phase 1. Build the wizard during Phase 2. |
| Survey fatigue, low response rate | Medium | Low — survey is one input among many | Keep survey to 10 questions, five-minute limit; chase non-responders in the pilot Teams channel personally. |
| Sensitive workgroup chair objects to scraping | Low | High — could force WBA disable | Hard kill switch per DataSource exists in admin UI. Pre-empt by having the Aurora team brief their WBA contact at WFA before pilot start. |

---

## Decision gate (end of Phase 3)

At 2026-06-15, the Aurora technical owner produces a single document answering three questions:

1. Did Phase 2 hit the WAU and NPS targets?
2. What three pieces of feedback most need to be addressed for the next iteration?
3. What does the next phase require — more engineering time, more sources, more agents, productionisation?

Submit to OCTO sponsor. Decision: continue investment, fold back to research, or productionise.
