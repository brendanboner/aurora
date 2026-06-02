# Fast Pipeline Entity Guard — Design

**Date:** 2026-06-02
**Owner:** bbonner
**Status:** Draft, pending review
**Context:** Production eval (2026-06-02) showed fast-pipeline hallucination rate of 20% on entity_focused queries, driven by overconfident answers when the named entity doesn't exist in the graph (e.g., "Kevin" → returns Wi-Fi 7 meetings; "BGP working group" → returns ACE working group).

## Goal

Reduce fast-pipeline hallucination rate from 20% toward the baseline's 15% target, **without slowing down fast pipeline latency** (currently p50 5.7s, p95 24.8s) and **without falling back to baseline RAG** (12s+, too slow per UX requirement).

When the user names an entity that isn't in the graph, the system streams a fast (≤500 ms) "I don't see X — did you mean Y or Z?" response with fuzzy-matched suggestions, rather than confidently answering about an unrelated entity.

## Root cause

`oracle/src/services/query_template_registry.py` template `DOCUMENTS_BY_TOPIC` (lines 1489–1677) has two phases:

1. **Exact-match** (lines 1502–1514): `toLower(t.name) = toLower(topic)` on Topic nodes. Confidence multiplier 1.0.
2. **Fuzzy fallback** (lines 1516–1553): If no exact match, `CONTAINS` substring search on `title`/`summary` text. Confidence multiplier 0.8.

The fuzzy fallback returns any document with the entity name in its text, regardless of relevance. The 0.8× penalty is too gentle — fuzzy matches end up with confidence almost as high as exact matches.

Confidence scoring in `fast_engine.py:566-578` is unaware of match quality; it weights only routing-pattern specificity, doc count, and temporal freshness.

## Design

### Change 1 — Entity-existence precheck (in `fast_engine.py:_retrieve_neo4j_data()`)

Before executing the main Cypher template for `entity_focused` intent, run a single batched precheck that returns both existence and suggestions:

```cypher
// $entity = the extracted entity name (e.g. "Kevin")
// $entity_lower = toLower($entity)
WITH $entity_lower AS query
OPTIONAL MATCH (exact)
  WHERE (exact:Person OR exact:Organization OR exact:Topic)
    AND toLower(exact.name) = query
WITH query, collect(DISTINCT {name: exact.name, label: head(labels(exact))}) AS exact_matches
CALL {
  WITH query
  MATCH (n)
  WHERE (n:Person OR n:Organization OR n:Topic)
    AND (toLower(n.name) STARTS WITH substring(query, 0, 3)
         OR toLower(n.name) CONTAINS query
         OR query CONTAINS toLower(n.name))
  RETURN n.name AS name, head(labels(n)) AS label
  LIMIT 5
}
RETURN exact_matches, collect(DISTINCT {name: name, label: label}) AS suggestions
```

Cost budget: <100 ms (indexed lookup + small fuzzy scan). Runs only for `entity_focused` intent (~20% of queries per the eval), so adds <20 ms amortized.

If `exact_matches` is empty:
- Set `plan.entity_missing = True`
- Set `plan.entity_suggestions = [suggestions]`
- **Skip the main Cypher template**
- Return a structured payload that the response generator turns into a streamed "did you mean" answer

### Change 2 — Tighten the fuzzy fallback in `DOCUMENTS_BY_TOPIC`

Two options, I'll implement **option B** unless we decide otherwise:

- **A.** Remove the fuzzy fallback entirely for `entity_focused` intent. Simpler, but loses real recall for misspelled-but-real entities.
- **B.** Keep the fuzzy fallback but (1) gate it by intent — only allow CONTAINS-on-text for `topic_discovery` intent — and (2) drop the confidence multiplier from 0.8× to 0.4× when the fuzzy path fires. The 0.4× pushes fuzzy answers below the "high confidence" threshold the UI shows, so the user knows it's a soft match.

### Change 3 — Confidence calibration in `fast_engine.py:query()`

