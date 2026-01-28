# Aurora Curator Service

The Curator service is responsible for organizing and maintaining the knowledge graph by creating hierarchical relationships between topics. It uses machine learning clustering and LLM-based analysis to identify broader-than and narrower-than relationships.

## Purpose

The curator service periodically analyzes topics in the knowledge graph and organizes them into a hierarchical structure. This helps:

- Create semantic relationships between related topics
- Enable navigation through topic hierarchies (e.g., "Wi-Fi 6E" → "Wi-Fi" → "Wireless Networking")
- Improve knowledge graph querying and exploration
- Support better content recommendations based on topic relationships

## Architecture

The curator service follows a multi-step process:

### 1. Topic Retrieval
Retrieves topics from the Neo4j knowledge graph along with their embedding vectors. 

**Important**: By default, the service processes **ALL topics** (not just unorganized ones) to ensure a unified hierarchy. This is critical because:

- **Fragmentation Problem**: If you only process unorganized topics, each day's new topics would form isolated clusters that don't relate to existing topics
- **Example**: Day 1's 100 topics get organized, then Day 2's 100 topics form a separate hierarchy, creating disconnected knowledge islands
- **Solution**: Re-processing all topics allows new topics to integrate with existing ones through clustering

The service can optionally target only topics without existing hierarchy, but this is **not recommended** for production use as it creates fragmented hierarchies.

### 2. Clustering
Uses **Agglomerative Clustering** with **overlapping clusters** to group semantically similar topics:
- Computes cosine distances between topic embeddings
- Performs hierarchical clustering with configurable distance threshold
- Refines cluster sizes to meet min/max constraints (default: 3-10 topics per cluster)
- **Adds overlap**: Each cluster gets augmented with its k nearest external topics (default: 3)
- This ensures topics from different domains can be compared for cross-cluster relationships

**Example of Overlapping Clusters**:
```
Original Cluster 1: ["Wi-Fi", "Wi-Fi 6", "Wi-Fi 6E"]
  + Overlaps: ["Wireless Standards", "Bluetooth", "IEEE 802.11"]
  = Extended Cluster 1: 6 topics

Original Cluster 2: ["Wireless Standards", "IEEE 802.11", "Bluetooth"]  
  + Overlaps: ["Wi-Fi", "5G", "NFC"]
  = Extended Cluster 2: 6 topics

Note: "Wi-Fi" and "Wireless Standards" now both appear in both clusters!
```

### 3. Intra-Cluster Analysis
Sends each overlapping cluster to an Azure OpenAI LLM to identify **ENCOMPASSES** relationships:
- LLM analyzes which topics encompass (contain/include) other topics
- Only asks for ENCOMPASSES direction (broader → narrower)
- Automatically creates reciprocal SUBTOPIC_OF relationships
- Provides confidence scores and reasoning for each relationship
- Filters relationships below confidence threshold

**Clearer Semantics**: Instead of "broader than" / "narrower than", we use:
- **ENCOMPASSES**: Topic A encompasses Topic B (A is a category that includes B)
- **SUBTOPIC_OF**: Automatically created reciprocal (B is a subtopic of A)

**Example Relationships**:
```
"Wireless Standards" ENCOMPASSES "Wi-Fi" (confidence: 0.95)
  → Auto-creates: "Wi-Fi" SUBTOPIC_OF "Wireless Standards"

"Wi-Fi" ENCOMPASSES "Wi-Fi 6E" (confidence: 0.98)
  → Auto-creates: "Wi-Fi 6E" SUBTOPIC_OF "Wi-Fi"
```

### 3.5. Cross-Cluster Analysis (New!)
Analyzes cluster representatives to identify high-level relationships **across clusters**:
- Extracts the most central topic from each cluster as its representative
- Sends representatives to LLM for cross-cluster relationship analysis
- Catches relationships that span different topic domains

**Example**: Identifies that "Wireless Standards" (Cluster 1 rep) is broader than "Wi-Fi" (Cluster 2 rep)

**Why this matters**: Without cross-cluster analysis, you might miss important hierarchical relationships:
```
Cluster 1: ["Wi-Fi", "Wi-Fi 6", "Wi-Fi 6E"]
  → Wi-Fi --ENCOMPASSES--> Wi-Fi 6

Cluster 2: ["Wireless Standards", "IEEE 802.11", "Bluetooth"]  
  → Wireless Standards --ENCOMPASSES--> IEEE 802.11

❌ WITHOUT cross-cluster: Missing "Wireless Standards --ENCOMPASSES--> Wi-Fi"
✅ WITH cross-cluster: Finds the connection between cluster representatives
```

