# Aurora — Monday Demo & End-of-Week Launch Pack

**Office of the CTO, Rapid AI Innovation Team — Extreme Networks**

This directory contains everything needed to (a) deliver the Monday 2026-05-18 demo of Aurora to senior leadership and (b) soft-launch Aurora to a 25-person pilot cohort by Friday 2026-05-22.

Aurora is a prototype. It pulls together standards-body activity (Wi-Fi Alliance, IETF, IEEE) — including member-only WBA Extranet content — into a single chat surface, with user-defined AI agents that produce daily and weekly digests. It runs in the browser today and inside Microsoft Teams as soon as IT provisioning lands.

## What's in this folder

| File | Purpose | Audience |
|---|---|---|
| `DEMO_PLAN.md` | 30-minute live walkthrough with timing, queries, fallbacks, Q&A | Presenter |
| `IT_PERMISSIONS_REQUEST.md` | Escalation note to forward to corporate IT / Entra admin / Teams admin | Internal IT |
| `LAUNCH_MESSAGE.md` | Final draft of the company-wide announcement + 4 audience cuts + survey questions | Comms / presenter |
| `ENGAGEMENT_PLAN.md` | Pilot/launch phases, KPIs with targets, enablement artefacts, owner matrix | Project owner |
| `ADVERTISEMENT.md` | Standing landing-page copy for the intranet info site | Comms |
| `SETUP_COMMANDS.md` | Pre-demo / demo / post-demo command playbook | Presenter |
| `SECURITY_NOTES.md` | Technical security/compliance brief — appendix for the IT request | IT / compliance |

## Order to use this pack

1. **Today (Wed 2026-05-13)** — Forward `IT_PERMISSIONS_REQUEST.md` to the corporate IT / Entra / Teams admin owners. Start the human escalation clock.
2. **Thu–Fri** — Walk through `SETUP_COMMANDS.md` end-to-end at least once. Dry-run `DEMO_PLAN.md` start-to-finish, ideally with one trusted colleague in the audience. Iterate on the queries that don't land cleanly.
3. **Mon 2026-05-18 morning** — Run the T-1 hour through T-5 min checklist in `SETUP_COMMANDS.md`. Deliver the demo.
4. **Mon afternoon → Wed** — Create the Microsoft Forms survey from the question content in `LAUNCH_MESSAGE.md`. Paste the URL into both `LAUNCH_MESSAGE.md` and `ADVERTISEMENT.md`.
5. **Wed–Fri** — Hand-pick the 25 pilot users per `ENGAGEMENT_PLAN.md` Phase 1. Send the audience-routed launch message variants. Pin `ADVERTISEMENT.md` content to the company info site.
6. **Following week** — Phase 2 soft launch; office hours; weekly KPI review against the targets in `ENGAGEMENT_PLAN.md`.

## Status assumptions (as of 2026-05-13)

- Aurora production system is healthy and reachable via SSO.
- WBA Extranet authenticated scraping is live; child workgroup DataSources are populating.
- Teams agent runs locally and over an ngrok tunnel to a personal/dev Teams tenant. Corporate-tenant deployment is gated on the IT escalation in this pack.
- No in-app onboarding wizard exists yet. The demo walks through manual setup; the pilot uses white-glove 15-min onboardings to cover the gap.

## Origin

Prototype from the **Office of the CTO, Rapid AI Innovation Team**. Repository: `octo-rapid-aurora`. Primary architecture reference: `.github/copilot-instructions.md` and `CLAUDE.md` at the repo root.
