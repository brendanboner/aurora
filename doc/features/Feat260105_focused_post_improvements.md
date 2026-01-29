# Content Creator Focused Post Improvements

## Problem Statement

The content creator service was generating posts that aggregated multiple unrelated knowledge base articles, particularly when querying generic topics like "Wi-Fi". Historical knowledge base items compounded this issue by matching broad topics despite being years old or only tangentially related.

## Solution Overview

Implemented relevance scoring, topic specificity filtering, temporal bounds, quality thresholds, and diversity checks to ensure posts focus on specific subjects rather than generic topic aggregations.

## Changes Made

### 1. Enhanced `fetch_recent_events()` in `neo4j_context.py`

**Added Parameters:**
- `window_days: int = 90` - Temporal filter to exclude old articles
- `min_relevance_score: float = 0.3` - Quality threshold for article selection

**Relevance Scoring Algorithm:**
- **Topic Specificity (40% weight)**: Fewer total topics = more focused content
  - 1-3 topics: 1.0 score
  - 4-6 topics: 0.7 score
  - 7-10 topics: 0.4 score
  - 11-20 topics: 0.2 score
  - >20 topics: Filtered out (generic aggregation)

- **Query Match Rate (30% weight)**: Proportion of query topics matched in article

- **Recency Score (20% weight)**: Exponential decay with 30-day half-life

- **Title Match Bonus (10% weight)**: Query topics in title indicate primary focus

**Key Features:**
- Filters out resources with >20 topic relationships (generic content)
- Enforces temporal window to prevent historical articles from dominating
- Returns articles sorted by relevance score (primary) and recency (secondary)
- Logs relevance score statistics for monitoring

### 2. Enhanced `fetch_recent_documents()` in `neo4j_context.py`

**Added Parameters:**
- `window_days: int = 90` - Temporal filter
- `min_relevance_score: float = 0.3` - Quality threshold

**Relevance Scoring Algorithm:**
- **Organization Specificity (50% weight)**: Fewer organizations = more focused
  - 1-2 orgs: 1.0 score
  - 3-4 orgs: 0.7 score
  - 5-6 orgs: 0.4 score
  - 7-10 orgs: 0.2 score
  - >10 orgs: Filtered out

- **Recency Score (30% weight)**: Same exponential decay

- **Title Match Bonus (20% weight)**: Organization names in title

### 3. Updated `generate_post_payload()` in `generation_service.py`

**Quality-Based Selection:**
- Requests 30 candidates (increased from 8-12) to ensure quality pool
- Uses agent's `cadence_window_days` for temporal filtering
- Calculates minimum relevance score from agent's `discovery_tolerance`:
  - Strict (0.0) → 0.5 min_score
  - Exploratory (1.0) → 0.2 min_score
- Applies diversity filtering before final selection
- Returns 3-8 high-quality articles (down from 8-20)

### 4. New `_apply_diversity_filter()` Method in `generation_service.py`

**Prevents Duplicate Coverage:**
- Removes exact URL duplicates
- Calculates Jaccard similarity between article titles
- Filters articles with >70% title similarity
- Limits to 2 articles per domain to prevent source dominance
- Preserves relevance score ordering

**Similarity Threshold:** 0.7 (configurable)

### 5. Updated `poll_recent_events()` in `knowledge_monitor.py`

**Added Parameter:**
- `window_days: int = 90` - For consistency with gateway methods

## Configuration

### System-Wide Settings (settings.py)

New configurable parameters added to `Settings` class with environment variable support:

- **`DIVERSITY_SIMILARITY_THRESHOLD`** (float, 0.0-1.0, default: 0.7)
  - Jaccard similarity threshold for filtering similar articles
  - Higher values = stricter filtering (more duplicates removed)
  - Recommended: 0.60-0.80

- **`MIN_RELEVANCE_SCORE_DEFAULT`** (float, 0.0-1.0, default: 0.3)
  - Default minimum relevance score for article selection
  - Can be overridden by agent's `discovery_tolerance`
  - Recommended: 0.20-0.40

- **`MAX_TOPICS_PER_ARTICLE`** (int, default: 20)
  - Maximum topics per article before filtering as generic aggregation
  - Articles exceeding this are considered unfocused
  - Recommended: 15-25