### 4. Relationship Insertion
Inserts validated relationships into the Neo4j knowledge graph:
- Creates `ENCOMPASSES` relationships (A is a broader category that includes B)
- Automatically creates reciprocal `SUBTOPIC_OF` relationships (B is a subtopic of A)
- Validates all relationships reference existing topics
- Uses Neo4j MERGE to handle duplicate relationships gracefully (idempotent)
- Logs statistics and errors

**Relationship Types**:
- `ENCOMPASSES` (A → B): A is a broader topic that includes B (includes reasoning and confidence)
- `SUBTOPIC_OF` (B → A): B is a more specific topic within A (auto-created reciprocal with confidence)

## Important Considerations

### Unified vs. Fragmented Hierarchies

**The curator processes ALL topics by default** to maintain a unified knowledge graph hierarchy. This is essential because:

1. **Why process all topics?**
   - New topics can relate to existing topics (e.g., "Wi-Fi 7" should connect to existing "Wi-Fi" and "Wireless Standards")
   - Clustering only new topics would create isolated hierarchies each day
   - A unified graph enables better querying and navigation

2. **Duplicate Relationships**
   - Re-processing existing topics may identify the same relationships again
   - Neo4j's MERGE operation handles this gracefully (idempotent updates)
   - No harm in re-creating existing relationships

3. **Performance Considerations**
   - For large graphs (1000+ topics), processing all topics can be expensive
   - Consider running less frequently (weekly instead of daily)
   - Future optimization: Track and skip "stable" clusters that haven't changed

4. **Example Scenario**:
   ```
   Day 1: 100 topics → Creates hierarchy A
   Day 2: 100 new topics
   
   ❌ Process only new topics:
      → Creates separate hierarchy B (disconnected from A)
      → "Wi-Fi 7" doesn't connect to existing "Wi-Fi" topic
   
   ✅ Process all 200 topics:
      → New topics integrate into unified hierarchy
      → "Wi-Fi 7" correctly connects to "Wi-Fi" and "Wireless Standards"
   ```

### Automatic Scaling Mode

The curator automatically switches between **full** and **incremental** curation modes based on the total number of topics in the knowledge graph:

- **Below threshold (default: 4000 topics)**: **FULL MODE** - processes all topics to ensure unified hierarchy
- **Above threshold**: **INCREMENTAL MODE** - builds context clusters around unorganized topics

**How Incremental Mode Works:**

Instead of clustering only unorganized topics (which would create isolated hierarchies), incremental mode:

1. **Identifies seed topics**: Gets all unorganized topics (those without ENCOMPASSES/SUBTOPIC_OF relationships)
2. **Builds context clusters**: For each seed topic, finds its nearest neighbors from ALL topics (including already-organized ones)
3. **Integrates into hierarchy**: The LLM sees the new topic alongside relevant existing topics and can properly place it in the hierarchy

**Example:**
```
New unorganized topic: "Wi-Fi 7"

Context cluster built around it:
  - Wi-Fi 7 (seed - unorganized)
  - Wi-Fi 6E (neighbor - organized, already under "Wi-Fi")
  - Wi-Fi 6 (neighbor - organized, already under "Wi-Fi")
  - Wi-Fi (neighbor - organized, under "Wireless Standards")
  
→ LLM correctly places: "Wi-Fi" ENCOMPASSES "Wi-Fi 7"
→ New topic integrates into existing hierarchy!
```

This dramatically reduces LLM calls for large knowledge graphs while maintaining hierarchy quality:

| Topic Count | Mode | Topics Processed | Estimated LLM Calls |
|-------------|------|------------------|---------------------|
| 1,000 | Full | 1,000 | ~200 |
| 4,000 | Full | 4,000 | ~800 |
| 10,000 | Incremental | ~50-100 new | ~20-40 |
| 50,000 | Incremental | ~50-100 new | ~20-40 |

Configure the threshold via environment variable:
```bash
INCREMENTAL_CURATION_THRESHOLD=4000  # Default, switch modes at 4000 topics
INCREMENTAL_CURATION_THRESHOLD=0     # Always use full mode (not recommended for large graphs)
INCREMENTAL_CURATION_THRESHOLD=999999 # Always use incremental mode
```

### Scheduling Recommendations

- **Small graphs (<500 topics)**: Run daily with all topics
- **Medium graphs (500-4000 topics)**: Run 2-3 times per week with all topics
- **Large graphs (4000+ topics)**: Automatic incremental mode kicks in - safe to run daily

