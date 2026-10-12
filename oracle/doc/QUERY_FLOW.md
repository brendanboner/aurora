# Oracle Query Flow Diagram

This document illustrates the complete flow when a query is made to the Oracle Service.

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              ORACLE QUERY FLOW                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

                                    ┌──────────┐
                                    │  Client  │
                                    └────┬─────┘
                                         │
                                         ▼
                              POST /query
                              {
                                "user_id": "...",
                                "question": "What are the latest Wi-Fi 7 updates?",
                                "mode": "answer",
                                "options": { ... }
                              }
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                                API LAYER                                        │
│  ┌─────────────────┐                                                           │
│  │ Authentication  │◄── Validates X-User-ID header                             │
│  └────────┬────────┘                                                           │
│           ▼                                                                     │
│  ┌─────────────────┐                                                           │
│  │ Query Endpoint  │◄── Validates request body                                 │
│  └────────┬────────┘                                                           │
└───────────┼────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                           STEP 1: INTENT CLASSIFICATION                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         Query Router                                     │   │
│  │                                                                          │   │
│  │   Input: "What are the latest Wi-Fi 7 updates?"                         │   │
│  │                           │                                              │   │
│  │                           ▼                                              │   │
│  │                    ┌─────────────┐                                       │   │
│  │                    │     LLM     │                                       │   │
│  │                    │  (gpt-4o)   │                                       │   │
│  │                    └──────┬──────┘                                       │   │
│  │                           │                                              │   │
│  │                           ▼                                              │   │
│  │   Output: intent="topic_discovery", confidence=0.95                     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                           STEP 2: QUERY PARSING                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         Query Parser                                     │   │
│  │                                                                          │   │
│  │   Input: "What are the latest Wi-Fi 7 updates?"                         │   │
│  │                           │                                              │   │
│  │              ┌────────────┴────────────┐                                 │   │
│  │              ▼                         ▼                                 │   │
│  │     ┌──────────────┐          ┌───────────────┐                         │   │
│  │     │  LLM-based   │          │   Heuristic   │                         │   │
│  │     │  Extraction  │          │   Fallback    │                         │   │
│  │     └──────┬───────┘          └───────────────┘                         │   │
│  │            │                                                             │   │
│  │            ▼                                                             │   │
│  │   ParsedQuery:                                                          │   │
│  │   - topics: ["Wi-Fi 7"]                                                 │   │
│  │   - organizations: []                                                   │   │
│  │   - start_date: "2025-12-10"  (30 days ago from "latest")              │   │
│  │   - end_date: null                                                      │   │
│  │   - keywords: ["updates"]                                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                        STEP 3: ENTITY RESOLUTION                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                       Entity Resolver                                    │   │
│  │                                                                          │   │
│  │   Input: topics=["Wi-Fi 7"]                                             │   │
│  │                           │                                              │   │
│  │          ┌────────────────┼────────────────┐                            │   │
│  │          ▼                ▼                ▼                            │   │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                     │   │
│  │   │Exact Match  │  │Alias Match  │  │Vector Match │                     │   │
│  │   │             │  │             │  │ (fallback)  │                     │   │
│  │   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                     │   │
│  │          │                │                │                            │   │
│  │          └────────────────┼────────────────┘                            │   │
│  │                           ▼                                              │   │
│  │   Query Graph:                                                          │   │
│  │   MATCH (t:Topic) WHERE toLower(t.name) = 'wi-fi 7'                    │   │
│  │                           │                                              │   │
│  │                           ▼                                              │   │
│  │   Resolved: "Wi-Fi 7" → "wi-fi 7" (actual graph node name)             │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                        STEP 4: DOCUMENT RETRIEVAL                               │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        Hybrid Search                                     │   │
│  │                              │                                           │   │
│  │         ┌────────────────────┴────────────────────┐                     │   │
│  │         ▼                                         ▼                     │   │
│  │  ┌──────────────────┐                  ┌──────────────────┐             │   │
│  │  │ Keyword Retriever│                  │ Vector Retriever │             │   │
│  │  │                  │                  │   (if enabled)   │             │   │
│  │  │  Query Neo4j:    │                  │                  │             │   │
│  │  │  - Topic rels    │                  │  1. Generate     │             │   │
│  │  │  - Date filter   │                  │     query embed  │             │   │
│  │  │  - Text search   │                  │  2. Vector index │             │   │
│  │  │                  │                  │     search       │             │   │
│  │  └────────┬─────────┘                  └────────┬─────────┘             │   │
│  │           │                                     │                       │   │
│  │           │    ┌─────────────────────┐         │                       │   │
│  │           └───►│  Reciprocal Rank    │◄────────┘                       │   │
│  │                │  Fusion (RRF)       │                                 │   │
│  │                │                     │                                 │   │
│  │                │  score = Σ 1/(k+r)  │                                 │   │
│  │                └──────────┬──────────┘                                 │   │
│  │                           │                                             │   │
│  │                           ▼                                             │   │
│  │                   Merged & Ranked Documents                            │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  Neo4j Query (simplified):                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │  MATCH (r:Resource)-[:RELATES_TO]->(t:Topic)                            │   │
│  │  WHERE toLower(t.name) IN ['wi-fi 7']                                   │   │
│  │    AND date(r.publish_date) >= date('2025-12-10')                       │   │
│  │  RETURN r, collect(t) as topics                                         │   │
│  │  ORDER BY relevance_score DESC                                          │   │
│  │  LIMIT 20                                                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                        STEP 5: CONTEXT BUILDING                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                       Context Builder                                    │   │
│  │                                                                          │   │
│  │   From retrieved documents, extract:                                    │   │
│  │                                                                          │   │
│  │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         │   │
│  │   │ Central Topics  │  │ Key Orgs        │  │ Key People      │         │   │
│  │   │ - wi-fi 7       │  │ - Wi-Fi Alliance│  │ - Dorothy Stanley│        │   │
│  │   │ - wpa3          │  │ - Broadcom      │  │ - Stephen Orr   │         │   │
│  │   │ - mlo           │  │ - Intel         │  │                 │         │   │
│  │   └─────────────────┘  └─────────────────┘  └─────────────────┘         │   │
│  │                                                                          │   │
│  │   ┌─────────────────────────────────────────────────────────────┐       │   │
│  │   │ Related Entities (via graph traversal)                       │       │   │
│  │   │ - 802.11be (alias of wi-fi 7)                               │       │   │
│  │   │ - 6 GHz band                                                 │       │   │
│  │   │ - MLO (multi-link operation)                                │       │   │
│  │   └─────────────────────────────────────────────────────────────┘       │   │
│  │                                                                          │   │
│  │   Temporal patterns: "Documents span 3 months (Oct 2025 - Jan 2026)"   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                        STEP 6: RESPONSE GENERATION                              │
│                           (Answer Mode Only)                                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                      Response Generator                                  │   │
│  │                                                                          │   │
│  │   Input:                                                                │   │
│  │   - Question: "What are the latest Wi-Fi 7 updates?"                   │   │
│  │   - Documents: [doc1, doc2, doc3, ...]                                 │   │
│  │   - Graph context                                                       │   │
│  │                           │                                              │   │
│  │                           ▼                                              │   │
│  │                    ┌─────────────┐                                       │   │
│  │                    │     LLM     │                                       │   │
│  │                    │  (gpt-4o)   │                                       │   │
│  │                    └──────┬──────┘                                       │   │
│  │                           │                                              │   │
│  │                           ▼                                              │   │
│  │   Output:                                                               │   │
│  │   - answer: "The latest Wi-Fi 7 updates focus on..."                   │   │
│  │   - citations: [{doc_index: 0, text: "..."}]                           │   │
│  │   - confidence: 0.85                                                    │   │
│  │   - suggestions: ["What is MLO?", "Compare Wi-Fi 6E vs Wi-Fi 7"]       │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                              RESPONSE                                           │
│  {                                                                              │
│    "mode": "answer",                                                           │
│    "answer": "The latest Wi-Fi 7 updates include...[1][2]",                   │
│    "citations": [...],                                                         │
│    "documents": [                                                              │
│      {"title": "Wi-Fi 7 R2 Specification", "publish_date": "2025-12-15", ...},│
│      {"title": "Wi-Fi 7 Security Update", "publish_date": "2025-12-20", ...}  │
│    ],                                                                          │
│    "graph_context": {                                                          │
│      "central_topics": ["wi-fi 7", "mlo", "wpa3"],                            │
│      "key_organizations": ["Wi-Fi Alliance"],                                  │
│      "key_people": ["Dorothy Stanley"],                                        │
│      "related_entities": [...]                                                 │
│    },                                                                          │
│    "metadata": {                                                               │
│      "intent": "topic_discovery",                                              │
│      "strategies_used": ["keyword", "vector"],                                 │
│      "total_candidates": 45,                                                   │
│      "processing_time_ms": 3250                                                │
│    },                                                                          │
│    "suggestions": ["What is MLO?", "Wi-Fi 7 vs Wi-Fi 6E comparison"],         │
│    "confidence_score": 0.85                                                    │
│  }                                                                             │
└────────────────────────────────────────────────────────────────────────────────┘
```

## Detailed Component Interactions

### Retrieval Mode Flow

```
User Query
    │
    ├──► Intent Classification (LLM)
    │
    ├──► Query Parsing (LLM + Heuristics)
    │        │
    │        └──► Entity Resolution (Graph Lookup)
    │
    ├──► Document Retrieval
    │        │
    │        ├──► Keyword Retriever ──► Neo4j
    │        │                              │
    │        └──► Vector Retriever ──► Neo4j Vector Index
    │                                       │
    │        ◄── RRF Fusion ◄───────────────┘
    │
    ├──► Context Building (Graph Traversal)
    │
    └──► Response (documents + context)
