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
        // Teams bot is a trusted internal service on the Docker network.
        // Admin role allows it to look up and create any user's profile.
        // X-User-* headers are trusted by internal services without Cognito validation.
        'X-User-Id': userId,
        'X-User-Email': this.devUserEmail,
        'X-User-Role': 'admin',
        ...(process.env.AURORA_SERVICE_TOKEN ? { 'X-Service-Token': process.env.AURORA_SERVICE_TOKEN } : {}),
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
   * Sync Teams user to Aurora backend.
   *
   * Uses the AAD OID as the user_id when the email is a synthetic @teams.aad address,
   * so that after SSO migration (where app_users.id = Azure OID) the Teams bot
   * and web app share the same Aurora identity.
   *
   * For real email addresses (resolved via Graph API), the backend's get_or_create_user
   * logic handles email-collision migration automatically.
   */
  async syncUser(
    email: string,
    displayName: string,
    givenName?: string,
    familyName?: string
  ): Promise<AuroraUser> {
    try {
      // If this is a synthetic @teams.aad address, the local part IS the Azure OID.
      // Use it directly so the resulting Aurora user_id matches the SSO-migrated account.
      let userId: string;
      if (email.endsWith('@teams.aad')) {
        userId = email.replace('@teams.aad', '');  // Azure OID — same as post-SSO-migration ID
        console.log(`[UserService] Syncing via AAD OID as user_id: ${email} (${userId})`);
      } else {
        // Real email — let the backend's get_or_create_user handle ID allocation
        // (it will reuse the existing account found by email, or create a new one)
        userId = `teams-${Buffer.from(email).toString('base64').substring(0, 20)}`;
        console.log(`Syncing user: ${email} (${userId})`);
      }

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

      // /internal/sync-user returns {success, user_id, email, display_name} (flat)
      console.log(`User synced successfully: ${response.data.user_id}`);
      return {
        id: response.data.user_id,
        email: response.data.email,
        display_name: response.data.display_name ?? displayName,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
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
   * Get Aurora user by their internal ID.
   */
  async getUserById(userId: string): Promise<AuroraUser | null> {
    try {
      const response = await this.apiClient.get(`/users/${encodeURIComponent(userId)}`);
      return response.data;
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) return null;
      return null;
    }
  }

  /**
   * Get or create Aurora user from Teams context.
   *
   * Resolution priority for AAD OID placeholders (aad:{oid}):
   *   1. Look up the OID directly as an Aurora user ID — works after SSO migration
   *      because the user's Aurora ID becomes their Azure OID on first SSO login.
   *   2. Try Microsoft Graph API to resolve OID → real email (requires GRAPH_* env vars).
   *   3. Fall back to a synthetic @teams.aad email (last resort — avoids null user).
   *
   * This ensures Teams bot users and web-app SSO users share the same Aurora account
   * and therefore see the same agents, preferences, memberships, and feed.
   */
  async getOrCreateUser(emailOrAadPlaceholder: string, displayName: string): Promise<AuroraUser> {
    if (process.env.USE_MOCK_DATA === 'true') {
      return this.getMockUser(emailOrAadPlaceholder.startsWith('aad:')
        ? `${emailOrAadPlaceholder.substring(4)}@teams.aad`
        : emailOrAadPlaceholder);
    }

    let email = emailOrAadPlaceholder;

    if (email.startsWith('aad:')) {
      const aadObjectId = email.substring(4);

      // Priority 1: Direct ID lookup — user's Aurora ID IS the Azure OID after SSO migration.
      // Skip synthetic @teams.aad accounts so Graph API can resolve the real identity.
      const userByOid = await this.getUserById(aadObjectId);
      if (userByOid && !userByOid.email.endsWith('@teams.aad')) {
        console.log(`[UserService] Resolved AAD OID ${aadObjectId} → Aurora user ${userByOid.email} (direct ID match)`);
        return userByOid;
      }
      if (userByOid) {
        console.warn(`[UserService] AAD OID ${aadObjectId} matched synthetic @teams.aad account — continuing to Graph API for real identity`);
      }

      // Priority 2: Graph API email resolution
      const resolvedEmail = await this.lookupEmailByAadObjectId(aadObjectId);
      if (resolvedEmail) {
        email = resolvedEmail;
        console.log(`[UserService] Resolved AAD OID ${aadObjectId} → ${email} (Graph API)`);
      } else {
        // Priority 3: Synthetic fallback (last resort — creates a temporary account)
        email = `${aadObjectId}@teams.aad`;
        console.warn(`[UserService] Could not resolve AAD OID ${aadObjectId} — using synthetic email. Configure GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET to fix this.`);
      }
    }

    let user = await this.getUserByEmail(email);

    if (!user) {
      console.log(`[UserService] User ${email} not found in Aurora, creating...`);
      user = await this.syncUser(email, displayName);
    }

    return user;
  }

  /**
   * Extract email from Teams context.
   * Priority:
   *   1. activity.from.email (not always present)
   *   2. Microsoft Graph API lookup via AAD Object ID (requires GRAPH_APP_TOKEN env var)
   *   3. Emulator/webchat test email fallback
   */
  extractUserEmail(activity: any): string {
    // Try to get email from activity
    if (activity.from?.email) {
      return activity.from.email;
    }

    // Try AAD Object ID — Graph API lookup is done async in getOrCreateUser()
    if (activity.from?.aadObjectId) {
      // Return a placeholder that callers can enrich via lookupEmailByAadObjectId()
      console.warn(`[UserService] Email not in activity, will attempt Graph API lookup for AAD OID: ${activity.from.aadObjectId}`);
      return `aad:${activity.from.aadObjectId}`;
    }

    // For emulator, webchat, or any test/local channel — fall back to TEST_USER_EMAIL
    // The Teams App Test Tool sends channelId='msteams' without a real user identity.
    const testEmail = process.env.TEST_USER_EMAIL || 'test@example.com';
    console.warn(`[UserService] No user identity in activity (channelId: ${activity.channelId}), using TEST_USER_EMAIL: ${testEmail}`);
    return testEmail;
  }

  /**
   * Resolve an AAD Object ID to an email address via Microsoft Graph API.
   * Requires GRAPH_APP_TOKEN (app-level bearer token with User.Read.All permission)
   * or GRAPH_TENANT_ID + GRAPH_CLIENT_ID + GRAPH_CLIENT_SECRET for client credentials flow.
   * Falls back gracefully if Graph API is not configured.
   */
  async lookupEmailByAadObjectId(aadObjectId: string): Promise<string | null> {
    const graphToken = process.env.GRAPH_APP_TOKEN;
    const tenantId = process.env.GRAPH_TENANT_ID;
    const clientId = process.env.GRAPH_CLIENT_ID;
    const clientSecret = process.env.GRAPH_CLIENT_SECRET;

    try {
      let bearerToken = graphToken;

      // Acquire token via client credentials if individual token not set
      if (!bearerToken && tenantId && clientId && clientSecret) {
        const tokenResponse = await axios.post(
          `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
          new URLSearchParams({
            grant_type: 'client_credentials',
            client_id: clientId,
            client_secret: clientSecret,
            scope: 'https://graph.microsoft.com/.default',
          }),
          { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
        );
        bearerToken = tokenResponse.data.access_token;
      }

      if (!bearerToken) {
        console.warn('[UserService] Graph API not configured — set GRAPH_APP_TOKEN or GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET');
        return null;
      }

      const graphResponse = await axios.get(
        `https://graph.microsoft.com/v1.0/users/${aadObjectId}?$select=mail,userPrincipalName,displayName`,
        { headers: { Authorization: `Bearer ${bearerToken}` } }
      );

      return graphResponse.data.mail || graphResponse.data.userPrincipalName || null;
    } catch (error) {
      console.error(`[UserService] Graph API lookup failed for AAD OID ${aadObjectId}:`, error);
      return null;
    }
  }

  /**
   * Get mock user for testing without backend authentication
   */
  private getMockUser(email: string): AuroraUser {
    return {
      id: process.env.TEST_USER_ID || `mock-user-${Buffer.from(email).toString('base64').substring(0, 10)}`,
      email: email,
      display_name: email.split('@')[0],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
  }
}
