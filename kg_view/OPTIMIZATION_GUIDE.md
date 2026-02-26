# Knowledge Graph Visualization - Optimization Guide

## Overview

This guide explains the optimizations implemented to handle large knowledge graphs (45,000+ nodes) while maintaining interactive performance and focusing on the most important entities.

## Key Features Implemented

### 1. Importance-Based Filtering

**What it does**: Allows users to filter the graph to show only nodes above a certain importance threshold.

**How it works**:
- Each node gets an `importance` score (0.0 - 1.0) based on:
  - Number of incoming relationships (more connections = more important)
  - Node type (Organizations and Topics weighted higher than Events)
  - Explicit curation signals
- Users can adjust the slider from 0% to 100% to focus on high-value nodes
- Default threshold is 0% (show all), but you can increase it to reduce clutter

**Formula** (simplified):
```
importance = typeWeight + (inboundCount * connectionMultiplier)
```

### 2. Topic Hierarchy Tiers

**What it does**: Organizes topics into 3 tiers for progressive disclosure of information.

**Tier System**:
- **Tier 0 (Root)**: Top-level, curated topics (Wi-Fi Alliance, IEEE 802.11, etc.)
- **Tier 1 (Major)**: Major topics directly related to tier-0 topics (Wi-Fi 7, 802.11be, etc.)
- **Tier 2 (Leaf)**: All other detailed topics (~13,000 topics)

**Curated-Only Search**:
- When "Curated Topics Only" is enabled, topic searches only return Tier 0-1 topics
- This prevents search results from being overwhelmed by detailed leaf topics
- Tier-2 topics are still accessible by direct search or graph exploration

### 3. Smart Node Type Hiding

**What it does**: Hide less-important node types by default while allowing users to show them.

**Default Hidden Types**:
- `IngestionBatch` - Internal pipeline metadata, not useful for analysis
- Optional: `Event` - Often peripheral to knowledge discussions

**Quick Toggle**:
- Users can quickly hide/show any node type (Resource, Topic, Organization, Person, Event, DataSource, IngestionBatch)
- Changes apply immediately when "Apply Filters" is clicked
- Individual type toggling is more granular than global importance threshold

### 4. Progressive Graph Loading

**What it does**: Rather than loading all 45,000 nodes at once, load intelligently:

1. **Initial Load**: 1,000 nodes sorted by importance
2. **Entity Selection**: Load 2-hop neighborhood on-demand (~200-500 nodes)
3. **Multi-Entity**: Compute shortest paths and load connecting subgraph (~500 nodes)
4. **Progressive Exploration**: Each "hop" click loads more neighbors

**Benefits**:
- Browser stays responsive (WebGL can render ~1000 nodes smoothly)
- User sees results immediately
- Graph fills in more nodes as user explores
- Users focus on high-value content first

## Using the Filter Panel

### Accessing Filters
1. Click the **⚙️ Filters** button in the top-left corner
2. The filter panel slides down with configuration options

### Filter Options

#### Node Types
- **Checkboxes for**: Resource, Topic, Organization, Person, Event, DataSource, IngestionBatch
- **Default unchecked**: IngestionBatch
- **What it does**: Hide all nodes of that type from the graph
- **Note**: Hiding a type removes all connections to it

#### Importance Threshold Slider
- **Range**: 0% - 100%
- **Default**: 0% (show all)
- **Recommended**:
  - 0% (0.0) = All nodes (45K+)
  - 10% (0.1) = High-quality content (~5-8K nodes)
  - 20% (0.2) = Very important content (~2-3K nodes)
  - 30% (0.3) = Top-tier content (~500-1K nodes)
- **Note**: This is not applied until "Apply Filters" is clicked

#### Curated Topics Only
- **Checkbox**: "Curated Topics Only"
- **Default**: Off
- **What it does**: When searching for topics in the Topic Selector, only Tier 0-1 topics appear
- **Use case**: Start with high-level topics, then drill into details
- **Note**: Applies to both manual search and entity autocomplete