- **`MAX_ARTICLES_PER_DOMAIN`** (int, default: 2)
  - Maximum articles from same domain in a single post
  - Ensures source diversity
  - Recommended: 2-3

- **`TEMPORAL_WINDOW_DAYS_DEFAULT`** (int, 1-365, default: 90)
  - Default temporal window for article selection
  - Can be overridden by agent's `cadence_window_days`
  - Recommended: 60-120

### Admin API Configuration

New admin endpoints for runtime configuration management:

**GET `/api/content-creator/admin/config/content-quality`**
- Retrieve current content quality settings

**PUT `/api/content-creator/admin/config/content-quality`**
- Update content quality settings (runtime only, not persisted)
- Request body: `ContentQualityConfig` JSON

**POST `/api/content-creator/admin/config/content-quality/reset`**
- Reset all settings to default values

### Frontend Admin Interface

New admin page: **`/admin/content-quality`**
- Visual sliders for similarity threshold and relevance score
- Number inputs for topic limits and domain limits
- Real-time preview of changes
- Save/Reset/Cancel controls
- Comprehensive help text and recommendations
- Warning about runtime vs. persistent changes

**Access:** Admin menu → Content Quality

**Requires:** Admin or Superadmin role

### Agent Model Fields (Already Present)

These existing fields now have enhanced impact:

- `cadence_window_days: int` - Controls temporal window for article selection (default: 7)
- `discovery_tolerance: float` - Controls minimum relevance score:
  - 0.0 (strict): min_score = 0.5
  - 0.5 (balanced): min_score = 0.35
  - 1.0 (exploratory): min_score = 0.2

### Default Values

- **Temporal Window**: 90 days (can be overridden by agent's `cadence_window_days`)
- **Minimum Relevance Score**: 0.3 (adjusted by agent's `discovery_tolerance`)
- **Maximum Topics per Article**: 20 (>20 = filtered as generic aggregation)
- **Maximum Organizations per Document**: 10
- **Diversity Similarity Threshold**: 0.7 (Jaccard similarity)
- **Maximum Articles per Domain**: 2

## Impact

### Before
- Generic topics like "Wi-Fi" pulled in every related article
- Historical articles dominated results
- Posts referenced 8-20 loosely related items
- No quality filtering beyond date sort
- Example: "Brian Innovator" post mixed Easy Connect, Passpoint, and old Congressional updates

### After
- Topics prioritized for specificity and focus
- Historical articles filtered by temporal window
- Posts reference 3-8 highly relevant, diverse articles
- Quality thresholds ensure focused content
- Relevance scoring prioritizes articles where query topic is central focus

## Monitoring

Relevance scores are logged at DEBUG level:
```
Fetched 8 events with relevance scores: min=0.45, max=0.92, avg=0.67
Diversity filter: 30 -> 8 articles (removed 22 duplicates/similar)
```

## Backward Compatibility

All new parameters have default values, so existing calls without these parameters will continue to work with enhanced behavior:
- `window_days=90` (reasonable default for most agents)
- `min_relevance_score=0.3` (balanced quality threshold)

## Testing Recommendations

1. **Agent Configuration Test**: Verify agents with different `discovery_tolerance` values get appropriate article sets
2. **Historical Data Test**: Confirm old articles (>90 days) are filtered unless agent has longer `cadence_window_days`
3. **Generic Topic Test**: Query "Wi-Fi" and verify <20 topics per article, relevance scores >0.3
4. **Diversity Test**: Verify multiple similar articles from same source are reduced to 2 max
5. **Post Quality Test**: Generate posts and verify 3-8 focused articles instead of 8-20 loosely related

## Future Enhancements

1. **Topic Hierarchy**: Add explicit parent/child relationships in Neo4j (e.g., Wi-Fi 7 → Wi-Fi → Networking)
2. **User Feedback Loop**: Incorporate user reactions to adjust relevance weights
3. **Agent-Specific Weights**: Allow agents to customize relevance scoring weights
4. **Semantic Similarity**: Use embeddings for better title similarity detection
5. **Topic Aliases**: Support topic aliases in content creator (currently only in backend)
