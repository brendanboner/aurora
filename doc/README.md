# Aurora — Documentation Index

This directory holds living documentation for Aurora. The authoritative architecture reference is `.github/copilot-instructions.md` at the repo root; the short version is `CLAUDE.md` at the repo root. Everything here is supporting detail, grouped by audience.

## Start here

| If you are… | Read |
|---|---|
| **New to the codebase** | [`QUICKSTART.md`](QUICKSTART.md) — getting Aurora running locally |
| **Building or modifying the query pipeline** | [`PIPELINE_FLOW.md`](PIPELINE_FLOW.md), [`FAST_PIPELINE.md`](FAST_PIPELINE.md) |
| **Deploying / running production** | [`DEPLOYMENT.md`](DEPLOYMENT.md), [`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md), [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |
| **Setting up the Teams integration** | [`TEAMS_IT_ADMIN_GUIDE.md`](TEAMS_IT_ADMIN_GUIDE.md), then [`demo/IT_PERMISSIONS_REQUEST.md`](demo/IT_PERMISSIONS_REQUEST.md) |
| **Preparing for the Monday demo / launch** | [`demo/README.md`](demo/README.md) |
| **From corporate IT / Security / Compliance** | [`IT/README.md`](IT/README.md), [`demo/SECURITY_NOTES.md`](demo/SECURITY_NOTES.md) |

## Architecture and engineering

| Doc | Covers |
|---|---|
| [`PIPELINE_FLOW.md`](PIPELINE_FLOW.md) | End-to-end query processing flow |
| [`FAST_PIPELINE.md`](FAST_PIPELINE.md) | Graph-first / deterministic-routing fast pipeline, why it exists, how it works |
| [`KG_VIEW.md`](KG_VIEW.md) | Knowledge graph viewer service |
| [`KG_OPTIMIZATION_IMPLEMENTATION.md`](KG_OPTIMIZATION_IMPLEMENTATION.md) | Graph-side performance work |
| [`KG_VIEW_OPTIMIZATION_PRODUCTION_GUIDE.md`](KG_VIEW_OPTIMIZATION_PRODUCTION_GUIDE.md) | Operating the KG view in production |
| [`CURATOR_OPTIMIZATION.md`](CURATOR_OPTIMIZATION.md) | Curator service scheduling and ranking |
| [`CREATOR_AGENT_ORACLE_INTEGRATION.md`](CREATOR_AGENT_ORACLE_INTEGRATION.md) | How creator agents talk to the oracle |
| [`INTELLIGENT_NO_RESULTS_HANDLING.md`](INTELLIGENT_NO_RESULTS_HANDLING.md) | Behaviour when a query returns nothing |

## Operations

| Doc | Covers |
|---|---|
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | AWS EC2 deployment guide |
| [`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md) | Initial production install |
| [`DEPLOYMENT_COMPLIANCE.md`](DEPLOYMENT_COMPLIANCE.md) | Compliance-tracking for deployments |
| [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) | Common failure modes and fixes |
| [`QUICKSTART.md`](QUICKSTART.md) | Local-dev quick start |

## Teams integration

| Doc | Covers |
|---|---|
| [`TEAMS_IT_ADMIN_GUIDE.md`](TEAMS_IT_ADMIN_GUIDE.md) | Full IT/AAD admin guide — bot setup, SSO, agents, proactive messaging |
| [`TEAMS_AGENT_PERSONAS.md`](TEAMS_AGENT_PERSONAS.md) | How creator agents appear as named Teams identities |
| [`TEAMS_SHOWCASE.md`](TEAMS_SHOWCASE.md) | Five real-world use cases with under-the-hood detail |
| [`TEAMS_STATUS_BRIEF.md`](TEAMS_STATUS_BRIEF.md) | Status brief for project sponsors |
| [`demo/IT_PERMISSIONS_REQUEST.md`](demo/IT_PERMISSIONS_REQUEST.md) | Tight escalation note for the initial IT provisioning ask |

## Demo and launch — `demo/`

The Monday 2026-05-18 demo + end-of-week launch pack. Index: [`demo/README.md`](demo/README.md).

## IT / security — `IT/`

Pre-existing security and architecture briefs for corporate IT. Index: [`IT/README.md`](IT/README.md).

## Diagrams — `drawings/`

| File | Purpose |
|---|---|
| `architecture-overview.xml` | Current system architecture (draw.io) |
| `observability-stack.drawio` | Grafana / Tempo / Loki / Prometheus stack |
| `presentation-final.xml` | Canonical presentation deck draw.io source |

Earlier iterations are preserved in `drawings/archive/`.

## Legal

| Doc | Covers |
|---|---|
| [`AI_CODE_PROVENANCE.md`](AI_CODE_PROVENANCE.md) | Aurora's AI-assisted code attribution policy |
| [`NOTICE`](NOTICE) | Standard NOTICE file |
| [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) | Third-party dependency licences |

## Archive — `archive/`

Historical records that are no longer load-bearing but worth keeping accessible:

- `archive/features/` — 18 dated implementation logs from Nov 2025–Jan 2026 (`Feat<YYMMDD>_*.md`). The code has moved on; these capture the rationale at the time.
- `archive/strategy/` — strategic decision records (`Strat<YYMMDD>_*.md`).
- `archive/TEAMS_INTEGRATION_SUMMARY.txt` — March 2026 Teams-integration completion summary.

If you find yourself frequently consulting an archived file, that's a signal to promote it back to a live doc and update it.

## Conventions

- **Living docs use `SCREAMING_SNAKE_CASE.md` at the top level.** Reflects the existing repo convention; not worth churning all the inbound references to change it.
- **Dated logs use `Type<YYMMDD>_topic.md`** in `archive/` — `Feat` for feature implementation logs, `Strat` for strategy decisions.
- **Add a row to this index** when you create a new top-level doc, so newcomers can find it.
