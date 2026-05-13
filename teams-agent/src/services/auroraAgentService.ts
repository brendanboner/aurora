import axios, { AxiosInstance } from 'axios';

export interface CreatorAgent {
  id: number;
  name: string;
  description: string | null;
  persona: string | null;
  tone_style: string;
  content_length_preference: string;
  expertise_topics: string[];
  expertise_organisations: string[];
  expertise_standards: string[];
  llm_temperature_override: number | null;
  teams_slug: string | null;
  enabled: boolean;
  follower_count?: number;
}

export class AuroraAgentService {
  private apiClient: AxiosInstance;

  constructor(userId: string, userEmail: string) {
    const baseUrl = process.env.AURORA_CONTENT_CREATOR_URL || 'http://aurora-content-creator:8000';

    this.apiClient = axios.create({
      baseURL: baseUrl,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userId,
        'X-User-Email': userEmail,
        'X-User-Role': 'user',
      },
    });
  }

  async listAgents(): Promise<CreatorAgent[]> {
    const response = await this.apiClient.get('/agents');
    return response.data;
  }

  async followAgent(agentId: number, userId: string): Promise<void> {
    await this.apiClient.post(`/agents/${agentId}/follow`, { user_id: userId });
  }

  async unfollowAgent(agentId: number, userId: string): Promise<void> {
    await this.apiClient.delete(`/agents/${agentId}/follow`, { data: { user_id: userId } });
  }

  /** Find an agent by name (case-insensitive, partial match). */
  async findAgentByName(name: string): Promise<CreatorAgent | null> {
    const agents = await this.listAgents();
    const lower = name.toLowerCase();
    return agents.find((a) => a.name.toLowerCase().includes(lower)) ?? null;
  }

  /** Resolve a Teams slug (e.g. 'aurora-wba-wifi-design-wg') to an agent. */
  async getAgentBySlug(teamsSlug: string): Promise<CreatorAgent | null> {
    try {
      const response = await this.apiClient.get(`/agents/by-slug/${encodeURIComponent(teamsSlug)}`);
      return response.data;
    } catch (err: any) {
      if (err?.response?.status === 404) return null;
      console.warn(`[AuroraAgentService] getAgentBySlug(${teamsSlug}) failed:`, err?.message);
      return null;
    }
  }

  /** Return agents the given Aurora user is following. */
  async listFollowedAgents(userId: string): Promise<CreatorAgent[]> {
    try {
      const response = await this.apiClient.get(`/agents/user/${encodeURIComponent(userId)}/followed`);
      return (response.data?.agents ?? []).map((a: any) => a.agent ?? a);
    } catch (err: any) {
      console.warn(`[AuroraAgentService] listFollowedAgents(${userId}) failed:`, err?.message);
      return [];
    }
  }
}
