# Question-Answering Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     USER SUBMITS NATURAL LANGUAGE QUERY                  │
│                     POST /query {user_id, question}                      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 1: LOAD USER PREFERENCES FROM POSTGRESQL                           │
├─────────────────────────────────────────────────────────────────────────┤
│  • postgres.get_user_preferences(user_id)                               │
│  • Retrieve: topics[], organisations[], people[]                        │
│  • Handle missing preferences gracefully                                │
│                                                                          │
│  Result: {topics: [..], organisations: [..], people: [..]}              │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 2: LLM FILTER EXTRACTION                                            │
├─────────────────────────────────────────────────────────────────────────┤
│  • llm_service.parse_query_to_filters(question)                         │
│  • Azure OpenAI with domain-specific prompt                             │
│  • Extract: topics, organisations, people, dates, limit                 │
│  • Focus on high-level subjects and direct entity mentions              │
│  • Fallback to heuristic parsing if LLM unavailable                     │
│                                                                          │
│  Result: {topics: [..], organisations: [..], people: [..],              │
│           start_date: "...", end_date: "...", limit: 20}                │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 3: MERGE FILTERS WITH PREFERENCES                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  • _merge_filters_with_preferences()                                     │
│  • Strategy: LLM filters + User preferences (deduplicated)              │
│  • Both treated as RELEVANCE SIGNALS (not hard filters)                 │
│  • Increase limit if many filters present                               │
│                                                                          │
│  LLM:   topics: ["Wi-Fi 6"]                                             │
│  Prefs: topics: ["802.11ax", "Bluetooth"]                               │
│  ──────────────────────────────────────────                             │
│  Merged: topics: ["Wi-Fi 6", "802.11ax", "Bluetooth"]                   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 4: QUERY NEO4J KNOWLEDGE GRAPH                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  • repository.get_recent_resources(merged_filters)                      │
│  • Enhanced Cypher query with relevance ranking                         │
│  • Alias matching: topics/orgs by name OR aliases                       │
│  • Multi-factor scoring:                                                │
│    ├─ Topic match:        40%                                           │
│    ├─ Organization match: 30%                                           │
│    ├─ People match:       20%                                           │
│    └─ Relationship conf:  10%                                           │
│  • Recency weighting: newer docs ranked higher                          │
│  • Final rank: 70% relevance + 30% recency                              │
│                                                                          │
│  Result: [{resource: {title, url, summary, ...},                        │
│            topics: [{name, ...}],                                       │
│            organisations: [{name, ...}],                                │
│            people: [{name, ...}]}]                                      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 5: LLM SUMMARIZATION WITH CONTEXT                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  • llm_service.summarise_documents(question, docs, preferences)         │
│  • Azure OpenAI with anti-hallucination instructions                    │
│  • System prompt includes user preferences for context                  │
│  • Strict requirement: answer ONLY from provided documents              │
│  • Reference specific documents in answer                               │
│                                                                          │
│  Result: "Based on the retrieved documents, [answer with citations]..." │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ STEP 6: FORMAT AND RETURN STRUCTURED RESPONSE                            │
├─────────────────────────────────────────────────────────────────────────┤
│  • _format_documents_for_response()                                      │
│  • Limit topic display (max 10 per document)                            │
│  • Build response object with full traceability                         │
│                                                                          │
│  Response: {                                                            │
│    answer: "Generated answer from documents...",                        │
│    filters: {                                                           │
│      applied: {merged filters used in query},                           │
│      from_query: {LLM extracted filters},                               │
│      from_preferences: {user preference filters}                        │
│    },                                                                   │
│    documents: [{formatted doc with metadata}],                          │
│    document_count: 15                                                   │
│  }                                                                      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        RETURN TO CLIENT                                  │
│              JSON response with answer + metadata                        │
└─────────────────────────────────────────────────────────────────────────┘


═══════════════════════════════════════════════════════════════════════════
                            KEY PRINCIPLES
═══════════════════════════════════════════════════════════════════════════

🎯 KNOWLEDGE GRAPH FIRST
   All responses based on Neo4j documents, never LLM hallucination

🔍 PREFERENCE INTEGRATION  
   User preferences as relevance signals, not hard constraints

🧠 INTELLIGENT EXTRACTION
   Domain-aware LLM prompts for wireless/standards entities

📊 RELEVANCE RANKING
   Multi-factor scoring: topics, orgs, people, quality, recency

🔗 FULL TRACEABILITY
   Response shows all filters applied and their sources

💪 RESILIENT OPERATION
   Works without preferences, graceful fallbacks, logs everything

═══════════════════════════════════════════════════════════════════════════


═══════════════════════════════════════════════════════════════════════════
                          EXAMPLE EXECUTION
═══════════════════════════════════════════════════════════════════════════

Query: "What are the latest Wi-Fi Alliance updates?"
User: ID=1 with preferences: topics=["802.11ax"], orgs=["IEEE"]

STEP 1: Load Preferences
└─→ topics: ["802.11ax"], organisations: ["IEEE"], people: []

STEP 2: LLM Filter Extraction
└─→ topics: ["Wi-Fi"], organisations: ["Wi-Fi Alliance"], limit: 20

STEP 3: Merge Filters
└─→ topics: ["Wi-Fi", "802.11ax"]
    organisations: ["Wi-Fi Alliance", "IEEE"]
    limit: 30 (increased due to multiple filters)

STEP 4: Query Neo4j
└─→ Retrieved 18 documents
    Top match: "Wi-Fi Alliance Certifies Wi-Fi 6E"
      Relevance: 0.89 (strong topic + org match)
      Date: 2025-11-15 (very recent)
      Final score: 0.91

STEP 5: Summarize
└─→ "Based on recent documents from the Wi-Fi Alliance, the most 
     significant update is the certification of Wi-Fi 6E devices 
     announced on November 15, 2025. This includes... [citing 
     retrieved documents]"

STEP 6: Format Response
└─→ {
      answer: "...",
      document_count: 18,
      filters: {
        from_query: ["Wi-Fi", "Wi-Fi Alliance"],
        from_preferences: ["802.11ax", "IEEE"],
        applied: ["Wi-Fi", "802.11ax", "Wi-Fi Alliance", "IEEE"]
      }
    }

═══════════════════════════════════════════════════════════════════════════