## Cross-Cluster Analysis

### What Problem Does It Solve?

When topics are clustered for LLM analysis, each cluster is analyzed independently. This creates a blind spot: **topics in different clusters never get compared to each other**.

**Example Problem**:
```
Cluster 1 (Wi-Fi Topics):
  - Wi-Fi
  - Wi-Fi 6
  - Wi-Fi 6E
  - Wi-Fi 7
  
Cluster 2 (Standards):
  - Wireless Standards
  - IEEE 802.11
  - Bluetooth

WITHOUT cross-cluster analysis:
  ✅ Finds: Wi-Fi --BROADER_THAN--> Wi-Fi 6
  ❌ Misses: Wireless Standards --BROADER_THAN--> Wi-Fi
```

### How It Works

1. **Extract Representatives**: After clustering, find the most central topic in each cluster
   - Uses the topic closest to the cluster's embedding centroid
   - Represents the "essence" of that cluster

2. **Batch if Needed**: Check the number of representatives
   - **≤10 representatives**: Analyze all together in one LLM call
   - **>10 representatives**: Cluster the representatives into "meta-clusters" of max 10 each
   - This ensures we never overwhelm the LLM with too many topics

3. **Analyze Representatives**: Send representatives (or meta-clusters) to the LLM
   - Representatives from different clusters can now be compared
   - LLM identifies high-level relationships between topic domains

4. **Combine Results**: Merge cross-cluster relationships with intra-cluster relationships

**Example**:
```
Scenario 1: Few clusters (≤10)
────────────────────────────────
Step 1: Intra-cluster analysis (5 clusters)
  Cluster 1 → "Wi-Fi" is most central
  Cluster 2 → "Wireless Standards" is most central
  Cluster 3 → "Network Security" is most central
  Cluster 4 → "Cloud Computing" is most central
  Cluster 5 → "IoT" is most central

Step 2: Cross-cluster analysis (all together)
  Representatives: ["Wi-Fi", "Wireless Standards", "Network Security", "Cloud Computing", "IoT"]
  → Single LLM call analyzes all 5 representatives
  LLM identifies: Wireless Standards --BROADER_THAN--> Wi-Fi

Step 3: Result
  ✅ Complete hierarchy spans across clusters!


Scenario 2: Many clusters (>10)
────────────────────────────────
Step 1: Intra-cluster analysis (100 clusters)
  100 clusters → 100 representatives

Step 2: Meta-clustering (cluster the representatives)
  100 representatives → 10 meta-clusters of ~10 representatives each
  
  Meta-cluster 1: ["Wi-Fi", "Bluetooth", "Zigbee", "LoRaWAN", ...]
  Meta-cluster 2: ["Cloud Computing", "AWS", "Azure", "GCP", ...]
  Meta-cluster 3: ["Network Security", "Firewall", "VPN", ...]
  ...

Step 3: Cross-cluster analysis (analyze each meta-cluster)
  → 10 LLM calls (one per meta-cluster)
  Each analyzes ~10 representatives
  
Step 4: Result
  ✅ Scalable cross-cluster analysis even with 100+ clusters!
```

### Configuration

Enable/disable via `ENABLE_CROSS_CLUSTER_ANALYSIS`:
- `true` (default): Full coverage, catches cross-cluster relationships
- `false`: Faster, lower cost, but may miss some relationships

### Cost Impact

- **Small graphs (<10 clusters)**: 1 extra LLM call (analyzing representatives)
- **Medium graphs (10-50 clusters)**: 2-5 extra LLM calls (meta-clustering representatives)
- **Large graphs (50+ clusters)**: ~10% increase in LLM calls (proportional to cluster count)
- **Still minimal**: Much cheaper than processing all topic pairs
- **Worth it**: Catches important high-level relationships that would otherwise be missed

### Scalability

The implementation automatically scales:
- **≤10 representatives**: Single analysis (most common case)
- **>10 representatives**: Meta-clustering kicks in
  - 100 clusters → ~10 meta-clusters → ~10 additional LLM calls
  - 1000 clusters → ~100 meta-clusters → ~100 additional LLM calls
- Respects `CLUSTER_MAX_SIZE` setting at all levels

## Configuration

All configuration is managed through environment variables (`.env` file):

### Required Settings

