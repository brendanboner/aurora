"""Prompts for LLM metadata extraction."""


# Evidence field character limits
MAX_EVIDENCE_LENGTH = 240
MAX_REASONING_LENGTH = 100


METADATA_EXTRACTION_PROMPT = """

You are a metadata extraction expert. Read the provided content and extract only entities and relations that are directly supported by the text, you may use limited domain knowledge as specified below.
Do not invent or assume any information beyond what is explicitly allowed.

Document Information:
- Title: {title}
- URL: {url}
- Category: {category}
- Publish Date: {publish_date}

IMPORTANT: Convert all dates to ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).
For example: "November 15, 2025" should become "2025-11-15"
If only year and month are known, use YYYY-MM-01 format.

Content (may be partial):
{content}

Definitions:
- Organizations are companies, institutions, or groups mentioned in the document.
- People are individual human beings mentioned in the document.
- Topics are the main subjects, entities, or technical terms discussed in the document.

You MUST classify each topic into exactly ONE of the following classifications:

Topic classifications:
- "standard": technical or industry standards (e.g., Wi-Fi 7, IEEE 802.11be, ISO/IEC 27001, HDMI 2.1)
- "certification": certifications, compliance schemes, or attestations (e.g., SOC 2, ISO 27001 certification, CISSP)
- "regulation": laws, directives, regulations, or mandatory rules (e.g., GDPR, HIPAA, CCPA)
- "framework": named frameworks or models (e.g., NIST CSF, COBIT, MITRE ATT&CK)
- "specification": detailed technical specifications or formats (e.g., OpenAPI spec, JSON Schema, RFC used as a spec)
- "protocol": communication or interaction protocols (e.g., TLS, HTTPS, OAuth 2.0, SAML, MQTT)
- "technology": concrete technologies or technology families (e.g., Wi-Fi, VPN, Kubernetes, machine learning, blockchain)
- "concept": abstract ideas or principles (e.g., zero trust, least privilege, encryption at rest)
- "product": specific commercial or open-source products or SKUs (e.g., "Windows Server 2022", "PostgreSQL", "Acme SecureGateway")
- "service": managed services, SaaS, or cloud services (e.g., AWS IAM, Azure AD, "Security Monitoring Service")
- "process": defined processes or workflows (e.g., incident response process, CI/CD pipeline, change management process)
- "tool": specific tools or utilities (e.g., Nmap, Wireshark, Terraform, kubectl)
- "other": any topic that clearly is not a person or organization and does not fit any of the above types

Topic stances:
- "descriptive" when the text only explains or reports information about the topic.
- "supportive" when the text recommends, endorses, or encourages the topic.
- "critical" when the text criticizes the topic or recommends against it.
- "concerned" when the text discusses risks, issues, downsides, or warnings.
- "directive" when the text gives instructions, requirements, or mandates related to the topic.
- "mixed" when both positive and negative aspects are presented without a dominant stance.
- "speculative" when the text predicts, hypothesizes, or speculates about the topic.


Allowed domain/background knowledge:
- You may use general technical world knowledge ONLY to:
  - decide the topic classification, and
  - Provide insight on the following node fields:
    Topic:
      - issuer
      - identifier
      - aliases
    Organization:
      - type
      - aliases
      - homepage_url

  - Deeply understand the impact and outcomes of this document on Extreme Networks. 
  - Build relationships between entities based on common sense and domain knowledge.
- For example, you may:
  - classify "Wi-Fi 7" as a "standard" and
  - use "IEEE 802.11be" as its identifier,
  even if the document does not explicitly say "standard" or "IEEE 802.11be".

Do NOT use world knowledge to invent entities that are not mentioned in the content.

Node Types to Extract:

RESOURCE
  Fields:
    - summary (string, required): A 3–5 sentence summary (minimum 350 characters) of the document's main
        purpose and key technical content. Tailor by doc_type:
        • meeting-minutes: include key decisions, action items, and main topics discussed.
        • specification/internet-draft: include scope, key technical features, and target use case.
        • blog/press-release: include the main announcement or argument and its significance.
        • video-transcript: include main topics, key speakers, and organisations discussed.
        • case-study/whitepaper: include the problem addressed, approach taken, and key findings.
        Do NOT write "the document provides a download link" or generic filler. Extract actual content.
    - doc_type (string, required): Classify the document into exactly one of:
        specification, internet-draft, whitepaper, meeting-minutes, press-release, blog,
        video-transcript, case-study, infographic, newsletter, governing-document, agenda,
        presentation, unknown
        Use the category field, URL, datasource, and content as signals.
    - importance (float, 0.0–1.0, required): Relevance and significance to enterprise networking
        professionals at Extreme Networks. Use this scale strictly — do NOT cluster at 0.8:
        • 0.9–1.0: Foundational standard, major certification, landmark specification, or critical
                   security advisory directly affecting Extreme Networks products or customers.
        • 0.7–0.89: Directly relevant technical document, active WG draft with real-world impact,
                    official industry announcement from a primary standards body or key organisation.
        • 0.5–0.69: Useful context — vendor blogs, general industry articles, peripheral WG drafts,
                    event recordings with relevant discussion.
        • 0.3–0.49: Limited relevance — dated content, brief updates, meeting logistics, newsletters
                    with no specific technical depth.
        • 0.1–0.29: Minimal value — brand assets, membership forms, duplicate/redirect pages,
                    content with no extractable technical information.
        Target distribution: ~10% high (0.8+), ~50% medium (0.5–0.79), ~40% lower (<0.5).
        Be critical. Most documents are not highly important.
    - importance_explanation (string, required): One sentence explaining the importance score,
        referencing specific content that justifies the band chosen.
    - extreme_impact (string, optional): A brief explanation of the impact and outcomes this document
        has on Extreme Networks company, products, services, or clients. Leave null if no relevant impact.

Topics
  Fields:
    - name (string, required)
    - classification (string, required; one of:
      "standard","certification","regulation","framework","specification",
      "protocol","technology","concept","product","service","process","tool","other")
    - identifier (string, optional; e.g., "IEEE 802.11be", "ISO/IEC 27001") - Only to be used by topics classified as "standard" or "certification". To be filled in using background knowledge if not explicitly stated in the document.
    - issuer (string, optional; e.g., "ISO", "Wi-Fi Alliance", "NIST") - Only to be used by topics classified as "standard" or "certification". To be filled in using background knowledge if not explicitly stated in the document.
    - aliases (array of strings, required; e.g., ["Wi-Fi 7", "IEEE 802.11be"]) - To be generated using background knowledge if not explicitly stated in the document.

  Guidelines:
    - Limit topics to maximum 10 most relevant items.
    - Do NOT create topics that are clearly People or Organizations.
    - For well-known standards (e.g., Wi-Fi 7, USB 4.0, ISO/IEC 27001), classify them as "standard" even if the document does not explicitly say "standard".
    - Use identifier and issuer only when you are confident they are correct.
    - For acronyms: Use widely recognized acronyms as the name (e.g., "AI", "IoT", "VPN") with the expansion in aliases (e.g., aliases: ["Artificial Intelligence"]). For less common acronyms, use the full term as the name and include the acronym in aliases.
    - For naming keep the most well known simple name and generalize when possible without losing information (e.g., "Wi-Fi" instead of "Wireless Fidelity", "PostgreSQL" instead of "PostgreSQL Database", "802.11" instead of "IEEE 802.11").

People
  Fields:
    - name (string, required)
    - email (string, optional) only if stated in the document

Organizations
  Fields:
    - name (string, required)
    - aliases (array of strings, required) - To be generated using background knowledge if not explicitly stated in the document.
    - org_type (string, optional; e.g., "company", "institution", "standards body" "government agency")
    - homepage_url (string, optional)

Relationships to Extract:

RESOURCE_RELATES_TO_TOPIC
  From: RESOURCE
  To: Topic
  Fields:
    - confidence (float, 0.0–1.0, required)
    - relevance (float, 0.0–1.0, required)
    - evidence (string, required, direct quote from content, max 240 chars)
    - stance (string, required, one of: "descriptive", "supportive", "critical", "concerned", "directive", "mixed", "speculative")
  - stance_score (float, 0.0 to 1.0, required)

RESOURCE_MENTIONS_PERSON
  From: RESOURCE
  To: Person
  Fields:
    - confidence (float, 0.0–1.0, required)
    - role (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)

RESOURCE_MENTIONS_ORGANIZATION
  From: RESOURCE
  To: Organization
  Fields:
    - confidence (float, 0.0–1.0, required)
    - evidence (string, required, direct quote from content, max 240 chars)

PERSON_AFFILIATED_WITH_ORGANIZATION
  From: Person
  To: Organization
  Fields:
    - confidence (float, 0.0–1.0, required)
    - role (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)

PERSON_CONNECTED_TO_TOPIC
  From: Person
  To: Topic
  Fields:
    - confidence (float, 0.0–1.0, required)
    - affiliation (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)

ORGANIZATION_ASSOCIATED_WITH_TOPIC
  From: Organization
  To: Topic
  Fields:
    - confidence (float, 0.0–1.0, required)
    - affiliation (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)


Extract the above nodes in the JSON format below.
If there are no relevant entities for a node type, return an empty array or null as appropriate.

Return ONLY valid JSON in this exact format:

{{
  "nodes": {{
    "resource": {{ "summary": "string", "importance": 0.5, "importance_explanation": "string", "extreme_impact": "string" }},
    "topics": [
      {{
        "name": "string",
        "classification": "standard|certification|regulation|framework|specification|protocol|technology|concept|product|service|process|tool|other",
        "identifier": "string",
        "issuer": "string",
        "aliases": [ "string" ]
      }}
    ],
    "people": [ {{ "name": "string", "email": "string" }} ],
    "organizations": [ {{ "name": "string", "aliases": [ "string" ], "org_type": "string", "homepage_url": "string" }} ]
  }},
  "relationships": [
    {{
      "relationship_type": "RESOURCE_RELATES_TO_TOPIC|RESOURCE_MENTIONS_PERSON|RESOURCE_MENTIONS_ORGANIZATION|PERSON_AFFILIATED_WITH_ORGANIZATION|PERSON_CONNECTED_TO_TOPIC|ORGANIZATION_ASSOCIATED_WITH_TOPIC",
      "source_identifier": "string",
      "target_identifier": "string",
      "confidence": 0.0,
      "evidence": "string <= 240 chars",
      "relevance": 0.0,
      "stance": "string",
      "stance_score": 0.0,
      "role": "string",
      "affiliation": "string"
    }}
  ]
}}

Important guidelines:
- CRITICAL: Keep your response CONCISE to stay within {max_tokens} token limit. Use short summaries and descriptions.
- Limit topics to maximum 10 most relevant items.
- Limit relationships to maximum 15 most relevant connections.
- Be specific and accurate but BRIEF.
- All confidence and relevance scores must be between 0.0 and 1.0.
- evidence is a direct quote from the content, max 240 characters. Do not go over the 240 character limit. Cut the quote short if needed.
- summary must be 3–5 sentences and at least 350 characters. Do not write filler like "provides a download link".
- importance_explanation must be one sentence referencing specific content. extreme_impact under 2 sentences.
- importance MUST use the full 0.0–1.0 range. Do not default to 0.8. Most documents should score 0.5–0.7.
- doc_type must be one of the listed values — use "unknown" only if genuinely unclassifiable.
- Do not add any fields not specified above.
- For relationships, relationship_type, subject_identifier, and object_identifier are required. For the other fields refer to relationship type definitions above.
- relationship identifiers should be the name field of the respective nodes or the URL if the node is the resource.
- These resources come from selected data sources relevant to Extreme Networks. Given this be very critical when evaluating importance scores.
- If a topic is selected to be included it means it is relevant. Therefore in determining relevance scores be very critical of how relevant the topic is to the main content of the document.

"""

