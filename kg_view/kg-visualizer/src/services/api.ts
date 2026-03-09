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
// 2. If BASE_URL is /visualisation/, use /api/visualisation
// 3. Otherwise use localhost:8002 (development)
const getAPIBaseURL = () => {
  console.log('[KG Visualizer] Detection - BASE_URL:', import.meta.env.BASE_URL);
  console.log('[KG Visualizer] Detection - VITE_API_URL:', import.meta.env.VITE_API_URL);
  
  // Check if environment variable is set
  if (import.meta.env.VITE_API_URL) {
    console.log('[KG Visualizer] Using VITE_API_URL:', import.meta.env.VITE_API_URL);
    return import.meta.env.VITE_API_URL;
  }
  
  // Check Vite's BASE_URL (set during build via VITE_BASE_PATH)
  const baseUrl = import.meta.env.BASE_URL;
  if (baseUrl && baseUrl.includes('visualisation')) {
    console.log('[KG Visualizer] Detected visualisation base path, using /api/visualisation');
    return '/api/visualisation';
  }
  
  // Check if we're in a browser environment and can check the URL
  if (typeof window !== 'undefined') {
    const currentUrl = window.location.href;
    const currentPath = window.location.pathname;
    
    console.log('[KG Visualizer] Detection - Current URL:', currentUrl);
    console.log('[KG Visualizer] Detection - Current Path:', currentPath);
    
    if (currentUrl.includes('/visualisation/') || currentPath.startsWith('/visualisation/')) {
      console.log('[KG Visualizer] Detected /visualisation/ in URL, using /api/visualisation');
      return '/api/visualisation';
    }
  }
  
  // Default to localhost for development
  console.log('[KG Visualizer] Using localhost:8002 (development mode)');
  return 'http://localhost:8002';
};

const API_BASE_URL = getAPIBaseURL();

// Log the API base URL for debugging
console.log('[KG Visualizer] API Base URL:', API_BASE_URL);
console.log('[KG Visualizer] Current pathname:', typeof window !== 'undefined' ? window.location.pathname : 'SSR');

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Include cookies for authentication
});

// Add request interceptor for logging
api.interceptors.request.use(
  (config) => {
    console.log('[KG Visualizer] API Request:', config.method?.toUpperCase(), config.url);
    return config;
  },
  (error) => {
    console.error('[KG Visualizer] Request error:', error);
    return Promise.reject(error);
  }
);

// Add response interceptor to handle authentication errors
api.interceptors.response.use(
  (response) => {
    console.log('[KG Visualizer] API Response:', response.status, response.config.url);
    return response;
  },
  (error) => {
    console.error('[KG Visualizer] API Error:', error.response?.status, error.config?.url, error.message);
    // If we get a 401 Unauthorized, redirect to login
    if (error.response?.status === 401) {
      // Only redirect if we're in a browser environment and not in development
      if (typeof window !== 'undefined' && !window.location.hostname.includes('localhost')) {
        // Redirect to login, which will redirect back to home after auth
        // User can then navigate back to /visualisation/ (they'll have cookies)
        console.log('[KG Visualizer] Authentication required. Redirecting to login...');
        window.location.href = '/api/auth/login';
      }
    }
    return Promise.reject(error);
  }
);

export const graphApi = {
  // Get graph statistics
  getStats: async (): Promise<GraphStats> => {
    const response = await api.get<GraphStats>('/graph/stats');
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
    const response = await api.get<GraphData>('/graph/data', { params });
    return response.data;
  },

  // Get balanced graph data with diverse node type representation (recommended default)
  getBalancedGraphData: async (
    limit: number = 1000,
    importanceThreshold: number = 0.0
  ): Promise<GraphData> => {
    const response = await api.get<GraphData>('/graph/balanced-data', {
      params: { limit, importance_threshold: importanceThreshold },
    });
    return response.data;
  },

  // Execute Cypher query
  executeQuery: async (query: string, parameters?: Record<string, any>): Promise<any> => {
    const response = await api.post('/graph/query', {
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
    const response = await api.get<GraphData>(`/graph/neighborhood/${encodedNodeId}`, {
      params: { hops, limit },
    });
    return response.data;
  },

  // Search nodes
  searchNodes: async (query: string, limit: number = 100): Promise<SearchResult[]> => {
    const response = await api.get<{ results: SearchResult[] }>('/graph/search', {
      params: { q: query, limit },
    });
    return response.data.results;
  },

  // Autocomplete - all entities
  autocompleteAll: async (search: string, limit: number = 50): Promise<AutocompleteItem[]> => {
    const response = await api.get<{ results: AutocompleteItem[] }>('/autocomplete/all', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Autocomplete - topics only
  autocompleteTopics: async (search: string, limit: number = 50): Promise<Entity[]> => {
    const response = await api.get<{ results: Entity[] }>('/autocomplete/topics', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Autocomplete - organizations only
  autocompleteOrganizations: async (search: string, limit: number = 50): Promise<Entity[]> => {
    const response = await api.get<{ results: Entity[] }>('/autocomplete/organizations', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Autocomplete - people only
  autocompletePeople: async (search: string, limit: number = 50): Promise<Entity[]> => {
    const response = await api.get<{ results: Entity[] }>('/autocomplete/people', {
      params: { search, limit },
    });
    return response.data.results;
  },

  // Transform natural language query to Cypher
  transformQuery: async (naturalLanguageQuery: string): Promise<QueryTransformResult> => {
    const response = await api.post<QueryTransformResult>('/llm/transform-query', {
      natural_language_query: naturalLanguageQuery,
    });
    return response.data;
  },

  // Extract entities from text
  extractEntities: async (text: string): Promise<Entity[]> => {
    const response = await api.post<{ entities: Entity[] }>('/llm/extract-entities', {
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
    const response = await api.post<GraphData>('/graph/entity-subgraph', entityIds, {
      params: { hops, limit },
    });
    return response.data;
  },
};
