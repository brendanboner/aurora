# Aurora Production Evaluation Report

**Window:** 2026-01-11 19:27:26.649554 → 2026-06-02 00:27:43.693871  
**Generated:** 2026-06-02  
**Query volume:** 889  
**Source:** `oracle_query_history` Postgres table + Neo4j corpus snapshot

---

## Executive summary

- **Pipeline split:** fast: 523, unspecified: 267, baseline: 99
- **p95 latency:** fast = 24832 ms, baseline = 22214 ms
- **Error rate:** 0.22%
- **User feedback:** none captured in the window
- **Total LLM tokens:** 442,407
- **Estimated LLM cost over window:** $2.77 (per-query avg $0.0031, see methodology)
- **KG corpus:** 57,513 nodes / 293,185 relationships; resources=23,493; agents=8
- **LLM-judge (baseline):** faithfulness 3.52, relevance 4.61, hallucination rate 24% (n=33)
- **LLM-judge (fast):** faithfulness 3.40, relevance 4.15, hallucination rate 5% (n=20)
- **LLM-judge (unspecified):** faithfulness 4.16, relevance 4.77, hallucination rate 3% (n=31)

**Verdict.** _Fill in 2–3 sentences based on the numbers above. Suggested framing: did the fast/KG pipeline meaningfully reduce latency or token cost vs. baseline at comparable correctness?_

**Limitations.** No domain-expert ground-truth corpus exists; correctness numbers are LLM-judge scored (claude-opus-4-7 by default) and should be read as relative, not absolute. All numbers are a single snapshot over the window above; this is not a longitudinal trend report.

---

## 1. Operational health

![Daily volume](charts/01_daily_volume.png)

### Latency

| pipeline | n | mean (ms) | p50 | p95 | p99 |
|---|---|---|---|---|---|
| baseline | 99 | 13371 | 12120 | 22214 | 42700 |
| fast | 523 | 8462 | 5685 | 24832 | 53946 |
| unspecified | 267 | 13266 | 12001 | 26792 | 33714 |

![Latency](charts/02_latency_by_pipeline.png)

### Errors

Overall error rate: **0.22%**

Top error messages:

| count | error |
|---|---|
| 2 | `4 validation errors for QueryResponse
documents.0.relevance_score
  Input should be less than or equal to 1 [type=less_than_equal, input_value=1.4, input_type=float]
    For further information visit ` |

### Cache hit rate (3-tier)

| pipeline | overall | route | result | answer |
|---|---|---|---|---|
| baseline | 2.0% | 0.0% | 0.0% | 0.0% |
| fast | 16.8% | 12.8% | 16.6% | 16.1% |
| unspecified | —% | —% | —% | —% |

![Cache hit rate](charts/05_cache_hit_rate.png)

## 2. KG (fast) vs RAG (baseline)

### Tokens per query

| pipeline | n | mean | p50 | p95 |
|---|---|---|---|---|
| baseline | 0 | — | — | — |
| fast | 0 | — | — | — |
| unspecified | 150 | 2949 | 3170 | 3445 |

![Tokens](charts/04_tokens_by_pipeline.png)

### Confidence

| pipeline | n | mean | p50 | p95 |
|---|---|---|---|---|
| baseline | 99 | 0.68 | 0.72 | 0.86 |
| fast | 464 | 0.87 | 0.88 | 0.98 |
| unspecified | 188 | 0.71 | 0.75 | 0.88 |

![Confidence](charts/03_confidence_by_pipeline.png)

## 3. LLM efficiency

- Total LLM tokens over window: **442,407**
- Average tokens per query: **2949**
- Estimated cost: **$2.77** total, **$0.0031** per query

Cost estimate uses rates: input $0.0025, output $0.0100 per 1K tokens (placeholder — confirm against Azure OpenAI pricing for the deployed model).

> Per-prompt-type breakdown requires parsing structured Loki logs and is omitted from this one-shot script. To add it, follow the methodology section: filter Loki for `llm.prompt_type` and aggregate.

## 4. Knowledge graph utilization

### Intent distribution

| intent | queries |
|---|---|
| topic_discovery | 669 |
| entity_focused | 183 |
| relationship_query | 26 |
| comparative | 6 |
| trend_analysis | 3 |

![Intents](charts/06_intent_distribution.png)

### Citation density

| pipeline | count | mean citations | median citations |
|---|---|---|---|
| baseline | 99 | 2.41 | 2.00 |
| fast | 523 | 6.26 | 6.00 |
| unspecified | 267 | 3.85 | 5.00 |

### Neo4j corpus snapshot

Captured at: `2026-06-02T21:30:38.130894+00:00`

| metric | value |
|---|---|
| total_nodes | 57,513 |
| total_relationships | 293,185 |
| orphan_nodes | 3,385 |
| resources | 23,493 |
| ingestion_batches | 3,687 |
| datasources | 151 |
| topics | 17,197 |
| people | 4,070 |
| organizations | 2,409 |
| events | 6,497 |
| agents | 8 |