```

### Answer Mode Flow (adds LLM generation)

```
[Same as Retrieval Mode]
    │
    └──► Response Generator (LLM)
              │
              └──► Response (documents + context + answer + citations)
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    GRACEFUL DEGRADATION                          │
│                                                                  │
│  LLM Unavailable?                                               │
│       │                                                          │
│       └──► Use heuristic parsing                                │
│                                                                  │
│  Vector Search Fails?                                           │
│       │                                                          │
│       └──► Fall back to keyword-only search                     │
│                                                                  │
│  Entity Resolution Fails?                                       │
│       │                                                          │
│       └──► Use unresolved entity names                          │
│                                                                  │
│  Neo4j Unavailable?                                             │
│       │                                                          │
│       └──► Return 503 with error details                        │
│                                                                  │
│  Answer Generation Fails?                                       │
│       │                                                          │
│       └──► Return documents without answer                      │
└─────────────────────────────────────────────────────────────────┘
```

## Performance Characteristics

| Step | Typical Time | Notes |
|------|-------------|-------|
| Intent Classification | 500-1000ms | Single LLM call |
| Query Parsing | 500-1500ms | LLM + optional entity resolution |
| Keyword Retrieval | 100-500ms | Neo4j query |
| Vector Retrieval | 200-800ms | Embedding + vector search |
| Context Building | 50-200ms | Graph traversal |
| Response Generation | 1000-3000ms | LLM synthesis (answer mode only) |
| **Total (retrieval)** | **1-3 seconds** | |
| **Total (answer)** | **3-6 seconds** | |