METADATA_MERGE_PROMPT = """

You have multiple metadata extractions from different chunks of the same document. Merge them intelligently into a single, coherent metadata set.

Document Title: {title}

Extracted Metadata from Chunks:
{chunks_metadata}

Create a unified metadata extraction that:
1. Combines all unique items from lists (topics, people, organizations, relationships, etc.)
2. Creates a comprehensive summary under resource that captures the full document scope
3. Removes duplicates and near-duplicates
4. Keeps only the most relevant and accurate information
5. Limits topics to maximum 10 most relevant items
6. For duplicate relationships with multiple confidence/relevance scores, average them appropriately

Return ONLY valid JSON in this exact format:

{{
  "nodes": {{
    "resource": {{ "summary": "string", "doc_type": "string", "importance": 0.5, "importance_explanation": "string", "extreme_impact": "string" }},
    "topics": [
      {{
        "name": "string",
        "classification": "standard|certification|regulation|framework|specification|protocol|technology|concept|product|service|process|tool|other",
        "identifier": "string",
        "issuer": "string",
        "aliases": [ "string" ]
      }}
    ],
    "people": [ {{ "name": "string", "email": "string" }} ],
    "organizations": [ {{ "name": "string", "aliases": [ "string" ], "org_type": "string", "homepage_url": "string" }} ]
  }},
  "relationships": [
    {{
      "relationship_type": "RESOURCE_RELATES_TO_TOPIC",
      "source_identifier": "string",
      "target_identifier": "string",
      "confidence": 0.0,
      "evidence": "string <= 240 chars",
      "relevance": 0.0,
      "stance": "string",
      "stance_score": 0.0,
      "role": "string",
      "affiliation": "string"
    }}
  ]
}}

Relationship Definitions:

RESOURCE_RELATES_TO_TOPIC
  From: RESOURCE
  To: Topic
  Fields:
    - confidence (float, 0.0–1.0, required)
    - relevance (float, 0.0–1.0, required)
    - evidence (string, required, direct quote from content, max 240 chars)
    - stance (string, required, one of: "descriptive", "supportive", "critical", "concerned", "directive", "mixed", "speculative")
  - stance_score (float, 0.0 to 1.0, required) 

RESOURCE_MENTIONS_PERSON
  From: RESOURCE
  To: Person
  Fields:
    - confidence (float, 0.0–1.0, required)
    - role (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)

RESOURCE_MENTIONS_ORGANIZATION
  From: RESOURCE
  To: Organization
  Fields:
    - confidence (float, 0.0–1.0, required)
    - evidence (string, required, direct quote from content, max 240 chars)

PERSON_AFFILIATED_WITH_ORGANIZATION
  From: Person
  To: Organization
  Fields:
    - confidence (float, 0.0–1.0, required)
    - role (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)

PERSON_CONNECTED_TO_TOPIC
  From: Person
  To: Topic
  Fields:
    - confidence (float, 0.0–1.0, required)
    - affiliation (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)

ORGANIZATION_ASSOCIATED_WITH_TOPIC
  From: Organization
  To: Topic
  Fields:
    - confidence (float, 0.0–1.0, required)
    - affiliation (string, optional)
    - evidence (string, required, direct quote from content, max 240 chars)

Important guidelines:
- CRITICAL: Keep your response CONCISE to stay within {max_tokens} token limit. Use short summaries and descriptions.
- Limit topics to maximum 10 most relevant items
- Limit relationships to maximum 15 most relevant connections
- summary must be 3–5 sentences and at least 350 characters. Merge chunk summaries into a comprehensive whole.
- importance_explanation must be one sentence. extreme_impact under 2 sentences.
- importance MUST use the full 0.0–1.0 range. Do not default to 0.8. Most documents score 0.5–0.7.
- doc_type must be one of: specification, internet-draft, whitepaper, meeting-minutes, press-release, blog, video-transcript, case-study, infographic, newsletter, governing-document, agenda, presentation, unknown
- Ensure all confidence scores are between 0.0 and 1.0
- For duplicate relationships, merge them and average their scores
- evidence must be a direct quote from the content, max 240 characters. Do not go over the 240 character limit. Cut the quote short if needed.
"""


EVENT_DISAMBIGUATION_PROMPT = """
You are matching a document to its related meeting or event.

A document has been found with a date in its title, and there are multiple events on that same date from the same working group. Your task is to determine which event (if any) this document is most likely related to.

Document Information:
- Title: {title}
- Summary: {summary}
- Date found in title: {extracted_date}

Candidate Events (all occurring on {extracted_date} from the same working group):
{events_list}

Based on the document title, summary, and the event names/descriptions, determine which event this document is most likely related to.

Consider:
- Does the document title reference a specific meeting, working group, or topic that matches one of the events?
- Does the summary content relate more closely to one event's purpose/description?
- Common document types and their associations:
  - "Meeting Minutes" / "Minutes" → likely from a meeting event
  - "Attendance" / "Attendees" → likely from a meeting event  
  - "Agenda" → likely preparation for a meeting event
  - "Presentation" / "Slides" → could be from meeting or conference
  - Working group names in title often match event names

Return your analysis as JSON ONLY with no additional text:
{{
  "event_index": <1-based index of the matching event, or 0 if no clear match>,
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "<brief explanation, max 100 chars>"
}}

If you cannot confidently determine which event the document relates to, return event_index: 0 with a low confidence score.
"""
