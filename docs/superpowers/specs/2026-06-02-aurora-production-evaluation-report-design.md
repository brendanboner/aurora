# Aurora Production Evaluation Report — Design

**Date:** 2026-06-02
**Owner:** bbonner
**Status:** Draft (brainstorm output, pending review)

## Goal

Produce a one-shot evaluation report on the Aurora production system using existing telemetry, supplemented narrowly where the data is missing. The report must give a credible picture of: knowledge-graph utilization, retrieval accuracy/quality, LLM efficiency for both document processing and request handling, and the relative performance of the KG-first ("fast") pipeline vs. the baseline RAG pipeline.

Audience: hybrid — 1-page executive summary at the top, full technical detail in appendices.

## Non-goals

- No recurring/monthly evaluation harness (defer to a follow-up if the one-shot proves worth recurring).
- No golden-answer corpus authored by domain experts. Correctness is measured via LLM-as-judge on the existing query history.
- No longitudinal "system improved over time" trend story — the report is a snapshot, not a time-series.
- No changes to the production system other than (a) read-only queries and (b) one optional Cypher read script.

## Data sources

| Source | Use |
|---|---|
| Postgres `oracle_query_history` | Per-query truth: question, intent, route plan, strategies, documents, answer, confidence, latency, tokens, cache, feedback |
| Postgres `chat_conversations` + `chat_messages` | Session-level patterns (conversation length, abandonment proxy) |
| Postgres `user_feedback` | Free-form user feedback (bugs, usability) |
| Prometheus scrape | Rate calculations, histograms confirmed against DB |
| Loki query | Digester throughput, LLM call durations not in `oracle_query_history`, error patterns |
| Neo4j | Point-in-time corpus snapshot via one read-only Cypher batch |
| `eval_results.txt` (2026-05-14) | Historical reference point only; not relied on for current numbers |

All Postgres + Neo4j data is **exported to a local snapshot** (parquet/CSV for Postgres, JSON for Neo4j counts) before analysis. After the dump, the report builds entirely offline. No iterative load on prod.

## Architecture

Two artifacts, both checked into the repo:

1. **`eval/aurora_eval/`** — a small Python package + Jupyter notebook for reproducibility.
   - `dump.py` — pulls Postgres tables to local parquet, runs Neo4j read-only Cypher, captures a Prometheus snapshot, tails Loki for digester stats over the report window.
   - `judge.py` — runs the LLM-as-judge on a stratified sample of ~100 queries pulled from the dump.
   - `analyze.ipynb` — the notebook that produces every chart and number in the report. Reads only from the local dump.
   - `charts/` — output directory for SVG/PNG embedded in the report.
2. **`docs/aurora-production-evaluation-2026-06-02.md`** — the report itself. Markdown with embedded charts, written so it renders cleanly on GitHub.

### Data flow

```
prod Postgres ──┐
prod Neo4j  ────┼──► dump.py ──► eval/data/*.parquet, *.json
Prometheus  ────┤
Loki        ────┘                       │
                                        ▼
                              judge.py (LLM-as-judge)
                                        │
                                        ▼
                          eval/data/judgements.parquet
                                        │
                                        ▼
                              analyze.ipynb ──► docs/...md + charts/*.svg
```

## Report structure

### Executive summary (1 page)

- 5–7 headline numbers (query volume, p95 latency, cache hit rate, feedback ratio, fast-vs-baseline cost delta, judge faithfulness score, KG node count).
- One paragraph on the KG-vs-RAG verdict: does the fast pipeline pay for itself in latency/cost without giving up answer quality?
- One paragraph on limitations (no ground truth; LLM-judge has known biases; sample size implications).

### Section 1 — Operational health

- Query volume over the window (per day).
- Latency p50/p95/p99, broken down by pipeline (fast/baseline) and by intent.
- Error rate + top error types (from `oracle_query_history.error_message`).
- Cache hit rate with 3-tier breakdown (plan / result / answer caches from `request_options.cache`).

### Section 2 — KG vs RAG head-to-head

The system's core design bet. For matched intent buckets, compare fast vs. baseline on:

- Latency distributions.
- Tokens per query (LLM cost proxy).
- Confidence score distribution.
- User feedback ratio.
- LLM-judge correctness scores.

If a Mann–Whitney U or t-test is appropriate per metric, run it and report p-values — but lead with effect sizes, not p-values.

### Section 3 — LLM efficiency

