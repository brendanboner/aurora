# Oracle Service Personalization Plan

**Author**: AI Assistant  
**Date**: January 15, 2026  
**Status**: DRAFT - Awaiting Review

---

## Executive Summary

This document outlines a plan to add optional personalization to Oracle Service queries. The key insight is that personalization should **tailor the answer narrative**, not filter documents. This preserves Oracle's retrieval quality while allowing users to receive responses framed for their specific interests and expertise.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Current Oracle Architecture](#2-current-oracle-architecture)
3. [User Preferences Available](#3-user-preferences-available)
4. [When Personalization Should NOT Apply](#4-when-personalization-should-not-apply)
5. [When Personalization Adds Value](#5-when-personalization-adds-value)
6. [Proposed Solution](#6-proposed-solution)
7. [Integration with Existing Oracle Flow](#7-integration-with-existing-oracle-flow)
8. [Implementation Plan](#8-implementation-plan)
9. [Open Questions](#9-open-questions)

---

## 1. Problem Statement

### Current State
- Oracle Service retrieves documents and generates answers based solely on the query
- User preferences exist in PostgreSQL but are **not used** by Oracle
- The legacy backend `/query` endpoint previously merged preferences into filters, but this was **intentionally disabled** because it caused over-filtering and irrelevant results

### Desired State
- Users can optionally receive answers tailored to their interests
- Toggle control so users can turn personalization on/off
- Personalization enhances relevance without compromising retrieval quality

### Key Constraint
The previous approach (merging preferences into document filters) failed because:
- Adding preferred topics to filters narrowed results too much
- Users asking about new topics got no results because their preferences didn't match
- Filters are AND-based, so more filters = fewer results

---

## 2. Current Oracle Architecture

### Query Flow (Simplified)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         POST /oracle/query                               │
│         { user_id, question, mode, options }                            │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. INTENT CLASSIFICATION                                                 │
│    - Classify: entity_focused | topic_discovery | relationship |        │
│                trend_analysis | comparative                             │
│    - Extract entities, dates, keywords from query                       │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. HYBRID SEARCH (Parallel)                                             │
│    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                │
│    │   Keyword    │  │    Vector    │  │    Graph     │                │
│    │  Retriever   │  │  Retriever   │  │  Retriever   │                │
│    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                │
│           └─────────────────┼─────────────────┘                         │
│                             ▼                                           │
│                   Reciprocal Rank Fusion (RRF)                          │
│                   → Ranked document list                                │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. CONTEXT BUILDING                                                      │
│    - Graph context (central topics, key orgs, temporal patterns)        │
│    - Ranking explanations                                               │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. RESPONSE GENERATION                                                   │
│    ┌─────────────────────────────────────────────────────────────────┐  │
│    │ If mode == 'answer':                                            │  │
│    │   - Send documents + question to LLM                            │  │
│    │   - Generate answer with citations                              │  │
│    │   - Calculate confidence score                                  │  │
│    └─────────────────────────────────────────────────────────────────┘  │
│    ┌─────────────────────────────────────────────────────────────────┐  │
│    │ If mode == 'retrieval':                                         │  │
│    │   - Return ranked document list only                            │  │
│    └─────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         QueryResponse                                    │
│   { query_id, mode, answer, citations, documents, graph_context,        │
│     metadata, suggestions, confidence_score }                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Query Router | `oracle/src/services/query_router.py` | Intent classification |
| Query Parser | `oracle/src/services/query_parser.py` | Entity extraction |
| Hybrid Search | `oracle/src/services/hybrid_search.py` | Parallel retrieval + RRF |
| Context Builder | `oracle/src/services/context_builder.py` | Graph context assembly |
| Response Generator | `oracle/src/services/response_generator.py` | Answer generation |
| Answer Prompts | `oracle/src/prompts/answer_generator.py` | LLM prompts |

---

## 3. User Preferences Available

### PostgreSQL Schema: `user_preferences`

| Field | Type | Description | Example | Frontend Support |
|-------|------|-------------|---------|------------------|
| `topics` | TEXT[] | Topics of interest | `["Wi-Fi 7", "802.11be", "MLO"]` | ✅ UserProfile page |
| `organisations` | TEXT[] | Organizations to follow | `["Wi-Fi Alliance", "IEEE"]` | ✅ UserProfile page |
| `people` | TEXT[] | People to track | `["Stephen Palm"]` | ✅ UserProfile page |
| `sources` | TEXT[] | Preferred sources | `["wfa", "ieee"]` | ❌ No UI (not used) |

> **Note:** The `sources` field exists in the schema but has no frontend support, so we will **not** use it for personalization.

### Secondary Schema: `user_preference_profile` (Content Creator)

| Field | Type | Description | Frontend Support |
|-------|------|-------------|------------------|
| `topic_weights` | JSONB | Learned topic preferences (0.0-1.0) | ❌ Read-only (learned from feedback) |
| `agent_affinity` | JSONB | Content creator agent preferences | ✅ AgentPreferences page |
| `preferred_length` | TEXT | "short", "medium", "long" | ✅ AgentPreferences page |

> **Note:** `topic_weights` are learned from user feedback on social feed posts, not explicitly selected. We could potentially use these as *additional signals* for personalization, but the primary source should be the explicit `user_preferences` selections.

### What We'll Use for Personalization

For Oracle personalization, we focus on **explicitly selected preferences**:

| Field | Use in Personalization |
|-------|----------------------|
| `topics` | ✅ Primary - indicates areas of expertise/interest |
| `organisations` | ✅ Primary - indicates which industry players they care about |
| `people` | ✅ Secondary - indicates specific individuals they follow |
| `topic_weights` | ⚠️ Optional - could use as expertise depth signal |

### What This Tells Us About the User

From preferences, we can infer:
- **Area of expertise**: Topics they've selected indicate their domain
- **Organizational focus**: Which industry players they care about
- **Role signals**: An engineer tracking 802.11be vs. an executive tracking market trends

---

## 4. When Personalization Should NOT Apply

Based on your examples, here are query types where preferences should be ignored:

### 4.1 Document Lookups

> "Show me the meeting minutes for Wi-Fi 8 task group from last 2 weeks"

**Why preferences don't help:**
- User wants a **specific document**
- Query already contains all necessary filters (Wi-Fi 8, meeting minutes, 2 weeks)
- Adding preferences would only risk filtering out the document they want

**Detection signal:** Query contains specific document type + entity + time range

### 4.2 Learning New Areas

> "What are the new features Wi-Fi 8 will bring?"

**Why preferences don't help:**
- User is exploring **outside their expertise**
- Preferences would bias toward their existing knowledge
- They want comprehensive information, not a filtered view

**Detection signal:** Broad topic query without the topic in user's preferences

### 4.3 Queries with Explicit Entities

> "What did Broadcom announce about Matter?"

**Why preferences don't help:**
- User specified exactly what they want
- Adding other organizations from preferences dilutes focus
- Query is self-contained

**Detection signal:** Query contains specific org/topic/person mentions

---

## 5. When Personalization Adds Value

### 5.1 Open-Ended Queries

> "What's new in the industry?" or "What happened this week?"

**How personalization helps:**
- No specific topic → preferences help focus the answer
- Answer can emphasize user's areas of interest
- Still retrieve broadly, but narrate toward their interests

### 5.2 Answer Framing

> "Explain the latest developments in MLO"

**How personalization helps:**
- Documents retrieved normally
- Answer **framed** for user's expertise level
- If user tracks advanced topics → more technical depth
- If user tracks an organization → mention relevant connections

### 5.3 Relevance Emphasis

> "What should I know about Wi-Fi?"

**How personalization helps:**
- Highlights aspects relevant to user's role
- "Since you follow Wi-Fi Alliance, here's what matters for certification..."
- Connects information to their organizational context

---

## 6. Proposed Solution

### Core Principle

**Personalization affects ANSWER GENERATION, not document retrieval.**

| Aspect | Without Personalization | With Personalization |
|--------|------------------------|---------------------|
| Intent Classification | Based on query | Same |
| Entity Extraction | Based on query | Same |
| Document Retrieval | Query-driven | Same (no change) |
| Ranking | RRF fusion | Same |
| **Answer Generation** | Generic expert | **Tailored to user context** |

### Personalization Modes

Similar to how Oracle has query modes (`answer`, `retrieval`, `auto`), we propose three personalization modes:

| Mode | Behavior | Use Case |
|------|----------|----------|
| `off` | No personalization, generic expert answers | Default, or when user wants unbiased response |
| `on` | Always tailor answers to user preferences | User explicitly wants personalized answers |
| `auto` | System decides based on query type | Smart default - personalizes when it helps |

### Auto Mode Logic

When `personalize: auto`, the system analyzes the query to decide:

| Query Type | Auto Decision | Rationale |
|------------|---------------|-----------|
| **Document lookup** ("Show me meeting minutes for...") | `off` | Specific request, preferences don't help |
| **Explicit entities** ("What did Broadcom announce?") | `off` | User specified what they want |
| **Topic in preferences** ("Tell me about Wi-Fi 7") | `on` | User has context, can tailor depth |
| **Open-ended** ("What's new in the industry?") | `on` | Preferences help focus the answer |
| **Learning new area** (topic NOT in preferences) | `off` | Don't bias discovery |

**Implementation:** The auto-detection logic would run after intent classification and before response generation, examining:
1. Query intent (from existing intent classifier)
2. Extracted entities (from existing query parser)
3. Overlap between query topics and user preferences

### How It Works

When personalization is `on` (or `auto` decides to personalize):

1. **Fetch user preferences** from PostgreSQL
2. **Inject user context into answer prompt** (not retrieval)
3. **LLM tailors the narrative** while using the same documents

### Answer Prompt Enhancement

Current prompt (simplified):
```
You are an expert analyst. Answer based on the provided documents.
Question: {question}
Documents: {documents}
```

With personalization:
```
You are an expert analyst. Answer based on the provided documents.

Question: {question}
Documents: {documents}

**User Context (for tailoring your response):**
- Their areas of interest: {user_topics}
- Organizations they follow: {user_organizations}

**Tailoring Instructions:**
- Emphasize aspects related to their interests when relevant
- If they follow specific organizations, highlight those connections
- Adjust technical depth based on the sophistication of their tracked topics
- Do NOT omit information - tailor the narrative, not the content
```

### Why This Approach Works

| Benefit | Explanation |
|---------|-------------|
| **No over-filtering** | Documents retrieved identically |
| **Preserves discovery** | User still sees all relevant information |
| **Adds personal value** | Answer speaks to their specific context |
| **Optional** | Toggle on/off without breaking anything |
| **Cheap to implement** | Only changes prompt, not retrieval logic |

---

## 7. Integration with Existing Oracle Flow

### Where Personalization Fits

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         POST /oracle/query                               │
│     { user_id, question, mode, options: { personalize: "auto" } }       │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. INTENT CLASSIFICATION        (unchanged)                             │
│    → Returns: intent, extracted_entities, confidence                    │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. HYBRID SEARCH                (unchanged)                             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. CONTEXT BUILDING             (unchanged)                             │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. PERSONALIZATION DECISION     ◄─── NEW STEP (only if auto mode)       │
│                                                                         │
│    If options.personalize == "auto":                                    │
│      → Fetch user preferences from PostgreSQL                           │
│      → Analyze query type vs. user preferences                          │
│      → Decide: should_personalize = true/false                          │
│                                                                         │
│    If options.personalize == "on":                                      │
│      → Fetch user preferences from PostgreSQL                           │
│      → should_personalize = true                                        │
│                                                                         │
│    If options.personalize == "off":                                     │
│      → should_personalize = false (skip preference fetch)               │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. RESPONSE GENERATION          (modified)                              │
│                                                                         │
│    Response Generator receives:                                         │
│    - question, documents, graph_context, intent                         │
│    - user_context (NEW, only if should_personalize == true)             │
│                                                                         │
│    Answer prompt includes user context when provided                    │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         QueryResponse                                    │
│   (same schema + new field: personalization_applied: bool)              │
└─────────────────────────────────────────────────────────────────────────┘
```

### Comparison with Query Mode

| Aspect | Query Mode | Personalization Mode |
|--------|------------|---------------------|
| Options | `retrieval`, `answer`, `auto` | `off`, `on`, `auto` |
| Default | `answer` | `auto` |
| Persisted | localStorage | localStorage |
| Auto logic | Based on intent confidence | Based on query type vs. preferences |
| Affects | What gets returned (docs vs answer) | How answer is framed |

### Changes Required (Summary)

| Layer | Change | Impact |
|-------|--------|--------|
| **Request Model** | Add `personalize: Literal["off", "on", "auto"]` to `QueryOptions` | Minimal |
| **Query Endpoint** | Add personalization decision logic | ~30 lines |
| **Personalization Service** | NEW: fetch prefs + auto-detection logic | ~100 lines |
| **Response Generator** | Accept optional `user_context` parameter | ~5 lines |
| **Answer Prompt** | Add user context section when provided | ~20 lines |
| **Response Model** | Add `personalization_applied: bool` | ~2 lines |
| **Frontend API** | Pass `personalize` option | ~2 lines |
| **Frontend UI** | Add 3-way toggle (off/on/auto) | ~40 lines |

### What DOESN'T Change

- Intent classification logic
- Query parsing
- Keyword retriever
- Vector retriever
- Graph retriever
- RRF fusion
- Context builder
- Confidence scoring
- Query suggestions
- Caching (cache key includes personalize flag)

---

## 8. Implementation Plan

### Phase 1: Backend Support

**Files to modify:**

1. `oracle/src/models/request.py`
   - Add `personalize: Literal["off", "on", "auto"] = "off"` to `QueryOptions`

2. `oracle/src/models/response.py`
   - Add `personalization_applied: bool` to `QueryResponse`

3. `oracle/src/services/personalization.py` (NEW)
   - Fetch user preferences from PostgreSQL
   - Implement auto-detection logic:
     ```python
     def should_personalize(
         mode: str,  # "off", "on", "auto"
         intent: QueryIntent,
         parsed_entities: ParsedQuery,
         user_preferences: UserPreferences
     ) -> tuple[bool, Optional[UserContext]]:
         """Decide whether to personalize and return user context if so."""
     ```
   - Logic for auto mode:
     - If intent is `entity_focused` with explicit entities → `False`
     - If query topics overlap with user preferences → `True`
     - If intent is `topic_discovery` with open-ended query → `True`
     - If query topic is NOT in user preferences → `False` (learning mode)

4. `oracle/src/services/response_generator.py`
   - Add optional `user_context` parameter to `generate_answer()`
   - Pass to prompt builder

5. `oracle/src/prompts/answer_generator.py`
   - Add user context section to prompt when provided
   - Add tailoring instructions

6. `oracle/src/routes/query.py`
   - Call personalization service after intent classification
   - Pass user_context to response generator
   - Set `personalization_applied` in response

### Phase 2: Frontend Support

**Files to modify:**

1. `frontend/src/services/api.js`
   - Add `personalize` to `sendOracleQuery` options

2. `frontend/src/pages/Chatbot.jsx`
   - Add state for personalization mode (persisted to localStorage)
   - Add 3-way selector similar to query mode selector
   - Pass to query function
   - Optionally show "Personalized" indicator when response has `personalization_applied: true`

3. `frontend/src/pages/Chatbot.css`
   - Style for personalization selector (match query mode selector style)

**UI Mockup:**

```
┌────────────────────────────────────────────────────────────┐
│  Mode: [Answer ▼]    Personalize: [Auto ▼]                │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ Ask a question...                                    │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘

Personalize dropdown options:
  - Off (generic answers)
  - On (tailored to your profile)
  - Auto (system decides)
```

### Phase 3: Testing & Refinement

1. Test queries with/without personalization
2. Validate answer quality differences
3. Ensure no regression in retrieval quality
4. Add OTEL span attribute for personalization
5. Update Grafana dashboard to track usage

### Estimated Effort

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| Backend | ~4-6 hours | None |
| Frontend | ~2-3 hours | Backend complete |
| Testing | ~2-4 hours | Both complete |
| **Total** | **~8-13 hours** | |

---

## 9. Open Questions

### ~~9.1 What should the default personalization mode be?~~ RESOLVED

**Decision:** Default is `auto`. User selection is persisted to localStorage (same pattern as query mode).

### 9.2 Should we show users when personalization was applied?

When `personalize: auto` and the system decides to personalize, should we show:
> "✨ This answer was tailored to your interests"

**Pro:** Transparency about what's influencing answers  
**Con:** Could be annoying if shown every time

**Recommendation:** Show a subtle indicator, but don't be intrusive.

### 9.3 Should personalization affect retrieval mode?

Current plan only affects `answer` mode. Should `retrieval` mode also be affected?

**Option A:** No - retrieval mode is for browsing, user doesn't need tailoring  
**Option B:** Yes - add a "relevance to your interests" indicator on documents

**Recommendation:** Start with Option A (answer mode only), consider B later.

### 9.4 What about the Enhance flow?

When user clicks "Enhance", should that also use personalization?

**Current thinking:** Yes, if personalize is `on` or `auto` decides to personalize, enhanced answers should also be tailored.

### 9.5 Cache key implications

If personalization is enabled:
- Cache key should include `personalize` mode
- If mode is `on` or `auto` resolves to personalize, cache is per-user

**Proposed:** 
- `personalize: off` → shared cache
- `personalize: on` → per-user cache
- `personalize: auto` → depends on decision (may need to make decision before cache check, or cache the decision separately)

### ~~9.6 What if user has no preferences set?~~ RESOLVED

**Decision:** If user has no preferences (empty topics, orgs, people), fall back to normal query without personalization. No special prompt needed.

---

## Appendix: Alternative Approaches Considered

### A. Preference-based Ranking Boost (Rejected)

Boost documents matching user preferences in RRF ranking.

**Why rejected:**
- Complicates ranking logic
- May surface less relevant documents
- Hard to explain to users

### B. Preference-based Filtering (Previously Tried, Failed)

Add user preferences to retrieval filters.

**Why rejected:**
- Over-filtering causes poor results
- Breaks discovery of new topics
- Already tried in legacy backend - intentionally disabled

### C. Separate "Personalized Search" Mode (Rejected)

Create a distinct search mode for personalized queries.

**Why rejected:**
- Fragments the experience
- Users have to choose upfront
- More UI complexity

---

## Next Steps

1. **Review this plan** - Get feedback on approach
2. **Finalize open questions** - Especially 9.1-9.5
3. **Create implementation tickets** - Break into subtasks
4. **Implement Phase 1** - Backend support
5. **Implement Phase 2** - Frontend toggle
6. **Test & iterate** - Validate answer quality