```bash
# Neo4j Configuration
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
NEO4J_DATABASE=neo4j

# Azure OpenAI Configuration (Required for LLM analysis)
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your_deployment_name
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

### Optional Settings

```bash
# Clustering Parameters
CLUSTER_MIN_SIZE=3                    # Minimum topics per cluster
CLUSTER_MAX_SIZE=10                   # Maximum topics per cluster
CLUSTER_DISTANCE_THRESHOLD=0.5        # Cosine distance threshold for clustering
CLUSTER_OVERLAP_NEIGHBORS=3           # Number of nearest external topics to add to each cluster

# Hierarchy Analysis
HIERARCHY_CONFIDENCE_THRESHOLD=0.7    # Minimum confidence to accept relationships
LLM_MAX_TOKENS=4096                   # Maximum tokens for LLM response
LLM_TEMPERATURE=0.1                   # LLM temperature (lower = more deterministic)
ENABLE_CROSS_CLUSTER_ANALYSIS=true   # Analyze cluster representatives for cross-cluster relationships

# Scaling / Curation Mode
INCREMENTAL_CURATION_THRESHOLD=4000   # Switch to incremental mode above this topic count
                                      # Below threshold: process ALL topics (unified hierarchy)
                                      # Above threshold: process only UNORGANIZED topics (efficient)
                                      # Set to 0 to always use full mode
                                      # Set very high to always use incremental mode

# Logging
LOG_LEVEL=INFO                        # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Usage

### Running with Docker (Recommended)

#### Isolated Mode
Run with its own network and Neo4j instance (good for testing):

```bash
cd curator
make run-isolated
```

This will:
1. Build the curator Docker image
2. Create an isolated network
3. Start a fresh Neo4j instance
4. Run the curator service
5. Clean up when complete

#### Shared Mode
Run on the shared network with existing Neo4j instance:

```bash
cd curator
make run-shared
```

This will:
1. Build the curator Docker image
2. Ensure shared network exists
3. Ensure Neo4j is running on shared network
4. Run the curator service

### Running Locally

```bash
cd curator

# Install dependencies
pip install -r requirements.txt
pip install -e ../neo4j-client

# Run the service
python main.py
```

### Running as Scheduled Task

The curator service is designed to be run periodically (e.g., daily) to maintain the knowledge graph. You can:

1. **Cron Job** (Linux/macOS):
```bash
# Run daily at 2 AM
0 2 * * * cd /path/to/curator && make run-shared >> /var/log/curator.log 2>&1
```

2. **Kubernetes CronJob** (for production):
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: aurora-curator
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: curator
            image: aurora-curator:latest
            env:
              - name: NEO4J_URI
                value: "bolt://neo4j:7687"
              # ... other env vars
          restartPolicy: OnFailure
```

## Components

### Main Service (`main.py`)
- `CuratorService`: Orchestrates the entire curation workflow
- Coordinates clustering, LLM analysis, and graph updates
- Provides comprehensive logging and error handling

### Clustering (`clustering.py`)
- `TopicClusterer`: Implements agglomerative clustering
- Handles cluster size refinement
- Provides utility methods for cluster analysis

### LLM Analysis (`llm/`)
- `HierarchyAnalyzer`: Interfaces with Azure OpenAI
- `prompts.py`: Contains system and user prompts for LLM
- Validates LLM responses and filters by confidence

### Utilities (`utils/`)
- `logger.py`: Logging setup and configuration

## Data Models

The service uses the following Neo4j models (from `neo4j-client`):

### Nodes
- `Topic`: Represents a topic with embeddings
  - `topic_id`: Unique identifier
  - `name`: Human-readable name
  - `classification`: Topic type
  - `embedding`: Vector embedding for similarity

### Relationships
- `TopicBroaderThan`: A → B (A is broader than B)
  - Links general topics to more specific ones
  
- `TopicNarrowerThan`: A → B (A is narrower than B)
  - Links specific topics to more general ones

## Example Output

```
================================================================================
Starting topic hierarchy organization
================================================================================
Step 1: Retrieving topics from knowledge graph...
Processing ALL topics to ensure unified hierarchy
Retrieved 45 total topics
Sample topics: ['Wi-Fi 6E', 'Network Security', 'Cloud Computing', '5G', 'IoT']

Step 2: Clustering topics by semantic similarity...
Initial clustering produced 6 clusters (sizes: [12, 8, 9, 7, 6, 3])
Final clustering: 5 clusters (sizes: [12, 8, 9, 10, 6])
  Cluster 1: 12 topics - ['Wi-Fi', 'Wi-Fi 6', 'Wi-Fi 6E']...
  Cluster 2: 8 topics - ['Network Security', 'Firewall', 'VPN']...
  Cluster 3: 9 topics - ['Cloud Computing', 'AWS', 'Azure']...
  Cluster 4: 10 topics - ['Wireless Standards', 'IEEE 802.11', 'Bluetooth']...
  Cluster 5: 6 topics - ['IoT', 'Smart Home', 'Sensors']...