Current formula (lines 573–578):
```python
fast_confidence = round(
    plan.confidence * 0.4 + result_count_factor * 0.4 + temporal_factor * 0.2, 3
)
```

Add a fourth term: `match_quality_factor` (1.0 exact / 0.5 fuzzy / 0.0 missing), rebalanced:
```python
fast_confidence = round(
    plan.confidence * 0.3
    + result_count_factor * 0.3
    + temporal_factor * 0.1
    + match_quality_factor * 0.3,
    3,
)
```

When `plan.entity_missing` is True, return confidence 0.2 (low) directly, without computing the rest.

### Change 4 — "Did you mean" response generation

Add a new code path in `oracle/src/prompts/answer_generator.py` (or wherever fast-pipeline answer synthesis lives) for the `entity_missing` case:

```text
I don't have specific information on "{entity}" in the knowledge graph.

Did you mean: {suggestion_1}, {suggestion_2}, or {suggestion_3}?

You can also try asking about the related topics I do have data on.
```

This is template text, not LLM-generated, so it streams essentially instantly. No LLM cost.

## Non-goals

- Not changing the baseline pipeline.
- Not adding background validation passes (rejected — adds latency).
- Not changing the answer for `topic_discovery` queries (75% of traffic, mostly fine).
- Not building a full entity-disambiguation system; the suggestions list is heuristic, not ranked by semantic similarity.

## Risk and mitigation

- **Risk:** Precheck adds ~50–100 ms latency to every `entity_focused` query.
  *Mitigation:* Run the precheck as the first Cypher call, so by the time we'd otherwise be running the main template, we already know which path to take.
- **Risk:** Some real entities live under labels other than Person/Organization/Topic.
  *Mitigation:* Extend the precheck's label list as needed; start broad (`:Person OR :Organization OR :Topic`) and add `:Event` if eval shows misses.
- **Risk:** "Did you mean" suggestions could themselves be wrong if the fuzzy criteria are too loose.
  *Mitigation:* Suggestions are explicitly framed as suggestions, not answers; user can reformulate.
- **Risk:** Tightening fuzzy match removes some currently-helpful results.
  *Mitigation:* Measured by re-running the eval after deployment. If aggregate faithfulness drops on topic_discovery, loosen the gate.

## Validation

After implementation:

1. Unit tests in `oracle/tests/` covering: exact match, fuzzy match, no match, no suggestions.
2. CLI replay of the 5 worst-scoring queries from the eval — they must not produce confident wrong answers.
3. Full eval re-run (`eval_aurora.py --judge --sample 300 --refresh`) to measure hallucination rate. Target: ≤10% on fast pipeline.
4. p50 latency on `entity_focused` queries must stay ≤7s (currently ~5.7s overall fast pipeline).

## Files touched

| File | Change |
|---|---|
| `oracle/src/engines/fast_engine.py` | Add entity precheck call in `_retrieve_neo4j_data()`; update `query()` confidence formula |
| `oracle/src/services/query_template_registry.py` | New `ENTITY_EXISTS_PRECHECK` template; gate `DOCUMENTS_BY_TOPIC` fuzzy fallback by intent |
| `oracle/src/services/local_router.py` | Pass extracted entities into route plan so precheck can read them |
| `oracle/src/models/route_plan.py` | Add `entity_missing: bool`, `entity_suggestions: list`, `match_quality: str` |
| `oracle/src/prompts/answer_generator.py` | Branch for `entity_missing` → templated "did you mean" response |
| `oracle/src/routes/query.py` (`/query/stream`) | Stream the templated response in the missing-entity branch |
| `oracle/tests/...` | Add tests covering the new behavior |

## Open questions

1. Should the precheck cover `Event` labels too (e.g., "what happened at the March plenary")? Likely yes once we see real-world data; defer until first re-eval.
2. Should fuzzy match in `DOCUMENTS_BY_TOPIC` be removed entirely or just gated? Option B above gates it; if eval shows it's still adding noise on topic_discovery, escalate to option A.
