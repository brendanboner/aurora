import axios from 'axios';
import type {
  GraphData,
  GraphStats,
  QueryTransformResult,
  Entity,
  AutocompleteItem,
  SearchResult,
} from '../types/graph';

// Determine API base URL:
// 1. Use VITE_API_URL if set (from environment variables)
// 2. If the app is served under /visualisation/, use /api/visualisation/
// 3. Otherwise use /api/ or localhost:8002
const getAPIBaseURL = () => {
  // Check if environment variable is set
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  
  // Check if we're served under /visualisation/
  if (typeof window !== 'undefined' && window.location.pathname.startsWith('/visualisation/')) {
    return '/api/visualisation';
  }
  
  // Check if we have a base path set
  if (typeof window !== 'undefined' && import.meta.env.BASE_URL && import.meta.env.BASE_URL !== '/') {
    // We're served under a subpath, use relative API path
    return '/api/visualisation';
  }
  
  // Default to localhost
  return 'http://localhost:8002';
};

const API_BASE_URL = getAPIBaseURL();

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const graphApi = {
  // Get graph statistics
  getStats: async (): Promise<GraphStats> => {
    const response = await api.get<GraphStats>('/api/graph/stats');
    return response.data;
  },

  // Get graph data for visualization
  getGraphData: async (
    limit: number = 1000,
    skip: number = 0,
    nodeTypes?: string[]
  ): Promise<GraphData> => {
    const params: any = { limit, skip };
    if (nodeTypes && nodeTypes.length > 0) {
      params.node_types = nodeTypes.join(',');
    }
    const response = await api.get<GraphData>('/api/graph/data', { params });
    return response.data;
  },

  // Execute Cypher query
  executeQuery: async (query: string, parameters?: Record<string, any>): Promise<any> => {
    const response = await api.post('/api/graph/query', {
      query,
      parameters,
    });
    return response.data;
  },

  // Get node neighborhood
  getNeighborhood: async (
    nodeId: number | string,  // Support both number and string (elementId format)
    hops: number = 2,
    limit: number = 100
  ): Promise<GraphData> => {
    // URL encode the nodeId to handle special characters in elementId format
    const encodedNodeId = encodeURIComponent(String(nodeId));
    const response = await api.get<GraphData>(`/api/graph/neighborhood/${encodedNodeId}`, {
      params: { hops, limit },
    });
    return response.data;
  },

  // Search nodes
  searchNodes: async (query: string, limit: number = 100): Promise<SearchResult[]> => {
    const response = await api.get<{ results: SearchResult[] }>('/api/graph/search', {
      params: { q: query, limit },
    });
    return response.data.results;
  },

  // Autocomplete - all entities
  autocompleteAll: async (search: string, limit: number = 50): Promise<AutocompleteItem[]> => {
    const response = await api.get<{ results: AutocompleteItem[] }>('/api/autocomplete/all', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Autocomplete - topics only
  autocompleteTopics: async (search: string, limit: number = 50): Promise<Entity[]> => {
    const response = await api.get<{ results: Entity[] }>('/api/autocomplete/topics', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Autocomplete - organizations only
  autocompleteOrganizations: async (search: string, limit: number = 50): Promise<Entity[]> => {
    const response = await api.get<{ results: Entity[] }>('/api/autocomplete/organizations', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Autocomplete - people only
  autocompletePeople: async (search: string, limit: number = 50): Promise<Entity[]> => {
    const response = await api.get<{ results: Entity[] }>('/api/autocomplete/people', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Transform natural language query to Cypher
  transformQuery: async (naturalLanguageQuery: string): Promise<QueryTransformResult> => {
    const response = await api.post<QueryTransformResult>('/api/llm/transform-query', {
      natural_language_query: naturalLanguageQuery,
    });
    return response.data;
  },

  // Extract entities from text
  extractEntities: async (text: string): Promise<Entity[]> => {
    const response = await api.post<{ entities: Entity[] }>('/api/llm/extract-entities', {
      query: text,
    });
    return response.data.entities;
  },

  // Get subgraph connecting multiple entities
  getEntitySubgraph: async (
    entityIds: string[],
    hops: number = 3,
    limit: number = 500
  ): Promise<GraphData> => {
    const response = await api.post<GraphData>('/api/graph/entity-subgraph', entityIds, {
      params: { hops, limit },
    });
    return response.data;
  },
};