Step 3: Analyzing clusters with LLM to identify hierarchies...
Analyzing cluster 1/5
  wi-fi --BROADER_THAN--> wi-fi-6e (confidence: 0.95)
  wi-fi-6e --NARROWER_THAN--> wi-fi (confidence: 0.95)
  ...
Analyzed 5 clusters, found 38 total relationships
Identified 38 intra-cluster relationships

Step 3.5: Analyzing cluster representatives for cross-cluster relationships...
  Cluster 1 representative: Wi-Fi
  Cluster 2 representative: Network Security
  Cluster 3 representative: Cloud Computing
  Cluster 4 representative: Wireless Standards
  Cluster 5 representative: IoT

Total representatives: 5
Analyzing all 5 representatives in one batch
Analyzing 5 cluster representatives for cross-cluster relationships
Found 4 cross-cluster relationships
  wireless-standards --BROADER_THAN--> wi-fi (confidence: 0.92)
  wireless-standards --BROADER_THAN--> bluetooth (confidence: 0.88)
  network-security --BROADER_THAN--> vpn (confidence: 0.85)
  iot --NARROWER_THAN--> smart-home (confidence: 0.78)

Total relationships: 42 (38 intra-cluster + 4 cross-cluster)
Validated 42/42 relationships

Step 4: Inserting 42 relationships into knowledge graph...
Created BROADER_THAN: wireless-standards -> wi-fi (confidence: 0.92)
Created BROADER_THAN: wi-fi -> wi-fi-6e (confidence: 0.95)
...

================================================================================
Topic hierarchy organization complete!
  Topics processed: 45
  Clusters created: 5
  Cluster representatives analyzed: 5
  Intra-cluster relationships: 38
  Cross-cluster relationships: 4
  Total relationships identified: 42
  Relationships validated: 42
  BROADER_THAN relationships inserted: 21
  NARROWER_THAN relationships inserted: 21
  Errors: 0
================================================================================
```

### Example with Many Clusters (Meta-Clustering)

```
Step 3.5: Analyzing cluster representatives for cross-cluster relationships...
  Cluster 1 representative: Wi-Fi
  Cluster 2 representative: Bluetooth
  ... (extracting representatives from all 25 clusters)
  Cluster 25 representative: API Gateway

Total representatives: 25
Too many representatives (25) for single analysis. Clustering representatives into meta-clusters...
Created 3 meta-clusters from representatives
  Meta-cluster 1: 10 representatives - ['Wi-Fi', 'Bluetooth', 'Zigbee']...
  Meta-cluster 2: 8 representatives - ['Cloud Computing', 'AWS', 'Azure']...
  Meta-cluster 3: 7 representatives - ['Network Security', 'Firewall', 'VPN']...
Found 12 relationships across 3 meta-clusters

Total relationships: 50 (38 intra-cluster + 12 cross-cluster)
```

## Troubleshooting

### No topics found to organize
- Check that topics exist in Neo4j
- Verify Neo4j connection settings
- Run digester service first to populate topics

### Clustering produces no clusters
- Ensure topics have valid embeddings
- Adjust `CLUSTER_DISTANCE_THRESHOLD` (try lower values)
- Check minimum topic count (need at least 3 topics)

### LLM returns no relationships
- Verify Azure OpenAI credentials
- Check if topics in clusters are actually related
- Lower `HIERARCHY_CONFIDENCE_THRESHOLD`
- Review LLM prompts in `llm/prompts.py`

### Relationship insertion fails
- Verify topic IDs exist in Neo4j
- Check Neo4j connection and permissions
- Review Neo4j logs for constraint violations

## Future Enhancements

The curator service is designed to be extensible. Future curation functions could include:

1. **Synonym Detection**: Identify and merge duplicate topics with different names
2. **Relationship Validation**: Detect and remove invalid or outdated relationships
3. **Quality Scoring**: Assign quality scores to topics based on content richness
4. **Orphan Detection**: Find and organize disconnected topics
5. **Taxonomy Alignment**: Align topics with external taxonomies or ontologies
6. **Cross-reference Validation**: Ensure person/organization affiliations are current

## Dependencies

- Python 3.13+
- Neo4j 5.x with APOC plugins
- Azure OpenAI API access
- scikit-learn (for clustering)
- sentence-transformers (for embeddings)
- pydantic (for configuration)

## License

Part of the Aurora knowledge graph project.
