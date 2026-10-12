import axios, { AxiosInstance } from 'axios';

export interface FeedPost {
  id: number;
  agent_id: number;
  agent_name: string;
  title: string;
  body: string;
  summary: string | null;
  tags: string[];
  importance: string;
  content_length: string;
  created_at: string;
  normalized_score: number;
  sources: PostSource[];
  is_following_agent: boolean;
  user_reaction: string | null;
}

export interface PostSource {
  source_kind: string;
  url: string | null;
  title: string | null;
  confidence: number | null;
}

export interface FeedResponse {
  user_id: string;
  posts: FeedPost[];
  next_offset: number | null;
}

export class AuroraFeedService {
  private apiClient: AxiosInstance;
  private baseUrl: string;
  private devUserEmail: string;

  constructor() {
    // Content Creator Service runs separately from backend
    this.baseUrl = process.env.AURORA_CONTENT_CREATOR_URL || 'http://aurora-content-creator:8000';
    this.devUserEmail = process.env.TEST_USER_EMAIL || 'test@example.com';
    
    // Use actual Cognito UUID from environment, or generate dev ID as fallback
    const userId = process.env.TEST_USER_ID || `dev-${Buffer.from(this.devUserEmail).toString('base64').substring(0, 20)}`;
    
    this.apiClient = axios.create({
      baseURL: this.baseUrl,
      timeout: 15000,
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
   * Fetch personalized content feed for user
   */
  async getFeed(
    userId: string,
    limit: number = 10,
    offset: number = 0,
    sort: 'relevance' | 'date' = 'relevance'
  ): Promise<FeedResponse> {
    try {
      console.log(`Fetching feed for user ${userId}: limit=${limit}, sort=${sort}`);
      
      const response = await this.apiClient.get(
        '/feed',
        {
          params: {
            user_id: userId,
            limit: limit,
            offset: offset,
            sort: sort
          }
        }
      );

      console.log(`Retrieved ${response.data.posts.length} posts`);
      return response.data;
    } catch (error) {
      console.error('Error fetching feed:', error);
      throw error;
    }
  }

  /**
   * Get top N posts for daily digest
   */
  async getTopPosts(userId: string, count: number = 5): Promise<FeedPost[]> {
    const feedResponse = await this.getFeed(userId, count, 0, 'relevance');
    return feedResponse.posts.slice(0, count);
  }

  /**
   * Get recent posts (sorted by date)
   */
  async getRecentPosts(userId: string, count: number = 5): Promise<FeedPost[]> {
    const feedResponse = await this.getFeed(userId, count, 0, 'date');
    return feedResponse.posts.slice(0, count);
  }
}