- Tokens by `prompt_type` (intent classification, route plan, answer synthesis, summarization, etc.) — from Loki structured logs.
- Tokens by model.
- $ estimate using current Azure OpenAI pricing for the model(s) in use. Cite the pricing source date.
- Per-stage cost breakdown of a typical query — what does answering one question actually cost?

### Section 4 — Document processing efficiency

- Digester throughput (docs/hour) over the window.
- DLQ rate + failure mode breakdown.
- Tokens spent per document ingested (if visible in logs).
- Neo4j growth across the window if any timestamp field allows it; otherwise just a single snapshot.

### Section 5 — Knowledge graph utilization

- Neo4j corpus snapshot: nodes by label, edges by type, orphan-node count.
- Route template hit distribution: which `route_id` values fire most, which never fire (dead routes).
- Citation density: average citations per answer, per pipeline.
- Coverage gap signal: queries that fell back from fast→baseline, broken down by intent.

### Section 6 — User satisfaction

- 👍/👎 ratio over the window.
- Confidence-vs-feedback correlation: do high-confidence answers actually get more 👍?
- Theme extraction from `feedback_comment` text (light NLP — top n-grams or LLM clustering).

### Section 7 — Correctness (LLM-as-judge)

#### Sample selection

- Pull all queries in the report window from `oracle_query_history`.
- Stratify by (pipeline ∈ {fast, baseline}) × top 5 intents.
- Sample ~10 per stratum, target ~100 queries total. Reject queries with empty answers or errors.

#### Rubric (per query)

LLM judge (claude-opus-4-7 or claude-sonnet-4-6, configurable; defaults to opus for the report) scores 0–5 on each of:

1. **Faithfulness** — is the answer supported by the cited documents?
2. **Relevance** — does the answer address the user's question?
3. **Hallucination flag** (boolean) — does the answer contain a specific claim not in the cited docs?
4. **Citation usefulness** — would the cited docs actually help a reader verify the answer?

Each score includes a 1-line rationale stored alongside.

#### Reporting

- Mean + 95% CI per rubric dimension, broken down by pipeline.
- Hallucination rate per pipeline.
- 5 example queries per pipeline (highest- and lowest-scored) included verbatim in an appendix.

### Appendix A — Methodology and caveats

- Data window, row counts, why this window was chosen.
- Sampling strategy and what it does/doesn't generalize to.
- LLM-judge model, prompt, known biases (judges tend to over-score verbose answers; we mitigate by including the rubric explicitly).
- Pricing source for cost estimates.
- Reproducibility: how to re-run the notebook against a fresh dump.

### Appendix B — Glossary

Fast pipeline, baseline pipeline, route plan, intent, confidence score, cache tiers — short definitions for non-engineering readers.

### Appendix C — Raw tables

Per-intent breakdowns, per-route_id breakdowns, full judge sample with scores.

## Implementation plan summary

Roughly 1.5–2 days of work, in this order:

1. **Scout** — run a small query against prod Postgres to confirm row counts, date range, feedback volume. Decide the report window based on what's there (likely full history; fall back to last 30 days if early data is noisy).
2. **Dump** — `dump.py` produces the local snapshot.
3. **Build the notebook** — sections 1–6 in `analyze.ipynb`, all reading from the local dump.
4. **LLM-as-judge** — `judge.py` runs the rubric on the stratified sample. ~$5–10 spend.
5. **Write the report** — pull numbers and charts from the notebook into the markdown report.
6. **Self-review the report** — sanity check all numbers, ensure no claim outruns the data, confirm caveats section is honest.

## Risk and mitigation

- **Risk:** LLM-judge bias produces inflated correctness scores. *Mitigation:* publish the prompt and rubric; include human-verifiable example pairs in the appendix; mark every correctness number as "judge-scored, not human-validated."
- **Risk:** Snapshot-based numbers misrepresent live state if the system is currently changing fast. *Mitigation:* report a clear snapshot timestamp and note that all numbers refer to that window.
- **Risk:** Production access drift (Postgres credentials, SSM connectivity). *Mitigation:* surface this in step 1 and resolve before doing analysis work.
- **Risk:** Sensitive content in user questions / feedback. *Mitigation:* before publishing, scan the appendix for PII or proprietary content and redact. The report itself only contains aggregates and selected sanitized examples.

## Open questions to resolve during implementation

- Exact date range to pull (decide after scout).
- Which Azure OpenAI model(s) are actually in use right now → confirms pricing rows.
- Whether `feedback_comment` contains enough content to do theme extraction, or whether that section drops to "n was too small to analyze."
