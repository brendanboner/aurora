"""
LLM-based hierarchy analysis prompts.

This module contains the prompts used by the HierarchyAnalyzer to identify
broader-than and narrower-than relationships between topics.
"""

HIERARCHY_ANALYSIS_SYSTEM_PROMPT = """
You are an expert knowledge graph curator specializing in creating topic hierarchies.
Your task is to analyze a subset of related topics and identify which topics ENCOMPASS other topics. Ultimately, these topics will be used to create a topic hierarchy in a knowledge graph.

Guidelines for identifying encompassing relationships:
1. **Topic A ENCOMPASSES Topic B** when:
   - A is a broader category or field that includes B
   - B is a specific instance, type, subset, or specialization of A
   - A represents a general concept while B represents a more specific concept within that domain
   - Examples:
     * "Wireless Standards" encompasses "Wi-Fi"
     * "Wi-Fi" encompasses "Wi-Fi 6E"
     * "Network Security" encompasses "Firewalls"
     * "Cloud Computing" encompasses "AWS"

2. **Important considerations**:
   - Only identify ENCOMPASSES relationships (we'll create the reciprocal SUBTOPIC_OF automatically)
   - Focus on direct parent-child relationships (avoid transitive: if A→B→C, don't create A→C)
   - A topic can be encompassed by multiple broader topics (e.g., "Wi-Fi Security" is encompassed by both "Wi-Fi" and "Network Security")
   - Not all topics in a cluster will have encompassing relationships
   - Be conservative - only create relationships when the encompassing relationship is clear and meaningful

3. **Confidence scoring**:
   - Use confidence scores from 0.0 to 1.0
   - 0.9-1.0: Very clear encompassing relationship (e.g., "Wi-Fi" encompasses "Wi-Fi 6")
   - 0.7-0.9: Strong encompassing relationship with minor ambiguity
   - 0.5-0.7: Moderate encompassing relationship
   - Below 0.5: Weak or unclear relationship (don't include these)

4. **What to avoid**:
   - Sibling relationships (topics at the same level of specificity)
   - Associative relationships (related but not hierarchical)
   - Circular relationships (A encompasses B, B encompasses A)
   
You must respond with valid JSON only, no additional text or explanations.
"""


HIERARCHY_ANALYSIS_USER_PROMPT = """
Analyze the following cluster of related topics and identify ENCOMPASSES relationships.

Topics in cluster:
{topics_json}

Instructions:
1. Review all topics in the cluster
2. Identify which topics ENCOMPASS other topics (broader categories that include more specific ones)
3. Only identify the ENCOMPASSES direction (we'll create reciprocal SUBTOPIC_OF automatically)
4. Assign confidence scores (0.5-1.0) to each relationship
5. Provide brief evidence/reasoning for each relationship

Respond with JSON in this exact format:
{{
  "relationships": [
    {{
      "source_topic_id": "encompassing-topic-id",
      "target_topic_id": "subtopic-id",
      "relationship_type": "ENCOMPASSES",
      "confidence": 0.95,
      "reasoning": "Brief explanation of why source topic encompasses target topic"
    }}
  ]
}}

Notes:
- Only include ENCOMPASSES relationships (not SUBTOPIC_OF - that's automatic)
- Only include relationships with confidence >= 0.5
- Focus on direct parent-child relationships within this cluster
- If no clear encompassing relationships exist, return an empty relationships array

Example:
- "Wireless Standards" ENCOMPASSES "Wi-Fi" (confidence: 0.95)
- "Wi-Fi" ENCOMPASSES "Wi-Fi 6E" (confidence: 0.98)
- Do NOT also add "Wi-Fi 6E" SUBTOPIC_OF "Wi-Fi" - that will be created automatically
"""


def format_topics_for_prompt(topics: list) -> str:
    """
    Format topics for inclusion in the LLM prompt.
    
    Args:
        topics: List of topic dictionaries
        
    Returns:
        JSON-formatted string of topics with relevant information
    """
    import json
    
    formatted_topics = []
    for topic in topics:
        formatted_topic = {
            "topic_id": topic.get("topic_id", ""),
            "name": topic.get("name", ""),
            "classification": topic.get("classification", ""),
        }
        
        # Add optional fields if they exist
        if topic.get("identifier"):
            formatted_topic["identifier"] = topic["identifier"]
        if topic.get("issuer"):
            formatted_topic["issuer"] = topic["issuer"]
        
        formatted_topics.append(formatted_topic)
    
    return json.dumps(formatted_topics, indent=2)


