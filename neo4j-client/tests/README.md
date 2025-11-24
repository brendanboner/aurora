# Deduplication Testing

This directory contains comprehensive tests for the node deduplication functionality.

## Overview

The deduplication system identifies and merges duplicate nodes (Topics, People, Organizations) in the knowledge graph using:
- Vector similarity search (embeddings)
- Name/identifier matching
- Type-specific features (aliases, email, etc.)
- Optional LLM review for uncertain cases

## Test Structure

### Test Fixtures (`test_deduplication_fixtures.json`)

Contains controlled test cases with known duplicates:

1. **IEEE 802.11 Variants** - Tests different spellings/formats of the same standard
   - "802.11", "ieee 802.11", "ieee802.11", "IEEE 802.11"
   - Should deduplicate to 1 unique node

2. **Wi-Fi 6E Variants** - Tests naming variations
   - "Wi-Fi 6E", "WiFi 6E", "802.11ax 6GHz"
   - Should deduplicate to 1 unique node

3. **Similar but Different** - Tests that distinct topics stay separate
   - Wi-Fi 6, Wi-Fi 6E, Wi-Fi 7
   - Should remain 3 unique nodes

4. **Organization Name Variants** - Tests org deduplication
   - "IEEE", "Institute of Electrical and Electronics Engineers", "I.E.E.E."
   - Should deduplicate to 1 unique node

5. **Person Name Variants** - Tests person deduplication with email matching
   - "John Smith", "John A. Smith", "J. Smith" (same email)
   - Should deduplicate to 1 unique node

6. **Similar Person Names** - Different people with similar names
   - Same name but different emails
   - Should remain separate

7. **Acronym Variations** - Full names vs acronyms
   - "Software Defined Networking", "SDN", "Software-Defined Networking"
   - Should deduplicate to 1 unique node

8. **Edge Cases** - Punctuation and spacing
   - "Wi-Fi", "WiFi", "wi-fi"
   - Should deduplicate to 1 unique node

### Test Script (`test_deduplication.py`)

Automated test runner that:
- Loads test fixtures
- Creates node instances
- Runs deduplication
- Verifies results against expected outcomes
- Reports pass/fail for each test case

## Running Tests

### Prerequisites

1. Neo4j database must be running (automatically managed by Makefile)
2. Environment variables from root `.env` file:
   
   **Neo4j Configuration:**
   ```bash
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=your_password
   NEO4J_DATABASE=neo4j
   ```

3. **Azure OpenAI Configuration (for LLM judgement):**
   ```bash
   AZURE_OPENAI_API_KEY=your_key
   AZURE_OPENAI_ENDPOINT=your_endpoint
   AZURE_OPENAI_API_VERSION=2024-10-21
   AZURE_OPENAI_DEPLOYMENT=your_deployment
   LLM_MAX_TOKENS=4096
   LLM_TEMPERATURE=0.1
   ```
   
   These variables are automatically loaded from `/Users/lsimone/repos/octo-rapid-aurora/.env` when using the Makefile.

### Using Make (Recommended)

The easiest way to run tests is using the Makefile from the `neo4j-client` directory:

```bash
cd /Users/lsimone/repos/octo-rapid-aurora/neo4j-client

# Run all tests
make test-all

# Run tests with verbose output
make run-test

# Run quick similarity tests (no Neo4j required)
make test-similarity

# Run specific test case
make test-case NAME="IEEE 802.11 Variants - Should Deduplicate"

# Run threshold sensitivity analysis
make test-thresholds

# See all available commands
make help
```

### Using Python Directly

You can also run the test scripts directly:

Run all tests with default thresholds (similarity=0.85, llm_review=0.6):

```bash
cd /Users/lsimone/repos/octo-rapid-aurora/neo4j-client/tests
python test_deduplication.py
```

### Run with Verbose Output

See detailed information about each test:

```bash
python test_deduplication.py --verbose
```

### Run Specific Test Case

Run only one test case by name:

```bash
python test_deduplication.py --test-case "IEEE 802.11 Variants - Should Deduplicate"
```

### Threshold Sensitivity Analysis

Test how different threshold values affect deduplication:

```bash
python test_deduplication.py --thresholds
```

This runs each test case with multiple threshold configurations:
- Very High: similarity=0.95, llm=0.75
- High: similarity=0.90, llm=0.70
- Medium (Default): similarity=0.85, llm=0.6
- Medium-Low: similarity=0.80, llm=0.60
- Low: similarity=0.75, llm=0.55

## Understanding Test Output

### Success

```
================================================================================
Running test: IEEE 802.11 Variants - Should Deduplicate
Description: Different representations of the same Wi-Fi standard should be identified as duplicates
================================================================================

✓ PASSED
Unique nodes: 1 (expected: 1)
Duplicates found: 3 (expected: 3)
```

### Failure

```
================================================================================
Running test: Wi-Fi 6E Variants - Should Deduplicate
Description: Different names for Wi-Fi 6E standard
================================================================================

✗ FAILED
Unique nodes: 2 (expected: 1)
Duplicates found: 1 (expected: 2)

Deduplication Details:
Original nodes: 3

  Node 1: Wi-Fi 6E
    Status: new_node
    Score: 0.000
    Best match: None

  Node 2: WiFi 6E
    Status: auto_merge
    Score: 0.923
    Best match: Wi-Fi 6E (ID: wi-fi-6e)

  Node 3: 802.11ax 6GHz
    Status: new_node
    Score: 0.750
    Best match: None
```

## Deduplication Metadata

All nodes that go through deduplication now store metadata about any duplicates found:

```python
# If a duplicate was found
topic.deduplication_best_match_id = "existing-topic-id"
topic.deduplication_best_match_name = "Existing Topic Name"
topic.deduplication_score = 0.923  # similarity score 0.0-1.0

# If no duplicate was found, these fields remain None
```

This metadata is useful for:
- Debugging deduplication decisions
- Understanding confidence levels
- Auditing merge operations
- Improving similarity algorithms

## Improving Deduplication

If tests fail, consider:

1. **Adjusting Thresholds**: Lower thresholds catch more duplicates but risk false positives
2. **Improving Name Similarity**: Enhance `_calculate_name_similarity()` to handle:
   - Punctuation variations ("Wi-Fi" vs "WiFi")
   - Spacing differences ("ieee 802.11" vs "ieee802.11")
   - Common prefixes/suffixes ("IEEE" before numbers)
3. **Better Embeddings**: The embedding model affects vector similarity
4. **Feature Weights**: Adjust weights in `_score_duplicates()` for different node types
5. **Alias Expansion**: Include more aliases in test fixtures to test alias matching

## Current Scoring Algorithm

The deduplication score is calculated as:

```
Total Score = (Vector Similarity × 0.5) + (Name Similarity × 0.3) + (Type-Specific × 0.2)

Where Type-Specific is:
- Topics/Organizations: Alias overlap
- People: Email match
- If type-specific feature unavailable: Name gets full 50% weight
```

Thresholds:
- Score >= 0.85: Automatic merge
- Score 0.6-0.85: Send to LLM for review
- Score < 0.6: Treat as new node

## Adding New Test Cases

To add new test cases, edit `test_deduplication_fixtures.json`:

```json
{
  "name": "Your Test Name",
  "description": "What this test verifies",
  "topics": [
    {
      "name": "Topic Name",
      "classification": "standard",
      "identifier": "ID-123",
      "issuer": "Issuer Org",
      "aliases": ["Alias1", "Alias2"]
    }
  ],
  "expected_unique_count": 1,
  "expected_duplicates": 2
}
```

## Integration with Services

The deduplication is used by:
- **Digester**: Batch processing of resources (calls `deduplicate_nodes()`)
- **Curator**: Individual node checking (calls `check_topic_duplicate()`, etc.)
- **API**: Direct node insertion with duplicate checking

All of these will now populate the deduplication metadata fields automatically.
