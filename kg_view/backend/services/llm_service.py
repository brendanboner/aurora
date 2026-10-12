"""
LLM Service for transforming natural language queries to Cypher
Uses Azure OpenAI GPT-4o
"""
import os
from typing import Dict, List, Optional
from openai import AzureOpenAI
import json


class LLMService:
    """Service for natural language to Cypher transformation"""
    
    # Schema documentation for the LLM
    SCHEMA_CONTEXT = """
# Neo4j Knowledge Graph Schema

## Node Types:
1. **Resource** (Documents): Properties: url, title, summary, category (blog/press release/paper/whitepaper/article/podcast/newsletter), doc_type, publish_date, importance
2. **Topic** (Subject areas): Properties: topic_id, name, classification (standard/certification/regulation/framework/technology), identifier, issuing_org, aliases
3. **Organization**: Properties: org_id, name, org_type (standards body/consortium/vendor/non-profit/academic), aliases, homepage_url
4. **Person**: Properties: person_id, name, email
5. **Event**: Properties: url, name, event_type (conference/meeting/webinar/deadline/workshop/seminar/summit), start_date, end_date, location, description
6. **DataSource**: Properties: source_id, name, source_type, url

## Relationship Types:
- (Resource)-[:RELATES_TO_TOPIC]->(Topic) - Properties: stance, confidence, importance
- (Resource)-[:MENTIONS]->(Person) - Resource mentions a person
- (Resource)-[:MENTIONS]->(Organization) - Resource mentions an organization
- (Resource)-[:MENTIONS]->(Event) - Resource mentions an event
- (Resource)-[:MENTIONS]->(Topic) - Resource mentions a topic
- (Person)-[:AFFILIATED_WITH]->(Organization) - Properties: role, confidence, evidence
- (Person)-[:CONNECTED_TO_TOPIC]->(Topic) - Properties: relationship_type, confidence, evidence
- (Organization)-[:ASSOCIATED_WITH_TOPIC]->(Topic) - Properties: relationship_type, confidence, evidence
- (Topic)-[:ENCOMPASSES]->(Topic) - Broader → Narrower
- (Topic)-[:SUBTOPIC_OF]->(Topic) - Narrower → Broader
- (Event)-[:SUPERSEDES]->(Event) - Properties: reason

## Common Query Patterns:
- Find resources about a topic: `MATCH (r:Resource)-[:RELATES_TO_TOPIC]->(t:Topic {name: "Wi-Fi 6"}) RETURN r, t`
- Find related topics: `MATCH (t1:Topic)-[:ENCOMPASSES|SUBTOPIC_OF]-(t2:Topic) WHERE t1.name = "Wi-Fi" RETURN t1, t2`
- Find organization topics: `MATCH (o:Organization)-[:ASSOCIATED_WITH_TOPIC]->(t:Topic) WHERE o.name = "Wi-Fi Alliance" RETURN o, t`
- Find resources mentioning an organization: `MATCH (r:Resource)-[:MENTIONS]->(o:Organization {name: "IEEE"}) RETURN r`
- Find resources mentioning a person: `MATCH (r:Resource)-[:MENTIONS]->(p:Person {name: "David Coleman"}) RETURN r`
- Find person's organization: `MATCH (p:Person {name: "David Coleman"})-[:AFFILIATED_WITH]->(o:Organization) RETURN o`
- Find resources about a person and their org: `MATCH (p:Person {name: "David Coleman"})-[:AFFILIATED_WITH]->(o:Organization)<-[:MENTIONS]-(r:Resource)-[:MENTIONS]->(p) RETURN r`
- Find events by type: `MATCH (e:Event {event_type: "conference"}) WHERE e.start_date >= date() RETURN e`
"""
    
    def __init__(self):
        self.client = AzureOpenAI(
            api_key=os.getenv('AZURE_OPENAI_API_KEY'),
            api_version=os.getenv('AZURE_OPENAI_API_VERSION', '2024-10-21'),
            azure_endpoint=os.getenv('AZURE_OPENAI_ENDPOINT')
        )
        self.deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o')
    
    def transform_query(self, natural_language_query: str) -> Dict[str, any]:
        """
        Transform natural language query to Cypher and extract entities
        
        Args:
            natural_language_query: User's natural language question
            
        Returns:
            Dictionary with cypher query, entities, and explanation
        """
        system_prompt = f"""You are an expert at converting natural language questions into Neo4j Cypher queries.
Given a user's question, generate a safe, read-only Cypher query and extract relevant entities.

{self.SCHEMA_CONTEXT}

## Instructions:
1. Generate a Cypher query that answers the user's question
2. Extract entities mentioned (topics, organizations, people) with their types and names
3. Provide a brief explanation of what the query does
4. Use LIMIT to prevent returning too many results (max 100 for nodes, 500 for relationships)
5. ONLY use MATCH, WHERE, RETURN, ORDER BY, LIMIT - no CREATE, DELETE, SET, MERGE
6. Use parameters for user inputs to prevent injection
7. Return results in JSON format

## Response Format:
{{
  "cypher": "MATCH (n:Topic) WHERE n.name CONTAINS $search RETURN n LIMIT 50",
  "parameters": {{"search": "Wi-Fi"}},
  "entities": [
    {{"type": "topic", "name": "Wi-Fi 6", "id": "wi-fi-6"}},
    {{"type": "organization", "name": "Wi-Fi Alliance", "id": "wi-fi-alliance"}}
  ],
  "explanation": "This query finds all topics containing 'Wi-Fi' in their name"
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": natural_language_query}
                ],
                temperature=0.3,
                max_tokens=1000,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Validate the response
            if not result.get('cypher'):
                return {
                    'error': 'No Cypher query generated',
                    'cypher': 'MATCH (n) RETURN n LIMIT 10',
                    'parameters': {},
                    'entities': [],
                    'explanation': 'Default query: return 10 nodes'
                }
            
            # Basic safety check - ensure read-only
            dangerous_keywords = ['CREATE', 'DELETE', 'SET', 'REMOVE', 'MERGE', 'DROP', 'DETACH']
            cypher_upper = result['cypher'].upper()
            if any(keyword in cypher_upper for keyword in dangerous_keywords):
                return {
                    'error': 'Query contains write operations - not allowed',
                    'cypher': 'MATCH (n) RETURN n LIMIT 10',
                    'parameters': {},
                    'entities': [],
                    'explanation': 'Query blocked for safety'
                }
            
            return {
                'cypher': result.get('cypher', ''),
                'parameters': result.get('parameters', {}),
                'entities': result.get('entities', []),
                'explanation': result.get('explanation', '')
            }
            
        except Exception as e:
            print(f"Error in LLM query transformation: {e}")
            return {
                'error': str(e),
                'cypher': 'MATCH (n) RETURN n LIMIT 10',
                'parameters': {},
                'entities': [],
                'explanation': f'Error occurred: {str(e)}'
            }
    
    def extract_entities_from_text(self, text: str) -> List[Dict[str, str]]:
        """
        Extract entities (topics, organizations, people) from text
        
        Args:
            text: Text to analyze
            
        Returns:
            List of entities with type, name, and suggested ID
        """
        system_prompt = """Extract entities from the text that match these types:
- **Person**: Individual names (e.g., "David Coleman", "John Smith")
- **Organization**: Company/organization names (e.g., "Extreme Networks", "IEEE", "Wi-Fi Alliance")
- **Topic**: Technical terms, standards, technologies (e.g., "Wi-Fi 6", "802.11ax", "WPA3")
- **Event**: Events, conferences, deadlines (e.g., "WiFi Summit 2024")

Return ONLY entities explicitly mentioned in the text. Be generous with partial matches.
For organizations, include common abbreviations (e.g., "Extreme" for "Extreme Networks").

Return as JSON with this exact format:
{"entities": [
  {"type": "person", "name": "David Coleman", "id": "david_coleman"},
  {"type": "organization", "name": "Extreme Networks", "id": "extreme_networks"}
]}

IMPORTANT: 
- Use underscores in IDs (not hyphens)
- Keep organization names as mentioned, but add ", Inc." suffix if it's a company
- Extract ALL entities, even if partially mentioned
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract entities from: {text}"}
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return result.get('entities', [])
            
        except Exception as e:
            print(f"Error extracting entities: {e}")
            return []

    def extract_entities_with_context(self, prompt: str, context: str) -> List[Dict[str, str]]:
        """
        Extract entities from context using a specific prompt
        
        Args:
            prompt: Instruction prompt for the LLM
            context: Database search results or other context
            
        Returns:
            List of entities with type and name
        """
        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are an expert at identifying relevant entities from database search results. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            
            # Handle different response formats
            if 'entities' in result:
                return result['entities']
            elif isinstance(result, list):
                return result
            else:
                # Try to extract from first key that looks like entities
                for key in result.keys():
                    if isinstance(result[key], list):
                        return result[key]
                return []
            
        except Exception as e:
            print(f"Error extracting entities with context: {e}")
            return []