![Neo4j nodes](charts/08_neo4j_labels.png)

## 5. User satisfaction

No user feedback captured during this window.

## 6. Correctness (LLM-as-judge)

Sample: stratified by (pipeline × intent), Azure OpenAI deployment = `gpt-4o-mini`.

| pipeline | n | faithfulness | relevance | citation usefulness | hallucination rate |
|---|---|---|---|---|---|
| baseline | 33 | 3.52 | 4.61 | 3.03 | 24% |
| fast | 20 | 3.40 | 4.15 | 2.70 | 5% |
| unspecified | 31 | 4.16 | 4.77 | 3.42 | 3% |

> Faithfulness, relevance, citation usefulness are 0–5 (higher is better).

---

## Appendix A — Methodology

- **Window:** 2026-01-11 19:27:26.649554 → 2026-06-02 00:27:43.693871
- **Total rows:** 889
- **Pipeline tagging:** read from `request_options->>'pipeline'`; rows without this tag are bucketed as `unspecified`.
- **Cost rates (placeholder):** input $0.0025/1K, output $0.01/1K tokens. Verify against the current Azure OpenAI pricing for the deployed model before publishing.
- **LLM-as-judge:** Azure OpenAI deployment `gpt-4o-mini`, sample size 100, stratified by (pipeline × intent). Rubric: 0–5 on faithfulness, relevance, citation usefulness; boolean hallucination flag. Full prompt embedded in `eval_aurora.py`.
- **Judge biases:** (1) LLMs tend to over-score verbose answers; (2) judge and answer-generator share the same model family (gpt-4o), so self-judge bias may inflate scores. Treat absolute numbers as relative; the more useful signal is the *delta between pipelines*, which any shared bias cancels out.
- **No ground truth:** there is no domain-expert-authored expected-answer corpus. Correctness numbers reflect citation grounding, not document correctness.
- **Reproducibility:** re-run `python eval_aurora.py [...]` to regenerate. Charts in `eval_output/charts/`.

## Appendix B — Glossary

- **fast pipeline** — KG-first; Cypher template + Neo4j lookup before fallback.
- **baseline pipeline** — vector + keyword retrieval + LLM synthesis.
- **intent** — high-level question classification (FACTUAL, ANALYTICAL, COMPARATIVE, TEMPORAL, ENTITY).
- **confidence score** — model-estimated 0.0–1.0.
- **cache tiers** — plan / result / answer caches in Redis (each ~1h TTL).

## Appendix C — Judged answer examples (PII-scrubbed)

### Worst-scoring (faithfulness)

| query_id | pipeline | intent | faith | rationale | question (truncated) |
|---|---|---|---|---|---|
| `63fc2eae-150` | unspecified | relationship_query | 0 | The answer does not provide any claims that can be supported by citations. | @youtube who presented at cisco |
| `0d5d7782-644` | fast | entity_focused | 1 | The answer discusses the ACE working group rather than the BGP working group, which is unrelated. | - what is the latest from the bgp working group |
| `f6f5df31-f8a` | fast | topic_discovery | 1 | The claims about discussions and features of Wi-Fi 8 are not supported by available citations. | what has been discussed recently in the Wi-Fi 8 task group? |
| `215166b7-b67` | baseline | entity_focused | 1 | The answer mentions a date in the future and does not provide relevant claims about workgroups, contradicting the citations. | what workgroups met recently |
| `654b34bb-4d0` | baseline | topic_discovery | 1 | The claims about the awards and their recipients are stated, but the citations do not confirm that they are all accurately represented as 'latest' press release | What is the latest press release? |

### Best-scoring (faithfulness)

| query_id | pipeline | intent | faith | rationale | question (truncated) |
|---|---|---|---|---|---|
| `7937056c-778` | fast | entity_focused | 5 | The answer accurately reflects the lack of availability of detailed agenda information for the February 2026 meeting, consistent with the citations provided. | What was the agenda for the Wi-Fi 8 February 2026 face-to-face meeting? |
| `ad91e922-8b8` | unspecified | entity_focused | 5 | The answer accurately states that the retrieved documents do not provide the agenda for the next main WFA meeting. | tell me the agenda for the next main wfa meeting |
| `9178c4c8-7d5` | fast | entity_focused | 5 | The answer accurately states that there are no updates on the Wi-Fi 8 February 2026 meeting agenda and cites relevant discussions. | What was the agenda for the Wi-Fi 8 February 2026 face-to-face meeting? |
| `62b260aa-0d5` | baseline | entity_focused | 5 | All claims about David Coleman's involvement in the Wi-Fi industry and specific topics he discusses are supported by the citations. | who is david coleman |
| `3f272e05-556` | fast | topic_discovery | 5 | The claims made in the answer are well-supported by the citations provided. | What is the difference between Wi-Fi 7 and Wi-Fi 8? |

