import axios, { AxiosInstance } from 'axios';

export interface AuroraUser {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  updated_at: string;
}

export class AuroraUserService {
  private apiClient: AxiosInstance;
  private baseUrl: string;
  private devUserEmail: string;

  constructor() {
    this.baseUrl = process.env.AURORA_API_URL || 'http://localhost:8000';
    this.devUserEmail = process.env.TEST_USER_EMAIL || 'test@example.com';
    
    // Use actual Cognito UUID from environment, or generate dev ID as fallback
    const userId = process.env.TEST_USER_ID || `dev-${Buffer.from(this.devUserEmail).toString('base64').substring(0, 20)}`;
    
    this.apiClient = axios.create({
      baseURL: this.baseUrl,
      timeout: 10000,
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
   * Get Aurora user by email address
   */
  async getUserByEmail(email: string): Promise<AuroraUser | null> {
    try {
      console.log(`Looking up user by email: ${email}`);
      
      const response = await this.apiClient.get(
        `/users/email/${encodeURIComponent(email)}`
      );
      
      console.log(`Found user: ${response.data.id}`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        if (error.response?.status === 404) {
          console.log(`User not found: ${email}`);
          return null;
        }
        // If auth error and mock mode enabled, return mock user
        if ((error.response?.status === 401 || error.response?.status === 403) && 
            process.env.USE_MOCK_DATA === 'true') {
          console.log('⚠️  Using mock user data (authentication unavailable)');
          return this.getMockUser(email);
        }
        console.error(`Error looking up user:`, error.response?.data);
      }
      throw error;
    }
  }

  /**
   * Sync Teams user to Aurora backend
   */
  async syncUser(
    email: string,
    displayName: string,
    givenName?: string,
    familyName?: string
  ): Promise<AuroraUser> {
    try {
      // Generate a synthetic user_id for Teams users
      const userId = `teams-${Buffer.from(email).toString('base64').substring(0, 20)}`;
      
      console.log(`Syncing user: ${email} (${userId})`);

      const response = await this.apiClient.post(
        '/internal/sync-user',
        {
          user_id: userId,
          email: email,
          display_name: displayName,
          given_name: givenName,
          family_name: familyName
        }
      );

      console.log(`User synced successfully: ${response.data.user.id}`);
      return response.data.user;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        // If auth error and mock mode enabled, return mock user
        if ((error.response?.status === 401 || error.response?.status === 403) && 
            process.env.USE_MOCK_DATA === 'true') {
          console.log('⚠️  Using mock user data for sync (authentication unavailable)');
          return this.getMockUser(email);
        }
      }
      console.error('Error syncing user:', error);
      throw error;
    }
  }

  /**
   * Get or create Aurora user from Teams context
   */
  async getOrCreateUser(email: string, displayName: string): Promise<AuroraUser> {
    let user = await this.getUserByEmail(email);

    if (!user) {
      console.log(`User ${email} not found in Aurora, creating...`);
      user = await this.syncUser(email, displayName);
    }

    return user;
  }

  /**
   * Extract email from Teams context
   * Falls back to generating from AAD Object ID if email not available
   */
  extractUserEmail(activity: any): string {
    // Try to get email from activity
    if (activity.from?.email) {
      return activity.from.email;
    }

    // Try AAD Object ID
    if (activity.from?.aadObjectId) {
      // In production, you might want to query Microsoft Graph API for the actual email
      console.warn('Email not available, using AAD Object ID');
      return `${activity.from.aadObjectId}@teams.user`;
    }

    // For emulator testing: use a default test email
    if (activity.channelId === 'emulator' || activity.channelId === 'webchat') {
      const testEmail = process.env.TEST_USER_EMAIL || 'test@example.com';
      console.warn(`Using test email for emulator: ${testEmail}`);
      return testEmail;
    }

    throw new Error('Unable to extract user email from Teams context');
  }

  /**
   * Get mock user for testing without backend authentication
   */
  private getMockUser(email: string): AuroraUser {
    return {
      id: `mock-user-${Buffer.from(email).toString('base64').substring(0, 10)}`,
      email: email,
      display_name: 'Test User',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
  }
}
