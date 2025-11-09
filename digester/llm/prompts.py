"""Prompts for LLM metadata extraction."""


METADATA_EXTRACTION_PROMPT = """You are a metadata extraction expert. Analyze the following document and extract structured metadata.

Document Information:
- Title: {title}
- URL: {url}
- Resource Type: {resource_type}
- Source: {source}
- Publish Date: {publish_date}

Content (may be partial):
{content}

Extract the following metadata in JSON format:

1. **summary**: A concise 2-3 sentence summary of the document's main purpose and content
2. **topics**: List of relevant topics/subjects covered (e.g., "Wi-Fi 6E", "Network Security", "IoT Connectivity")
3. **standards**: List of technical standards mentioned (e.g., "IEEE 802.11ax", "WPA3", "Wi-Fi 6")
4. **standard_editions**: List of specific standard versions or editions (e.g., "802.11ax-2021", "WPA3-Personal")
5. **key_technologies**: List of key technologies discussed
6. **industry_sectors**: List of industry sectors relevant to this content
7. **use_cases**: List of practical applications or use cases mentioned

Return ONLY valid JSON in this exact format:
{{
  "summary": "...",
  "topics": ["topic1", "topic2", ...],
  "standards": ["standard1", "standard2", ...],
  "standard_editions": ["edition1", "edition2", ...],
  "key_technologies": ["tech1", "tech2", ...],
  "industry_sectors": ["sector1", "sector2", ...],
  "use_cases": ["usecase1", "usecase2", ...]
}}

Be specific and accurate. If a field has no relevant information, use an empty array [].
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

Return ONLY valid JSON in this exact format:
{{
  "summary": "...",
  "topics": ["topic1", "topic2", ...],
  "standards": ["standard1", "standard2", ...],
  "standard_editions": ["edition1", "edition2", ...],
  "key_technologies": ["tech1", "tech2", ...],
  "industry_sectors": ["sector1", "sector2", ...],
  "use_cases": ["usecase1", "usecase2", ...]
}}
"""