#### Apply Filters Button
- **What it does**: Submits the current filter settings to the backend
- **Reloads**: Graph data with new filters applied
- **Preserves**: Current entity selections and highlights
- **Loading time**: 1-5 seconds depending on filter selectivity

### Example Filter Scenarios

#### Scenario 1: Focus on Wi-Fi Standards
```
Node Types:  [✓] Resource, [✓] Topic, [✓] Organization, [✗] Person, [✗] Event, [✗] DataSource, [✗] IngestionBatch
Importance:  20% (0.2)
Curated Only: ON
Result:      ~1,000 nodes focused on major Wi-Fi topics and key resources
```

#### Scenario 2: Deep Dive into One Topic
```
1. Click "Filters" to disable Event and DataSource nodes
2. Search for "Wi-Fi 7" in Topics
3. Click it to load 2-hop neighborhood
4. Click "Hop" buttons to progressively expand
5. Graph shows: Wi-Fi 7 and everything related (no noise)
```

#### Scenario 3: High-Quality Content Only
```
Node Types:  All checked
Importance:  30% (0.3)
Curated Only: OFF
Result:      Only the most connected, highest-quality nodes (~300-500)
             Good for presentations or high-level overviews
```

## Technical Implementation

### Backend Changes

#### API Endpoint: `/graph/data`

New query parameters:
```
GET /graph/data?
  limit=1000
  &skip=0
  &node_types=Resource,Topic,Organization   # optional
  &importance_threshold=0.2                  # optional, default 0.0
  &curated_only=false                        # optional, default false
```

#### Response Metadata
```json
{
  "nodes": [...],
  "links": [...],
  "total_returned": 857,
  "importance_threshold": 0.2,
  "curated_only": false
}
```

### Neo4j Properties

#### `node.importance` (Float, 0.0 - 1.0)
Calculated once via migration script:
```cypher
# Topics: 0.3 base + connection multiplier
# Organizations: 0.2 base + connection multiplier
# Resources: 0.1 base + connection multiplier
# Others: 0.01 - 0.15 base + connection multiplier
```

#### `node.tier` (Integer, 0-2) [Topics only]
Set once via migration script:
```
Tier 0: Root topics (manually curated)
Tier 1: Children of Tier 0 topics
Tier 2: All other topics
```

### Frontend State

New App state variables:
```typescript
const [importanceThreshold, setImportanceThreshold] = useState(0.0);
const [curatedOnly, setCuratedOnly] = useState(false);
const [showFilterPanel, setShowFilterPanel] = useState(true);
const [hiddenNodeTypes, setHiddenNodeTypes] = useState(new Set(['IngestionBatch']));
```

New component: `FilterPanel.tsx`
- Handles all filter UI
- Calls `handleApplyFilters()` to reload graph
- Provides real-time visual feedback

## Running the Migration

Before using the filter features, populate the database with importance scores and tier levels:

```bash
# From kg_view/backend directory
cd /Users/bbonner/code/octo/octo-rapid-aurora/kg_view/backend

# Run the migration
python migrate_add_properties.py
```

Expected output:
```
Starting migration: Adding importance and tier properties...
✓ Set importance scores for 20456 nodes
✓ Set tier 0 (root) for 15 topics
✓ Set tier 1 (major) for 487 topics
✓ Set tier 2 (leaf) for 13498 topics
✓ Set tier 2 for 6456 non-topic nodes

✓ Migration completed successfully!
  • Total nodes updated: 20456
  • Tier 0 (root) nodes: 15
  • Tier 1 (major) nodes: 487
  • Tier 2 (leaf) nodes: 13498
  • Importance range: 0.010 - 0.897
  • Average importance: 0.175
```

## Performance Impact

### Load Times
- **Without filters** (show all ~45K nodes): Not recommended (browser may crash)
- **With default filters**: 1-2 seconds (1,000 nodes)
- **With importance 0.2**: 1-3 seconds (~800 nodes)
- **With importance 0.3**: 1-2 seconds (~400 nodes)

