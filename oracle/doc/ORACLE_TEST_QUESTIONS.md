# Oracle Service Test Questions

This document contains test questions for validating the Oracle Service hybrid search functionality. Questions are organized by query intent and the graph pattern they trigger.

## Query Intent Patterns

### 1. Entity-Focused → `org_hierarchy` pattern

Tests organization traversal and related orgs (parent/child/affiliated organizations).

```
What did Wi-Fi Alliance announce recently?
What has IEEE 802.11 published this year?
Show me FCC documents about spectrum
What is Qualcomm working on?
Latest news from Broadcom
What did the Wi-Fi Alliance certification team release?
```

### 2. Relationship Query → `people_topic` pattern

Tests people-topic and people-org relationships.

```
Who is working on Wi-Fi 7?
What topics are people from Intel working on?
Who are the key contributors to 6 GHz discussions?
What are Qualcomm engineers publishing about?
Who is involved in MLO development?
Show me experts on AFC systems
```

### 3. Topic Discovery → `topic_relationship` pattern

Tests topic co-occurrence and related topics.

```
What topics are related to MLO?
Tell me about Wi-Fi 7 certification
What is connected to 6 GHz spectrum?
Explain the relationship between 802.11be and Wi-Fi 7
What topics come up with AFC?
Show me everything about multi-link operation
```

### 4. Trend Analysis → `trend_analysis` pattern

Tests temporal growth detection.

```
What topics are trending this month?
What's hot in wireless right now?
What topics have grown in popularity recently?
What are the emerging trends in Wi-Fi?
What's gaining attention lately?
Show me trending discussions
```

### 5. Comparative → `cross_org_collaboration` pattern

Tests multi-org document discovery.

```
Which organizations are collaborating on 6 GHz?
What are different companies saying about Wi-Fi 7?
Compare perspectives on spectrum sharing
Who is working together on AFC?
Show me joint efforts on MLO
What organizations are involved in 802.11be?
```

---

## Edge Cases & Stress Tests

### Typos & Variations

Tests vector search semantic matching and typo recovery.

```
What is Quallcomm doing?
wifi7 certification
802.11 be standard
Multi Link Operation
six gigahertz spectrum
```

### Alias Resolution

Tests entity resolver alias matching.

```
What did WFA announce?
IEEE SA documents
Latest from the FCC
```

### Date Filtering

Tests temporal filters in queries.

```
Wi-Fi 7 news from last week
What happened in January 2026?
6 GHz updates since December
Documents from Q4 2025
Recent MLO announcements
```

### Vague/Broad Queries

Tests fallback behavior and general retrieval.

```
What's new?
Tell me about wireless
Latest updates
Show me everything
What should I know?
```

### Specific Technical Queries

Tests precise technical term matching.

```
320 MHz channel bandwidth support
4096-QAM modulation in Wi-Fi 7
EMLSR vs EMLMR comparison
Punctured transmission in 802.11be
R1/R2 LPI and VLP power classes
```

### Multi-Entity Queries

Tests queries with multiple organizations or topics.

```
What are Intel and Qualcomm saying about Wi-Fi 7?
Compare FCC and ETSI on 6 GHz
Wi-Fi Alliance and IEEE collaboration on certification
AFC and standard power mode differences
```

---

## Expected Behavior

| Query Type | Expected Behavior |
|------------|-------------------|
| Org-focused | Returns docs from specified org + related orgs |
| Topic query | Returns docs + related topics in graph_data context |
| People query | Returns docs mentioning people + their affiliations |
| Trending | Returns growth percentages, period comparison data |
| Collaboration | Returns multi-org docs, collaboration pairs in graph_data |
| Typos | Vector search recovers correct entities |
| Date filters | Returns only docs in specified date range |
| Vague queries | Falls back to topic_relationship pattern |

---

## Quick Smoke Test

Run these commands in sequence to validate basic functionality:

```bash
# Entity-focused
aurora query "What did Wi-Fi Alliance announce recently?"

# People-topic
aurora query "Who is working on Wi-Fi 7?"

# Topic discovery
aurora query "What topics are related to MLO?"

# Trend analysis
aurora query "What's trending this month?"

# Cross-org collaboration
aurora query "Which organizations are collaborating on 6 GHz?"

# Typo recovery (vector search)
aurora query "What is Quallcomm doing?"

# Date filter
aurora query "Wi-Fi 7 news from last week"

# Vague query fallback
aurora query "What's new in wireless?"
```

---

## Validation Checklist

When testing, verify:

- [ ] **Strategies Used**: Check logs show `keyword`, `vector`, `graph` strategies
- [ ] **RRF Fusion**: Documents appearing in multiple strategies rank higher
- [ ] **Graph Data**: Response includes `graph_data` with related topics, org contributions, etc.
- [ ] **Match Reasons**: Documents show which strategies found them (e.g., "Keyword match (rank #3)")
- [ ] **Recency Boost**: Recent documents get relevance boost
- [ ] **Intent Classification**: Correct pattern selected based on query type
