import axios, { AxiosInstance } from 'axios';

export interface OracleQuery {
  user_id: string;
  question: string;
  mode: 'retrieval' | 'answer' | 'auto';
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
        'X-User-Role': 'user'
      }
    });
  }

  /**
   * Send query to Oracle service
   */
  async query(userId: string, question: string): Promise<OracleResponse> {
    try {
      console.log(`Oracle query from user ${userId}: "${question}"`);
      
      const payload: OracleQuery = {
        user_id: userId,
        question: question,
        mode: 'answer',
        options: {
          max_documents: 5,
          include_graph_context: true
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
      answer: `**🧪 Mock Response** (Enable backend authentication for real data)\n\nYour question: "${question}"\n\nThis is sample data showing how Aurora would respond. With proper backend authentication, I would query the real knowledge base for accurate, source-backed answers about Wi-Fi, networking, and Extreme Networks products.`,
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
   * Check if Oracle service is healthy
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await this.apiClient.get('/api/oracle/health');
      return response.status === 200;
    } catch (error) {
      return false;
    }
  }
}