### Rendering
- Physics simulation: O(n²) pairwise forces
- 500 nodes: ~30 fps average
- 1000 nodes: ~15 fps average
- 2000 nodes: ~5-10 fps (sluggish but usable)
- 5000+ nodes: CPU-bound, not recommended

### Recommendations
- **Default view**: importance ≥ 0.1 (better UX)
- **Detailed exploration**: Start at 0.0, use node-type hiding for focus
- **Presentations**: Use 0.3+ threshold for clean visuals

## Future Optimizations

### Planned
1. **Hierarchical layout mode** - Replace force-directed with tree/hierarchy layout for 0-1 tiers
2. **Instanced rendering** - Use Three.js InstancedMesh for 5000+ node support
3. **Level-of-Detail (LOD)** - Render far nodes as dots, nearby nodes as full geometry
4. **Saved views** - Bookmark interesting filter combinations
5. **Time-based filtering** - Show only recent documents/events
6. **Relationship filtering** - Hide specific edge types (e.g., PUBLISHED_BY)

### Research
1. **Hierarchical clustering** - Group similar nodes, show/hide clusters
2. **Force-directed alternatives** - WebGL-based GPU force simulation
3. **Graph summarization** - Automatically create summary graphs for large datasets

## Troubleshooting

### Issue: "All nodes disappeared after applying filters"
**Solution**: Your importance threshold might be too high. Lower it to 0% and click "Apply Filters" again.

### Issue: "Graph is very slow/laggy"
**Solutions**:
1. Increase importance threshold (fewer nodes to render)
2. Hide node types you don't need (Person, Event, DataSource)
3. Use topic entity selection to focus on specific areas (loads 2-hop, ~200 nodes)

### Issue: "Can't find the topic I'm looking for"
**Cause**: "Curated Topics Only" is ON, filtering to Tier 0-1 only.
**Solution**: Uncheck "Curated Topics Only" to search all topics.

### Issue: "Migration failed with Neo4j error"
**Solutions**:
1. Ensure Neo4j is running: `docker ps | grep neo4j`
2. Check connection env vars: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
3. Run from correct directory (kg_view/backend)
4. Check Neo4j logs for errors: `docker logs aurora-neo4j`

## API Documentation

### GET /graph/data

Get graph nodes and relationships for visualization with smart filtering.

**Parameters**:
- `limit` (int, default=1000, max=10000): Max nodes to return
- `skip` (int, default=0): Pagination offset
- `node_types` (string, optional): Comma-separated node types (e.g., "Resource,Topic,Organization")
- `importance_threshold` (float, default=0.0, range 0-1): Min importance score
- `curated_only` (bool, default=false): Only return curated/tier 0-1 nodes

**Response**:
```json
{
  "nodes": [
    {
      "id": "4:uuid:123456",
      "label": "Topic",
      "name": "Wi-Fi 7",
      "importance": 0.85,
      "tier": 1,
      "properties": {...}
    }
  ],
  "links": [
    {
      "source": "4:uuid:123456",
      "target": "4:uuid:789012",
      "type": "DISCUSSES",
      "properties": {...}
    }
  ],
  "total_returned": 857,
  "importance_threshold": 0.0,
  "curated_only": false
}
```

### GET /autocomplete/topics

Get topics for autocomplete with optional tier filtering.

**Parameters**:
- `search` (string, default=""): Search text
- `limit` (int, default=50, max=100): Max results
- `curated_only` (bool, default=false): Only Tier 0-1 topics

**Response**:
```json
{
  "results": [
    {
      "id": "topic_123",
      "name": "Wi-Fi 7",
      "type": "topic",
      "classification": "technology",
      "tier": 1,
      "importance": 0.85
    }
  ]
}
```

## Questions or Issues?

See the main README.md in kg_view/ for architecture overview and contact information.