# ============================================================================
# Conflict Resolution Prompts
# ============================================================================

CONFLICT_RESOLUTION_SYSTEM_PROMPT = """
You are an expert knowledge graph curator specializing in resolving hierarchical conflicts.

Your task is to analyze three topics where existing relationships suggest a potential conflict, and determine the correct hierarchical structure.

You will be presented with:
1. Three topics (A, B, C) that have conflicting relationships
2. Existing relationships between them
3. A proposed new relationship that conflicts with the existing structure

Your job is to determine:
- Are these topics truly hierarchical (parent-child) or are they siblings?
- If hierarchical, what is the correct ordering?
- Should any existing relationships be removed to create the proper structure?

Guidelines:
1. **Hierarchy principles**:
   - Topics should form a clean hierarchy: general → specific → more specific
   - Siblings share a common parent but are at the same level of specificity
   - Avoid redundant relationships (if A→B→C, don't also have A→C)

2. **Common conflict scenarios**:
   - **Scenario 1**: Common parent conflict (A→B, A→C exist, proposed B→C)
     * If B is more general than C: Create A→B→C (remove A→C, add B→C)
     * If B and C are siblings: Keep A→B and A→C (reject B→C)
   
   - **Scenario 2**: Common child conflict (A→C, B→C exist, proposed A→B)
     * If A is more general than B: Create A→B→C (remove A→C, add A→B)
     * If A and B are siblings: Keep A→C and B→C (reject A→B)

3. **Decision criteria**:
   - Semantic relationship: Does one topic truly encompass the other?
   - Specificity: Is one topic clearly more specific/specialized?
   - Scope: Does one topic have broader scope than the other?

You must respond with valid JSON only, no additional text or explanations.
"""


CONFLICT_RESOLUTION_USER_PROMPT = """
Analyze the following hierarchical conflict and determine the correct structure.

CONFLICT TYPE: {conflict_type}

TOPICS:
{topics_json}

EXISTING RELATIONSHIPS:
{existing_relationships}

PROPOSED NEW RELATIONSHIP:
{proposed_relationship}

CONFLICT DESCRIPTION:
{conflict_description}

Your task:
1. Analyze the semantic relationships between these three topics
2. Determine if they form a hierarchy (A→B→C) or if some are siblings
3. Decide whether to accept the proposed relationship and potentially restructure

Respond with JSON in this exact format:
{{
  "decision": "remodel" | "keep_existing" | "accept_proposed",
  "reasoning": "Detailed explanation of your decision based on topic semantics",
  "final_structure": [
    {{"parent": "topic_id", "child": "topic_id"}},
    ...
  ],
  "relationships_to_remove": [
    {{"parent": "topic_id", "child": "topic_id"}},
    ...
  ],
  "relationships_to_add": [
    {{"parent": "topic_id", "child": "topic_id"}},
    ...
  ],
  "confidence": 0.85
}}

Decision types:
- "remodel": Restructure to create proper hierarchy (e.g., A→B→C)
- "keep_existing": Reject proposed relationship, keep current structure (topics are siblings)
- "accept_proposed": Add the proposed relationship to existing ones

Example responses:

If B is more specific than C under common parent A:
{{
  "decision": "remodel",
  "reasoning": "B represents a more specialized concept than C. Both fall under A, but B→C creates a clearer hierarchy.",
  "final_structure": [
    {{"parent": "A", "child": "B"}},
    {{"parent": "B", "child": "C"}}
  ],
  "relationships_to_remove": [
    {{"parent": "A", "child": "C"}}
  ],
  "relationships_to_add": [
    {{"parent": "B", "child": "C"}}
  ],
  "confidence": 0.90
}}

If B and C are siblings under A:
{{
  "decision": "keep_existing",
  "reasoning": "B and C are parallel concepts at the same level of specificity under A. Neither encompasses the other.",
  "final_structure": [
    {{"parent": "A", "child": "B"}},
    {{"parent": "A", "child": "C"}}
  ],
  "relationships_to_remove": [],
  "relationships_to_add": [],
  "confidence": 0.95
}}
"""


# ============================================================================
# General Topic Suggestion Prompts
# ============================================================================

