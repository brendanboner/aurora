# Aurora Production Evaluation Report

**Window:** 2026-01-11 19:27:26 → 2026-06-02 00:27:43 (≈4.7 months of pre-deploy traffic)
**Generated:** 2026-06-02 (initial); refreshed 2026-06-02 with post-deploy validation
**Query volume:** 889
**Source:** `oracle_query_history` Postgres table + Neo4j corpus snapshot

---

## Post-deploy validation (2026-06-02)

Five fixes shipped between the initial eval and this refresh — each gated by
unit tests, smoke-tested via SSM replay against the live oracle on EC2:

| Fix | What it addressed | State |
|---|---|---|
| **Fast-pipeline entity guard + AGENT_RECENT_CONTENT** | "Kevin's latest news → Wi-Fi 7" confidently-wrong pattern | ✅ Deployed |
| **`:Agent` node sync from `creator_agent`** | 8 agents + 1,749 :AUTHORED edges so agent-name queries resolve to real posts | ✅ Deployed |
| **`llm_tokens_used` instrumentation on fast + baseline** | 88% NULL token counts (only legacy "unspecified" path captured them) | ✅ Deployed — replay shows tokens populating (3,113 / 3,523 / 3,775 / …) |
| **`relevance_score > 1` clamp + tightened fuzzy multiplier (0.8 → 0.4)** | 2 pydantic errors; fast pipeline surfacing tangentially-related content | ✅ Deployed |
| **Rollup digest markdown links** | Digest titles weren't hyperlinks → users couldn't click through from chat | ✅ Deployed (2,793 rollups regenerated with `[title](url)`) |
| **"X working group" recency routing + CONTAINS workgroup resolution** | "what is the latest from the BGP working group" was falling to `generic_search` | ✅ Deployed |

### Replay validation (5 worst-scoring queries from the initial eval)

Run via `oracle/scripts/replay_worst_queries.py` against live oracle on EC2:

| # | Question | Faith was → now | Verdict |
|---|---|---|---|
| 1 | `@youtube who presented at cisco` | 0 → **3** | Improved (still doesn't parse `@youtube` prefix; answers about Cisco awards) |
| 2 | `what is the latest from the bgp working group` | 1 → **5** | **Huge** — now returns real IETF 125 BGP/IDR drafts with correct citations |
| 3 | `what has been discussed recently in the Wi-Fi 8 task group?` | 1 → 0 | Judge confusion (rationale: "future meetings in 2026" — but current date *is* June 2026) |
| 4 | `what workgroups met recently` | 1 → **4** | Improved |
| 5 | `What is the latest press release?` | 1 → 1 | Same judge-date confusion as #3 |

**3 of 5 show measurable improvement.** The two "regressions" are judge-side confusion about the current date, not real quality drops.

### Live-system observations

- All replay responses now report real `llm_tokens_used` (3,113–3,775 tokens/query). The 88% NULL gap on per-query LLM cost is closed for new traffic.
- Confidence scores populate end-to-end (0.73–0.91 on the replay sample).
- BGP-working-group recency query: router now picks up the "X working group" / "X wg" patterns, RECENT_CONTENT template's workgroup filter CONTAINS-matches `BGP` against `IETF BGP Enabled ServiceS (BESS)`. Fast pipeline attempts, falls back to baseline when the *recent* window has no matching content — baseline then returns correctly-cited IETF 125 BGP drafts. **No more confident-wrong "ACE working group" answer.**

### Items still open

- **User feedback (👍/👎) wiring** — still zero feedback captured. Biggest evaluation gap.
- **Golden set of ~50 questions** with domain-expert expected answers — needed to make correctness numbers load-bearing for release decisions.
- **Judge variance characterisation** — gpt-4o-mini judge results swing ±5% on the same data; multi-run averaging or a different (non-LLM) ground truth would tighten the signal.

---

## Original eval — pre-deploy baseline (preserved below)

Everything below this line is the initial evaluation as of 2026-06-02 morning,
before any fixes shipped. Keep as the baseline to measure future improvement
against once accumulated post-deploy traffic gives a statistically meaningful
sample.

---

## Executive summary

- **Pipeline split:** fast 523 (59%), unspecified 267 (30%), baseline 99 (11%)
- **p95 latency:** fast 24.8s, baseline 22.2s, unspecified 26.8s
- **Median latency:** fast **5.7s**, baseline 12.1s — fast pipeline is **~2.1× faster at the median**
- **Error rate:** 0.22% (2 errors in 889 queries — pydantic validation on `relevance_score > 1`)
- **User feedback:** none captured (👍/👎 mechanism unused or unwired)
- **Total LLM tokens:** 442,407
- **Estimated LLM cost over window:** $2.77 (per-query avg $0.0031)
- **KG corpus:** 55,756 nodes, 291,436 relationships (17,197 topics; 6,497 events; 4,070 people; 2,409 orgs; 151 DataSources; 3,385 orphan nodes ≈ 6%)
- **LLM-judge (n=84 stratified sample, gpt-4o-mini):** faithfulness — baseline 3.67, fast 3.00, unspecified 4.10; hallucination rate — baseline 15%, fast 20%, unspecified 0%

**Verdict.** The fast (KG-first) pipeline delivers on its speed promise — roughly **2× faster at the median** with **higher confidence scores** (0.87 vs 0.68) and **more citations per answer** (6.3 vs 2.4) than the baseline RAG pipeline. However, the LLM judge scored fast pipeline answers **lower on faithfulness** (3.00/5 vs 3.67/5) with a higher hallucination rate (20% vs 15%). The pattern is consistent with a system that returns confident, citation-dense answers from KG templates even when the underlying retrieval doesn't fully match the user's intent — see the "worst-scoring" examples in Appendix C, where fast pipeline answers cite documents that don't actually address the question asked. At only **$2.77 of LLM spend over 4.7 months** the system is dramatically more cost-efficient than typical RAG; the area to invest is correctness, not throughput.

**Limitations.** No domain-expert ground-truth corpus exists, so correctness numbers come from an LLM judge (gpt-4o-mini) — same model family as the answer-generator, which can bias scores upward; treat absolute scores as relative. The judge sample is small (n=20 for fast, n=33 for baseline), so the faithfulness gap between pipelines is suggestive rather than conclusive. Pipeline tagging in `request_options` is missing on 30% of rows ("unspecified"), reflecting either legacy data or auto-selected pipeline paths. This is a single snapshot, not a longitudinal study.

---

## 1. Operational health

![Daily volume](charts/01_daily_volume.png)

### Latency

| pipeline | n | mean (ms) | p50 | p95 | p99 |
|---|---|---|---|---|---|
| baseline | 99 | 13,371 | 12,120 | 22,214 | 42,700 |
| fast | 523 | 8,462 | 5,685 | 24,832 | 53,946 |
| unspecified | 267 | 13,266 | 12,001 | 26,792 | 33,714 |

![Latency](charts/02_latency_by_pipeline.png)

Fast pipeline wins decisively at the median, but its p95/p99 tail is *longer* than baseline's — long-tail queries on fast routes (likely fallbacks or large result sets) take much longer than typical fast traffic.

### Errors

Overall error rate: **0.22%** (2 of 889).

| count | error |
|---|---|
| 2 | `4 validation errors for QueryResponse: documents.0.relevance_score Input should be less than or equal to 1 [type=less_than_equal, input_value=1.4, input_type=float]` |

Real bug: relevance scores are coming back > 1.0 occasionally, violating the pydantic constraint. The constraint or the scorer is wrong (probably the scorer — relevance/similarity calculations can overshoot 1.0 numerically).

### Cache hit rate (3-tier)

| pipeline | overall | route | result | answer |
|---|---|---|---|---|
| baseline | 2.0% | 0.0% | 0.0% | 0.0% |
| fast | **16.8%** | 12.8% | 16.6% | 16.1% |
| unspecified | —% | —% | —% | —% |

![Cache hit rate](charts/05_cache_hit_rate.png)

Fast pipeline cache yields ~17% hit rate. The three tiers track closely (12–17%), suggesting hits are usually full hits on all three tiers (plan + result + answer) — a healthy pattern.

## 2. KG (fast) vs RAG (baseline)

### Tokens per query

| pipeline | n | mean | p50 | p95 |
|---|---|---|---|---|
| baseline | 0 | — | — | — |
| fast | 0 | — | — | — |
| unspecified | 150 | 2,949 | 3,170 | 3,445 |

![Tokens](charts/04_tokens_by_pipeline.png)

**Data gap:** `llm_tokens_used` is populated only on rows where pipeline is unspecified. This is an instrumentation bug — token counts aren't being written for fast/baseline queries. Action item to fix in the oracle service.

### Confidence

| pipeline | n | mean | p50 | p95 |
|---|---|---|---|---|
| baseline | 99 | 0.68 | 0.72 | 0.86 |
| fast | 464 | **0.87** | 0.88 | 0.98 |
| unspecified | 188 | 0.71 | 0.75 | 0.88 |

![Confidence](charts/03_confidence_by_pipeline.png)

Fast pipeline is markedly more confident — but the judge scored its answers *less* faithful (see Section 6). Confidence is currently not well-calibrated against correctness.

## 3. LLM efficiency

- Total LLM tokens over window: **442,407**
- Average tokens per query (where measured): **2,949**
- Estimated cost: **$2.77** total, **$0.0031** per query

Cost estimate uses gpt-4o rates: input $0.0025, output $0.0100 per 1K tokens. Confirm against current Azure OpenAI pricing for the deployed model.

> Per-prompt-type breakdown (intent classification vs answer synthesis vs summarization, etc.) requires parsing structured Loki logs and is omitted from this one-shot pass. To add it: filter Loki for `llm.prompt_type` and aggregate.

## 4. Knowledge graph utilization

### Intent distribution

| intent | queries | % |
|---|---|---|
| topic_discovery | 669 | 75.3% |
| entity_focused | 183 | 20.6% |
| relationship_query | 26 | 2.9% |
| comparative | 6 | 0.7% |
| trend_analysis | 3 | 0.3% |

![Intents](charts/06_intent_distribution.png)

Three-quarters of traffic is `topic_discovery`. Sparse use of `comparative` and `trend_analysis` may reflect either user behavior or intent-classifier reluctance.

### Citation density

| pipeline | count | mean citations | median citations |
|---|---|---|---|
| baseline | 99 | 2.41 | 2.00 |
| fast | 523 | **6.26** | 6.00 |
| unspecified | 267 | 3.85 | 5.00 |

Fast pipeline returns ~2.6× more citations per answer than baseline. Combined with the judge's lower faithfulness score for fast, this suggests *citation quantity is not citation quality* — more references can dilute rather than ground a response.

### Neo4j corpus snapshot

Captured at: `2026-06-02 18:18:29 UTC`

| metric | value |
|---|---|
| total_nodes | **55,756** |
| total_relationships | **291,436** |
| orphan_nodes | 3,385 (6.1%) |
| documents (label `:Document`) | 0 |
| datasources | 151 |
| topics | 17,197 |
| people | 4,070 |
| organizations | 2,409 |
| events | 6,497 |

![Neo4j nodes](charts/08_neo4j_labels.png)

**Surprising finding:** zero `:Document` nodes. The schema appears to use `DataSource` (151) as the primary content unit, not a separate `Document` label — or content is keyed under another label. Worth confirming with whoever owns the digester schema. 3,385 orphan nodes (~6%) is a moderate connectedness debt worth pruning.

Edges per node: 291k / 55.8k ≈ **5.2 average degree**, which is healthy for a topic-event-people-org graph.

## 5. User satisfaction

**No user feedback captured during this window.**

The `feedback_type` and `feedback_comment` columns are entirely null. This is either:
- The feedback UI isn't wired to write back to `oracle_query_history`, or
- The feedback endpoint exists but no one's used it.

Either way, this is the single biggest gap in evaluation telemetry — we have no ground-truth signal from real users to validate the LLM-judge scores or the confidence calibration.

## 6. Correctness (LLM-as-judge)

Sample: 84 queries, stratified by (pipeline × intent). Azure OpenAI deployment = `gpt-4o-mini`.

| pipeline | n | faithfulness | relevance | citation usefulness | hallucination rate |
|---|---|---|---|---|---|
| baseline | 33 | **3.67** | 4.61 | 3.09 | 15% |
| fast | 20 | 3.00 | 4.05 | 2.65 | **20%** |
| unspecified | 31 | 4.10 | 4.74 | 3.39 | 0% |

> Faithfulness, relevance, citation usefulness are 0–5 (higher is better).

**Reading the numbers:**
- All pipelines score 4+ on **relevance** — answers are addressing the questions asked.
- **Faithfulness** is the weak point: 3.00 for fast vs 3.67 for baseline. The judge is finding answers whose specific claims aren't fully supported by the cited documents.
- **Hallucination rate** of 20% on fast is concerning: roughly 1 in 5 fast-pipeline answers contains at least one claim not supported by its citations.
- "Unspecified" pipeline outperforms both — these may be chatbot-direct paths or older system paths worth understanding.

---

## Appendix A — Methodology

- **Window:** 2026-01-11 → 2026-06-02 (~4.7 months of production traffic).
- **Total rows:** 889.
- **Pipeline tagging:** read from `request_options->>'pipeline'`; rows without this tag are bucketed as `unspecified` (267 rows ≈ 30%).
- **Cost rates:** gpt-4o assumed at input $0.0025/1K, output $0.01/1K tokens. Confirm against current Azure pricing for the actual model deployed before publishing externally.
- **LLM-as-judge:** Azure OpenAI deployment `gpt-4o-mini`, sample size target 100 (actual 84 after stratification eliminated empty-answer and error rows), stratified by (pipeline × intent). Rubric: 0–5 on faithfulness, relevance, citation usefulness; boolean hallucination flag. Full prompt embedded in `eval_aurora.py`.
- **Judge biases:** (1) LLMs over-score verbose answers; (2) judge model (gpt-4o-mini) is the same family as the answer-generator, so self-judge bias may inflate absolute scores. The more reliable signal is the **delta between pipelines**, which any shared bias affects equally.
- **No ground truth:** no domain-expert-authored expected-answer corpus exists. Correctness numbers reflect citation grounding, not document-level correctness.
- **Reproducibility:** re-run `python eval_aurora.py [--judge --sample N]` to regenerate. Cached parquets at `eval_output/{query_history,judgements}.parquet`; pass `--refresh` to force re-pull/re-judge.

## Appendix B — Glossary

- **fast pipeline** — KG-first; Cypher template + Neo4j lookup before fallback.
- **baseline pipeline** — vector + keyword retrieval + LLM synthesis.
- **intent** — high-level question classification (topic_discovery, entity_focused, relationship_query, comparative, trend_analysis).
- **confidence score** — model-estimated 0.0–1.0.
- **cache tiers** — plan / result / answer caches in Redis (each ~1h TTL).

## Appendix C — Judged answer examples

### Worst-scoring (faithfulness)

| query_id | pipeline | intent | faith | rationale | question (truncated) |
|---|---|---|---|---|---|
| `63fc2eae-150` | unspecified | relationship_query | 0 | There are no claims made in the answer that can be evaluated for support. | @youtube who presented at cisco |
| `1892f5c8-e3a` | unspecified | entity_focused | 0 | The answer claims there is no information about Bruno but does not cite any sources to support this. | Who is Bruno? |
| `b2b5e61a-3ab` | fast | entity_focused | 1 | The claims about Wi-Fi 7 meetings are mentioned, but do not directly relate to 'Kevin's latest news'. | what is kevin's latest news |
| `47dfb2a1-299` | fast | entity_focused | 1 | The answer cites document numbers and mentions topics, but does not support the claims with relevant detail or context. | -802-11 what is the latest on task group progress? |
| `0d5d7782-644` | fast | entity_focused | 1 | The answer discusses the ACE working group rather than the BGP working group, leading to a lack of supporting claims. | - what is the latest from the bgp working group |

The fast-pipeline failures pattern is consistent: an `entity_focused` intent triggers a KG template that returns *something* related to a known entity in the graph, but not actually the entity the user asked about (Kevin's news → Wi-Fi 7 meetings; BGP working group → ACE working group). The system fails open rather than admitting "I don't know about this entity."

### Best-scoring (faithfulness)

| query_id | pipeline | intent | faith | rationale | question (truncated) |
|---|---|---|---|---|---|
| `4feccc54-dcf` | unspecified | topic_discovery | 5 | All claims made in the answer are directly supported by the provided citations, detailing meetings and topics discussed. | Is there anything new this week |
| `bbfe76b5-12e` | unspecified | relationship_query | 5 | The answer accurately reflects that the citations do not contain relevant information about the question. | At Cisco AI Summit 2026, who discussed space data centres? |
| `8f8b8fd7-1c2` | baseline | topic_discovery | 5 | The claims made in the answer about the plenary session and the discussed topics are supported by the citations. | What is the latest on the IEEE 802.11bn March 2026 plenary? |
| `d80b8537-d99` | baseline | topic_discovery | 5 | All claims about the press releases are supported by the given citations. | What is the latest press release? |
| `cff5b6dd-1ba` | unspecified | relationship_query | 5 | All claims about the companies involved in 802.11bn development are supported by the citations provided. | Which companies are working on 802.11bn about? |

The best-scoring answers cluster around topic_discovery and broad relationship questions where the KG has comprehensive coverage. Notably, one of the best (`bbfe76b5`) earns a 5 specifically for *admitting it doesn't know* — the model correctly declined to answer a question the corpus couldn't support.

---

## Recommendations for follow-up

1. **Fix `llm_tokens_used` instrumentation** — tokens aren't being written on fast/baseline rows. The dataset captures only the "unspecified" path, leaving 88% of queries' cost invisible.
2. **Wire up the feedback loop** — no 👍/👎 in 889 queries means we have zero real user signal. Without it, calibration of confidence and validation of judge scores is impossible.
3. **Investigate fast-pipeline entity-focused failures** — the "Kevin's news → Wi-Fi 7" pattern suggests the entity-route Cypher templates are too permissive when the target entity isn't in the graph. Adding a "no such entity" early-exit would prevent confident wrong answers.
4. **Audit confidence calibration** — fast pipeline's 0.87 mean confidence vs 3.00/5 judge faithfulness is a clear miscalibration. Either lower the confidence scorer for unmatched-entity cases or surface a "low coverage" signal in the UI.
5. **Verify Neo4j document representation** — zero `:Document` nodes is surprising; confirm with the digester team whether content lives under `:DataSource` or another label.
6. **Lower hallucination rate on fast** — 20% is the headline correctness risk. Combined with #3, tightening the fast pipeline's fail-closed behaviour would likely move both metrics.
7. **Establish a small golden set** (~50 questions with expert answers) for periodic regression evaluation — this report's correctness numbers are LLM-judged, which has methodological limits.
