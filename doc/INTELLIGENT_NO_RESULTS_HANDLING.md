# Intelligent No-Results Handling

## Overview

When a user asks a question that has no matching documents in the knowledge base, the system now provides more intelligent and helpful responses instead of simply saying "I couldn't find any relevant documents."

## Implementation

### Changes Made

1. **Oracle Response Generator** (`oracle/src/services/response_generator.py`)
   - Added new `_generate_no_documents_response()` method
   - Uses LLM's general knowledge to attempt answering the question when no documents are found
   - Provides helpful suggestions for query reformulation
   - Includes appropriate caveats about information not being from the knowledge base

2. **Fast Engine** (`oracle/src/engines/fast_engine.py`)
   - Improved no-documents message with actionable suggestions
   - Provides context about what the knowledge base covers

3. **Backend LLM Service** (`backend/src/services/llm_service.py`)
   - Consistent messaging when documents aren't found
   - Helpful suggestions for users

### Behavior

#### When LLM is Available
The system will:
1. Acknowledge that no documents were found in the knowledge base
2. Use the LLM's general knowledge to provide a helpful answer (if possible)
3. Include appropriate caveats (e.g., "I don't have current event dates")
4. Suggest where users might find more specific information
5. Provide query reformulation tips

**Example Response:**
```
I couldn't find specific documents in our knowledge base about the WFA meeting in Bangkok.

However, Wi-Fi Alliance typically holds member meetings throughout the year in various 
global locations. For the most current information about upcoming WFA events, including 
specific dates and locations, I recommend:

• Visiting the official Wi-Fi Alliance website (wi-fi.org)
• Checking their events calendar directly
• Searching for "Wi-Fi Alliance member meeting Bangkok" on their site

**Try rephrasing your query:**
• "Recent Wi-Fi Alliance announcements"
• "Upcoming Wi-Fi industry events"
• "Wi-Fi Alliance meeting schedule"
```

#### When LLM is Unavailable
The system provides structured suggestions:
```
I couldn't find any documents in our knowledge base that directly address your question.

**Suggestions:**
• Try rephrasing your question with different terms
• Broaden your search (e.g., remove specific date ranges)
• Check for typos in organization or technology names
• Try asking about related topics or industry trends

Our knowledge base focuses on wireless standards, Wi-Fi technology, and industry news 
from sources like Wi-Fi Alliance, IEEE, and industry organizations.
```

## Benefits

1. **More Helpful**: Users get guidance even when no documents match
2. **Better UX**: Provides actionable suggestions instead of dead-ends
3. **Intelligent Fallback**: Uses LLM's general knowledge appropriately with caveats
4. **Context-Aware**: Acknowledges limitations and suggests alternatives
5. **Professional**: Maintains trust by being honest about information sources

## Confidence Scoring

- No documents + LLM general knowledge response: **0.3** (low confidence)
- No documents + no LLM: **0.0** (no confidence)
- This ensures users understand the answer is not from curated sources

## Future Enhancements

Potential improvements:
1. **Web Search Integration**: Add ability to search public web for current information
2. **Query Expansion**: Automatically try alternative queries with synonyms
3. **Related Topics**: Suggest similar topics that do have documents
4. **Smart Routing**: Detect when question is about external/current events and suggest official sources
