import axios, { AxiosInstance } from 'axios';

export interface AgentPersona {
  name: string;
  persona: string | null;
  tone_style: string;
  content_length_preference: string;
  expertise_topics: string[];
  expertise_organisations: string[];
  expertise_standards: string[];
  llm_temperature_override: number | null;
}

export interface OracleQuery {
  user_id: string;
  question: string;
  mode: 'retrieval' | 'answer' | 'auto';
  agent_persona?: AgentPersona;
  options?: {
    max_documents?: number;
    include_graph_context?: boolean;
    date_start?: string;
    date_end?: string;
    topics?: string[];
    organizations?: string[];
    datasource_ids?: string[];
  };
}

export interface OracleResponse {
  mode: string;
  answer?: string;
  documents: OracleDocument[];
  citations?: Citation[];
  graph_context?: GraphContext;
  confidence_score?: number;
  metadata?: any;
  suggestions?: Suggestion[];
}

export interface OracleDocument {
  title: string;
  url: string;
  summary: string;
  publish_date: string;
  topics: string[];
  organisations: string[];
  datasource_id: string;
  datasource_name: string;
  relevance_score: number;
}

export interface Citation {
  document_index: number;
  quote: string;
}

export interface GraphContext {
  central_topics?: string[];
  key_organizations?: string[];
  key_people?: string[];
}

export interface Suggestion {
  suggestion: string;
  reason?: string;
  score?: number;
}

export class AuroraOracleService {
  private apiClient: AxiosInstance;
  private baseUrl: string;
  private devUserEmail: string;

  constructor() {
    // Oracle Service runs separately from backend
    this.baseUrl = process.env.AURORA_ORACLE_URL || 'http://aurora-oracle:8000';
    this.devUserEmail = process.env.TEST_USER_EMAIL || 'test@example.com';
    
    // Use actual Cognito UUID from environment, or generate dev ID as fallback
    const userId = process.env.TEST_USER_ID || `dev-${Buffer.from(this.devUserEmail).toString('base64').substring(0, 20)}`;
    
    this.apiClient = axios.create({
      baseURL: this.baseUrl,
      timeout: 30000, // 30 seconds for Oracle queries
      headers: {
        'Content-Type': 'application/json',
        // Development: Bot authenticates as TEST_USER_EMAIL (bypasses Cognito)
        // Backend trusts X-User-* headers from internal Docker network
        'X-User-Id': userId,
        'X-User-Email': this.devUserEmail,
        'X-User-Role': 'user',
        ...(process.env.AURORA_SERVICE_TOKEN ? { 'X-Service-Token': process.env.AURORA_SERVICE_TOKEN } : {}),
      }
    });
  }

  /**
   * Send query to Oracle service
   */
  async query(
    userId: string,
    question: string,
    agentPersona?: AgentPersona,
    datasourceIds?: string[],
  ): Promise<OracleResponse> {
    try {
      console.log(`Oracle query from user ${userId}: "${question}"${agentPersona ? ` [as ${agentPersona.name}]` : ''}${datasourceIds?.length ? ` [@sources: ${datasourceIds.join(',')}]` : ''}`);

      const payload: OracleQuery = {
        user_id: userId,
        question: question,
        mode: 'answer',
        ...(agentPersona && { agent_persona: agentPersona }),
        options: {
          max_documents: 5,
          include_graph_context: true,
          ...(datasourceIds?.length ? { datasource_ids: datasourceIds } : {}),
        }
      };

      const response = await this.apiClient.post('/query', payload);
      
      console.log(`Oracle responded with ${response.data.documents?.length || 0} documents`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        // If auth error and mock mode enabled, return sample data
        if ((error.response?.status === 401 || error.response?.status === 403) && 
            process.env.USE_MOCK_DATA === 'true') {
          console.log('⚠️  Using mock Oracle data (authentication unavailable)');
          return this.getMockResponse(question);
        }
      }
      console.error('Error querying Oracle:', error);
      throw error;
    }
  }

  /**
   * Get mock response for testing without backend authentication
   */
  private getMockResponse(question: string): OracleResponse {
    return {
      mode: 'answer',
      answer: `[Local test mode] Your question: "${question}"\n\nThis is a placeholder response. With production authentication, Aurora would query its knowledge base for source-backed answers about Wi-Fi, networking, and standards.`,
      documents: [
        {
          title: 'Example: Wi-Fi 7 Technology Overview',
          url: 'https://www.extremenetworks.com/wifi7',
          summary: 'Wi-Fi 7 (802.11be) delivers breakthrough performance with multi-link operation, 320 MHz channels, and enhanced reliability.',
          publish_date: '2026-01-10',
          topics: ['Wi-Fi 7', '802.11be'],
          organisations: ['Extreme Networks'],
          datasource_id: 'mock-1',
          datasource_name: 'Sample Knowledge Base',
          relevance_score: 0.95
        }
      ],
      confidence_score: 0.85,
      suggestions: [
        { suggestion: 'What are the key benefits of Wi-Fi 7?', score: 0.8 }
      ]
    };
  }

  /**
   * Resolve @mention text to datasource_ids.
   * Returns an array of matching datasource IDs (including children).
   * Uses the oracle's /datasources endpoint which already returns parent_datasource_id.
   */
  async resolveMentionsToDatasourceIds(mentions: string[]): Promise<string[]> {
    if (!mentions.length) return [];
    try {
      const response = await this.apiClient.get('/datasources');
      const allSources: Array<{ datasource_id: string; name: string; parent_datasource_id?: string }> =
        response.data?.datasources || [];

      const resolved = new Set<string>();
      for (const mention of mentions) {
        const lower = mention.toLowerCase();
        const match = allSources.find(ds =>
          ds.datasource_id.toLowerCase() === lower ||
          ds.datasource_id.toLowerCase().includes(lower) ||
          (ds.name || '').toLowerCase().includes(lower)
        );
        if (match) {
          resolved.add(match.datasource_id);
          // Include children (one level)
          for (const child of allSources.filter(ds => ds.parent_datasource_id === match.datasource_id)) {
            resolved.add(child.datasource_id);
          }
        }
      }
      return Array.from(resolved);
    } catch (err) {
      console.warn('resolveMentionsToDatasourceIds failed:', err);
      return [];
    }
  }

  /**
   * Check if Oracle service is healthy
   */
  /** Call the oracle enhance endpoint with documents from a previous query. */
  async enhance(userId: string, question: string, documents: Array<{ title: string; url: string; datasource_id?: string }>): Promise<string> {
    // Ensure each document has datasource_id (required by /enhance)
    const docsWithDs = documents.map(d => ({
      ...d,
      datasource_id: d.datasource_id || d.url?.match(/wi-fi\.org|wballiance|ieee|ietf/i)?.[0] || 'web',
    }));
    const response = await this.apiClient.post('/enhance', {
      user_id: userId,
      question,
      documents: docsWithDs,
    });
    return response.data?.enhanced_answer || response.data?.answer || '';
  }

  async healthCheck(): Promise<boolean> {
    try {
      const response = await this.apiClient.get('/api/oracle/health');
      return response.status === 200;
    } catch (error) {
      return false;
    }
  }
}