GENERAL_TOPIC_SUGGESTION_SYSTEM_PROMPT = """
You are an expert knowledge graph curator specializing in creating well-organized topic hierarchies.

Your task is to analyze a cluster of related topics and determine if they would benefit from one or more general/umbrella topics to organize them hierarchically.

Guidelines:
1. **When to suggest a general topic**:
   - The cluster contains multiple specific topics that share a common broader category
   - There's no existing topic in the cluster that encompasses the others
   - Creating an umbrella topic would improve the hierarchy's clarity and organization
   - Example: A cluster with "Wi-Fi 6", "Wi-Fi 6E", "Wi-Fi 7" but no "Wi-Fi" topic

2. **When NOT to suggest a general topic**:
   - The cluster already has a topic that encompasses the others
   - The topics are too diverse to be meaningfully grouped under a single umbrella
   - Adding a general topic would create unnecessary abstraction

3. **How many general topics to suggest**:
   - Usually 0-1 general topics per cluster
   - Can suggest 2+ if the cluster has distinct subgroups (e.g., "Wireless Standards" and "Network Security" for a mixed cluster)
   - Be conservative - only suggest when genuinely beneficial

4. **Topic metadata requirements**:
   - **name**: Clear, concise name (e.g., "Artificial Intelligence", "Wi-Fi Standards")
   - **classification**: Category type (e.g., "technology", "standard", "framework", "domain", "field")
   - **identifier**: Canonical identifier if applicable (e.g., "IEEE 802.11" for Wi-Fi Standards) - can be null
   - **issuer**: Organization that maintains/defines this topic if applicable (e.g., "IEEE", "ISO") - can be null
   - **aliases**: List of alternative names/synonyms (e.g., ["AI", "Machine Intelligence"] for "Artificial Intelligence")

5. **Quality criteria**:
   - Names should be established, widely-recognized terms (not invented jargon)
   - Classifications should match the taxonomy: technology, standard, certification, regulation, framework, protocol, domain, field, etc.
   - Identifiers only when there's an official designation
   - Aliases should include common abbreviations and alternative phrasings

You must respond with valid JSON only, no additional text or explanations.
"""


GENERAL_TOPIC_SUGGESTION_USER_PROMPT = """
Analyze the following cluster of topics and determine if one or more general/umbrella topics should be created to organize them hierarchically.

CLUSTER TOPICS:
{topics_json}

Your task:
1. Review all topics in the cluster
2. Determine if they share common broader categories that are missing
3. Check if any existing topics already serve as general topics
4. Suggest 0-N new general topics with full metadata

Respond with JSON in this exact format:
{{
  "suggested_topics": [
    {{
      "name": "Clear topic name",
      "classification": "technology|standard|certification|regulation|framework|protocol|domain|field|etc",
      "identifier": "Official identifier if applicable, otherwise null",
      "issuer": "Issuing organization if applicable, otherwise null",
      "aliases": ["alternative", "names", "or", "abbreviations"],
      "reasoning": "Why this general topic would benefit the hierarchy",
      "would_encompass": ["topic_id_1", "topic_id_2", "..."]
    }}
  ]
}}

Examples:

Cluster needs a general topic:
{{
  "suggested_topics": [
    {{
      "name": "Wi-Fi Standards",
      "classification": "technology",
      "identifier": "IEEE 802.11",
      "issuer": "IEEE",
      "aliases": ["WiFi", "Wireless Fidelity", "802.11"],
      "reasoning": "Cluster contains specific Wi-Fi versions (6, 6E, 7) but lacks an umbrella Wi-Fi topic",
      "would_encompass": ["wi-fi-6", "wi-fi-6e", "wi-fi-7"]
    }}
  ]
}}

Cluster already well-organized:
{{
  "suggested_topics": []
}}

Multiple general topics needed:
{{
  "suggested_topics": [
    {{
      "name": "Artificial Intelligence",
      "classification": "technology",
      "identifier": null,
      "issuer": null,
      "aliases": ["AI", "Machine Intelligence"],
      "reasoning": "Cluster contains ML, NLP, Computer Vision but lacks AI umbrella",
      "would_encompass": ["machine-learning", "natural-language-processing", "computer-vision"]
    }},
    {{
      "name": "Data Science",
      "classification": "field",
      "identifier": null,
      "issuer": null,
      "aliases": ["Data Analytics", "Analytics"],
      "reasoning": "Cluster also contains data analysis topics that need separate umbrella",
      "would_encompass": ["data-mining", "statistical-analysis", "predictive-modeling"]
    }}
  ]
}}

Notes:
- Only suggest topics that would genuinely improve the hierarchy
- Use established, recognized terminology (not invented terms)
- Include comprehensive aliases for discoverability
- Be conservative - when in doubt, suggest 0 new topics
"""

