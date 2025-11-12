"""Prompts for LLM metadata extraction."""


METADATA_EXTRACTION_PROMPT = """You are a metadata extraction expert. Analyze the following document and extract structured metadata.

Document Information:
- Title: {title}
- URL: {url}
- Category: {category}
- Datasource ID: {datasource_id}
- Publish Date: {publish_date}

Content (may be partial):
{content}

Extract the following metadata in JSON format:

1. **summary**: A concise 2-3 sentence summary of the document's main purpose and content
2. **topics**: List of top 5 most relevant topics/subjects covered with confidence and relevance scores
   - Maximum 5 topics per resource
   - Each topic should have: name, confidence (0.0-1.0), relevance (0.0-1.0)
   - confidence: How confident you are the content relates to this topic (0.0 = not confident, 1.0 = very confident)
   - relevance: How relevant this topic is to the document (0.0 = not relevant, 1.0 = very relevant)
3. **standards**: List of technical standards mentioned with confidence scores
   - Each standard should have: name, confidence (0.0-1.0)
   - confidence: How confident you are this standard is mentioned or referenced
4. **standard_editions**: List of specific standard versions or editions with confidence scores
   - Each edition should have: name, confidence (0.0-1.0)

Return ONLY valid JSON in this exact format:
{{
  "summary": "...",
  "topics": [
    {{"name": "topic1", "confidence": 0.95, "relevance": 0.85}},
    {{"name": "topic2", "confidence": 0.78, "relevance": 0.92}}
  ],
  "standards": [
    {{"name": "standard1", "confidence": 0.90}},
    {{"name": "standard2", "confidence": 0.85}}
  ],
  "standard_editions": [
    {{"name": "edition1", "confidence": 0.88}},
    {{"name": "edition2", "confidence": 0.75}}
  ]
}}

Important guidelines:
- Limit topics to maximum 5 most relevant items
- Be specific and accurate
- All confidence and relevance scores must be between 0.0 and 1.0
- If a field has no relevant information, use an empty array []
- Only include a standard edition if the edition/version is explicitly mentioned in the content. General standard references are included under standards.
"""


METADATA_MERGE_PROMPT = """You have multiple metadata extractions from different chunks of the same document. Merge them intelligently into a single, coherent metadata set.

Document Title: {title}

Extracted Metadata from Chunks:
{chunks_metadata}

Create a unified metadata extraction that:
1. Combines all unique items from lists (topics, standards, etc.)
2. Creates a comprehensive summary that captures the full document scope
3. Removes duplicates and near-duplicates
4. Keeps only the most relevant and accurate information
5. Limits topics to maximum 5 most relevant items
6. For topics/standards with multiple confidence/relevance scores, average them appropriately

Return ONLY valid JSON in this exact format:
{{
  "summary": "...",
  "topics": [
    {{"name": "topic1", "confidence": 0.95, "relevance": 0.85}},
    {{"name": "topic2", "confidence": 0.78, "relevance": 0.92}}
  ],
  "standards": [
    {{"name": "standard1", "confidence": 0.90}},
    {{"name": "standard2", "confidence": 0.85}}
  ],
  "standard_editions": [
    {{"name": "edition1", "confidence": 0.88}},
    {{"name": "edition2", "confidence": 0.75}}
  ]
}}

Important guidelines:
- Limit topics to maximum 5 most relevant items
- Ensure all confidence scores are between 0.0 and 1.0
- For duplicate topics/standards, merge them and average their scores
"""
