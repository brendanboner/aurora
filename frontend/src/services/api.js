import apiClient from '../api/client';
import axios from 'axios';

// Dedicated client for the Content Creator Service via auth gateway
const creatorApi = axios.create({
  baseURL: '/api/content_creator_service',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Mirror global 401 handling to keep sessions consistent
creatorApi.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    if (error.response?.status === 401 && !originalRequest._retry) {
      const currentPath = window.location.pathname;
      if (currentPath === '/login' || currentPath.includes('/api/auth/')) {
        return Promise.reject(error);
      }
      
      originalRequest._retry = true;
      
      try {
        console.log('creatorApi: Testing session refresh');
        
        // Create separate client to avoid interceptor loops
        const authCheckClient = axios.create({
          withCredentials: true,
          timeout: 10000,
        });
        
        const authResponse = await authCheckClient.get('/api/auth/me');
        
        if (authResponse.status === 200) {
          console.log('creatorApi: Session refreshed, retrying request');
          await new Promise(resolve => setTimeout(resolve, 100));
          return creatorApi.request(originalRequest);
        }
      } catch (authError) {
        console.log('creatorApi: Session cannot be restored - redirecting to login');
        window.location.href = '/login';
        return Promise.reject(error);
      }
    }
    return Promise.reject(error);
  }
);

// Health check - test backend service via auth gateway
export const testBackendConnection = async () => {
  try {
    const response = await apiClient.get('/backend/health');
    return response.data.status === 'ok';
  } catch (error) {
    console.error('Backend connection failed:', error);
    return false;
  }
};

// User Management
export const createUser = async (email, displayName) => {
  const response = await apiClient.post('/backend/users', {
    email,
    display_name: displayName,
  });
  return response.data;
};

export const getAllUsers = async () => {
  const response = await apiClient.get('/backend/users');
  return response.data;
};

export const getUserById = async (userId) => {
  const response = await apiClient.get(`/backend/users/${userId}`);
  return response.data;
};

export const getUserByEmail = async (email) => {
  const response = await apiClient.get(`/backend/users/email/${email}`);
  return response.data;
};

export const deleteUser = async (userId) => {
  const response = await apiClient.delete(`/backend/users/${userId}`);
  return response.data;
};

// User Preferences
export const getUserPreferences = async (userId) => {
  const response = await apiClient.get(`/backend/users/${userId}/preferences`);
  return response.data;
};

export const updateUserPreferences = async (userId, preferences) => {
  const response = await apiClient.put(`/backend/users/${userId}/preferences`, preferences);
  return response.data;
};

// Datasource listing (for workgroup preferences UI)
export const getListableDatasources = async () => {
  const response = await apiClient.get('/backend/datasources');
  return response.data;
};

// User source memberships (workgroup join/ignore preferences)
export const getUserSourceMemberships = async (userId) => {
  const response = await apiClient.get(`/backend/users/${userId}/source-memberships`);
  return response.data; // { joined: [...], ignored: [...] }
};

export const upsertSourceMembership = async (userId, datasourceId, status) => {
  const response = await apiClient.put(
    `/backend/users/${userId}/source-memberships/${encodeURIComponent(datasourceId)}`,
    { status }
  );
  return response.data;
};

export const deleteSourceMembership = async (userId, datasourceId) => {
  await apiClient.delete(
    `/backend/users/${userId}/source-memberships/${encodeURIComponent(datasourceId)}`
  );
};

// Knowledge Graph
export const getTopics = async (limit = 100, offset = 0, search = '', sortBy = 'alphabetical') => {
  const searchParam = search ? `&search=${encodeURIComponent(search)}` : '';
  const response = await apiClient.get(`/backend/graph/topics?limit=${limit}&offset=${offset}&sort_by=${sortBy}${searchParam}`);
  return response.data;
};

export const getTopicsHierarchy = async (search = '') => {
  const searchParam = search ? `?search=${encodeURIComponent(search)}` : '';
  const response = await apiClient.get(`/backend/graph/topics/hierarchy${searchParam}`);
  return response.data;
};

export const getOrganisations = async (limit = 100, offset = 0, sortBy = 'alphabetical', search = '') => {
  const searchParam = search ? `&search=${encodeURIComponent(search)}` : '';
  const response = await apiClient.get(`/backend/graph/organisations?limit=${limit}&offset=${offset}&sort_by=${sortBy}${searchParam}`);
  return response.data;
};

export const getPeople = async (limit = 100, offset = 0, sortBy = 'alphabetical', search = '') => {
  const searchParam = search ? `&search=${encodeURIComponent(search)}` : '';
  const response = await apiClient.get(`/backend/graph/people?limit=${limit}&offset=${offset}&sort_by=${sortBy}${searchParam}`);
  return response.data;
};

export const getGraphStatistics = async () => {
  const response = await apiClient.get('/backend/graph/statistics');
  return response.data;
};

// Query (Legacy backend endpoint)
export const sendQuery = async (userId, question, conversationId = null) => {
  const payload = {
    user_id: userId,
    question,
  };
  
  // Only include conversation_id if it's provided
  if (conversationId !== null) {
    payload.conversation_id = conversationId;
  }
  
  const response = await apiClient.post('/backend/query', payload);
  return response.data;
};

// Oracle Query Analysis - Pre-query quality check
export const analyzeQuery = async (question) => {
  const payload = { question };
  const response = await apiClient.post('/oracle/analyze', payload);
  return response.data;
};

// Get available datasources for @mention autocomplete
export const getDatasources = async () => {
  const response = await apiClient.get('/oracle/datasources');
  return response.data;
};

// Get available document categories
export const getCategories = async () => {
  const response = await apiClient.get('/oracle/documents/categories');
  return response.data;
};

// Get filter options (categories, topics, orgs, datasources) with bidirectional filtering
export const getFilterOptions = async (filters = {}) => {
  const payload = {
    datasource_ids: filters.datasourceIds || null,
    categories: filters.categories || null,
    topic_ids: filters.topicIds || null,
    organization_ids: filters.organizationIds || null,
  };
  const response = await apiClient.post('/oracle/documents/filter-options', payload);
  return response.data;
};

// Search documents with filters
export const searchDocuments = async (filters = {}) => {
  const payload = {
    keywords: filters.keywords || null,
    keyword_match_mode: filters.keywordMatchMode || 'any',
    datasource_ids: filters.datasourceIds || null,
    categories: filters.categories || null,
    topic_ids: filters.topicIds || null,
    organization_ids: filters.organizationIds || null,
    date_from: filters.dateFrom || null,
    date_to: filters.dateTo || null,
    limit: filters.limit || 50,
    offset: filters.offset || 0,
    sort_by: filters.sortBy || 'publish_date',
    sort_order: filters.sortOrder || 'desc',
  };
  
  const response = await apiClient.post('/oracle/documents/search', payload);
  return response.data;
};

// Get count of documents matching filters (without returning the documents)
export const getDocumentCount = async (filters = {}) => {
  const payload = {
    keywords: filters.keywords || null,
    keyword_match_mode: filters.keywordMatchMode || 'any',
    datasource_ids: filters.datasourceIds || null,
    categories: filters.categories || null,
    topic_ids: filters.topicIds || null,
    organization_ids: filters.organizationIds || null,
    date_from: filters.dateFrom || null,
    date_to: filters.dateTo || null,
  };
  
  const response = await apiClient.post('/oracle/documents/count', payload);
  return response.data;
};

// Oracle Query - Enhanced question-answering with graph-aware RAG
export const sendOracleQuery = async (userId, question, options = {}) => {
  const payload = {
    user_id: userId,
    question,
    mode: options.mode || 'answer', // 'retrieval', 'answer', or 'auto'
    options: {
      max_documents: options.maxDocuments || 20,
      include_graph_context: options.includeGraphContext !== false,
      date_start: options.dateStart || null,
      date_end: options.dateEnd || null,
      topics: options.topics || null,
      organizations: options.organizations || null,
      datasource_ids: options.datasourceIds || null,
      recency_boost: options.recencyBoost !== false,
      personalize: options.personalize || 'auto', // 'off', 'on', or 'auto'
      pipeline_override: options.pipelineOverride || null, // 'fast', 'baseline', or null for A/B test
    },
  };
  
  const response = await apiClient.post('/oracle/query', payload);
  return response.data;
};

// Oracle Enhance - Get detailed answer by analyzing document content (Phase 5)
export const sendEnhanceQuery = async (question, documents) => {
  // documents should be array of { url, datasource_id, title }
  const payload = {
    question,
    documents: documents.map(doc => ({
      url: doc.url,
      datasource_id: doc.datasource_id || 'wfa', // Default to 'wfa' if not specified
      title: doc.title || null,
    })),
  };
  
  const response = await apiClient.post('/oracle/enhance', payload);
  return response.data;
};

// Oracle Query History - Phase 6 Analytics
export const getOracleQueryHistory = async (options = {}) => {
  const params = new URLSearchParams();
  if (options.days) params.append('days', options.days);
  if (options.limit) params.append('limit', options.limit);
  if (options.offset) params.append('offset', options.offset);
  if (options.intent) params.append('intent', options.intent);
  if (options.minConfidence) params.append('min_confidence', options.minConfidence);
  if (options.maxConfidence) params.append('max_confidence', options.maxConfidence);
  if (options.hasFeedback !== undefined) params.append('has_feedback', options.hasFeedback);
  
  const response = await apiClient.get(`/oracle/history?${params.toString()}`);
  return response.data;
};

export const getOracleQueryDetail = async (queryId) => {
  const response = await apiClient.get(`/oracle/history/${queryId}`);
  return response.data;
};

export const getOracleQueryStats = async (days = 7) => {
  const response = await apiClient.get(`/oracle/history/stats?days=${days}`);
  return response.data;
};

// Oracle Feedback - Submit user feedback on query responses
export const submitOracleFeedback = async (queryId, feedback, options = {}) => {
  const payload = {
    query_id: queryId,
    feedback, // 'helpful' or 'not_helpful'
    comment: options.comment || null,
    intent: options.intent || null,
    mode: options.mode || null,
  };
  
  const response = await apiClient.post('/oracle/feedback', payload);
  return response.data;
};

// Oracle Settings - Get Oracle service configuration (fast pipeline, etc.)
export const getOracleSettings = async () => {
  const response = await apiClient.get('/oracle/admin/config/query-settings');
  return response.data;
};

// Chat Conversations
export const getConversations = async (limit = 50) => {
  const response = await apiClient.get(`/backend/conversations?limit=${limit}`);
  return response.data;
};

export const getConversationDetail = async (conversationId) => {
  const response = await apiClient.get(`/backend/conversations/${conversationId}`);
  return response.data;
};

export const deleteConversation = async (conversationId) => {
  const response = await apiClient.delete(`/backend/conversations/${conversationId}`);
  return response.data;
};

// Admin - Chat Analytics
export const getAllConversations = async (limit = 100, userId = null) => {
  let url = `/backend/admin/conversations?limit=${limit}`;
  if (userId) {
    url += `&user_id=${userId}`;
  }
  const response = await apiClient.get(url);
  return response.data;
};

export const getConversationDetailAdmin = async (conversationId) => {
  const response = await apiClient.get(`/backend/admin/conversations/${conversationId}`);
  return response.data;
};

// Admin - User Management
export const syncUserToGraph = async (userId) => {
  const response = await apiClient.post(`/backend/admin/users/${userId}/sync`);
  return response.data;
};

// Content Creator Service ----------------------------------------------------
export const fetchSocialFeed = async (
  userId,
  limit = 20,
  offset = 0,
  sort = 'relevance',
  q = undefined,
  personalAgentId = undefined
) => {
  const params = { user_id: userId, limit, offset, sort };
  if (q !== undefined) {
    params.q = q;
  }
  if (personalAgentId) {
    params.personal_agent_id = personalAgentId;
  }
  const response = await apiClient.get('/content_creator_service/feed', {
    params,
  });
  return response.data;
};

export const likePost = async (postId, userId) => {
  const response = await apiClient.post(`/content_creator_service/posts/${postId}/like`, { user_id: userId });
  return response.data;
};

export const dislikePost = async (postId, userId) => {
  const response = await apiClient.post(`/content_creator_service/posts/${postId}/dislike`, { user_id: userId });
  return response.data;
};

export const getCreatorAgents = async (includeDisabled = false) => {
  const response = await apiClient.get('/content_creator_service/agents', { params: { include_disabled: includeDisabled } });
  return response.data;
};

export const createCreatorAgent = async (payload) => {
  const response = await apiClient.post('/content_creator_service/agents', payload);
  return response.data;
};

export const parseLinkedInProfile = async (profileText) => {
  const response = await apiClient.post('/content_creator_service/agents/from-linkedin', {
    profile_text: profileText,
  });
  return response.data;
};

export const updateCreatorAgent = async (agentId, payload) => {
  const response = await apiClient.put(`/content_creator_service/agents/${agentId}`, payload);
  return response.data;
};

export const deleteCreatorAgent = async (agentId) => {
  const response = await apiClient.delete(`/content_creator_service/agents/${agentId}`);
  return response.data;
};

export const followCreatorAgent = async (agentId, userId) => {
  const response = await apiClient.post(`/content_creator_service/agents/${agentId}/follow`, { user_id: userId });
  return response.data;
};

export const unfollowCreatorAgent = async (agentId, userId) => {
  const response = await apiClient.post(`/content_creator_service/agents/${agentId}/unfollow`, { user_id: userId });
  return response.data;
};

export const getUserFollowedAgents = async (userId) => {
  const response = await apiClient.get(`/content_creator_service/agents/user/${userId}/followed`);
  return response.data;
};

export const updateAgentPreferences = async (agentId, userId, relevance, lengthPreference) => {
  const response = await apiClient.put(`/content_creator_service/agents/${agentId}/preferences`, {
    user_id: userId,
    relevance,
    length_preference: lengthPreference,
  });
  return response.data;
};

export const triggerAgentPost = async (agentId, force = true, limit = 5) => {
  const response = await apiClient.post(`/content_creator_service/agents/${agentId}/trigger`, { force, limit });
  return response.data;
};

// Personal (My) Agents -------------------------------------------------------

export const getMyAgents = async () => {
  const response = await apiClient.get('/content_creator_service/user_agents');
  return response.data;
};

export const createMyAgent = async (payload) => {
  const response = await apiClient.post('/content_creator_service/user_agents', payload);
  return response.data;
};

export const updateMyAgent = async (agentId, payload) => {
  const response = await apiClient.put(`/content_creator_service/user_agents/${agentId}`, payload);
  return response.data;
};

export const deleteMyAgent = async (agentId) => {
  const response = await apiClient.delete(`/content_creator_service/user_agents/${agentId}`);
  return response.data;
};

export const triggerMyAgentGeneration = async (agentId) => {
  const response = await apiClient.post(`/content_creator_service/user_agents/${agentId}/generate`);
  return response.data;
};

export const submitMyAgentPostFeedback = async (payload) => {
  const response = await apiClient.post('/content_creator_service/user_agents/feedback', payload);
  return response.data;
};

export const purgeAgentPosts = async (agentId) => {
  const response = await apiClient.delete(`/content_creator_service/posts/agent/${agentId}/purge`);
  return response.data;
};

export const purgeAllPosts = async () => {
  const response = await apiClient.delete('/content_creator_service/posts/purge_all');
  return response.data;
};

export const getPreferenceProfile = async (userId) => {
  const response = await apiClient.get(`/content_creator_service/preferences/${userId}`);
  return response.data;
};

export const updatePreferenceProfile = async (userId, payload) => {
  const response = await apiClient.put(`/content_creator_service/preferences/${userId}`, payload);
  return response.data;
};

// Feedback
export const submitFeedback = async (feedbackText, category) => {
  const response = await apiClient.post('/backend/feedback/submit', {
    feedback_text: feedbackText,
    category: category
  });
  return response.data;
};

// ==================== Document Upload ====================

/**
 * Upload documents to the retriever service.
 * @param {FormData} formData - Form data with files, titles, categories, and related_events
 */
export const uploadDocuments = async (formData) => {
  const response = await apiClient.post('/retriever/submit/documents', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
  return response.data;
};

/**
 * Get documents uploaded by the current user.
 */
export const getUserUploads = async (limit = 50, offset = 0) => {
  const response = await apiClient.get(`/backend/documents/user-uploads?limit=${limit}&offset=${offset}`);
  return response.data;
};

/**
 * Get available document categories for uploads.
 */
export const getDocumentCategories = async () => {
  const response = await apiClient.get('/backend/documents/categories');
  return response.data;
};

/**
 * Get a presigned S3 URL for downloading a document.
 * @param {string} urlHash - Document url_hash
 */
export const getDocumentDownloadUrl = async (urlHash) => {
  const response = await apiClient.get(`/backend/documents/${urlHash}/download`);
  return response.data.download_url;
};

/**
 * Get documents related to an event.
 * @param {string} urlHash - Event url_hash
 */
export const getEventDocuments = async (urlHash) => {
  const response = await apiClient.get(`/backend/events/${urlHash}/documents`);
  return response.data.documents || [];
};

/**
 * Get count of documents related to an event.
 * @param {string} urlHash - Event url_hash
 */
export const getEventDocumentCount = async (urlHash) => {
  const response = await apiClient.get(`/backend/events/${urlHash}/document-count`);
  return response.data.count;
};

/**
 * Update a document's metadata (title, category).
 * @param {string} urlHash - Document url_hash
 * @param {object} updates - Fields to update (title, category)
 */
export const updateDocument = async (urlHash, updates) => {
  const response = await apiClient.patch(`/backend/documents/${urlHash}`, updates);
  return response.data;
};

/**
 * Delete a document.
 * @param {string} urlHash - Document url_hash
 */
export const deleteDocument = async (urlHash) => {
  const response = await apiClient.delete(`/backend/documents/${urlHash}`);
  return response.data;
};

/**
 * Get events related to a document.
 * @param {string} urlHash - Document url_hash
 */
export const getDocumentEvents = async (urlHash) => {
  const response = await apiClient.get(`/backend/documents/${urlHash}/events`);
  return response.data.events;
};

export const getMyFeedback = async (limit = 50) => {
  const response = await apiClient.get(`/backend/feedback/my-feedback?limit=${limit}`);
  return response.data;
};

// Admin - Feedback Management
export const getAllFeedback = async (filters = {}) => {
  const params = new URLSearchParams();
  if (filters.status) params.append('status', filters.status);
  if (filters.category) params.append('category', filters.category);
  if (filters.priority) params.append('priority', filters.priority);
  if (filters.limit) params.append('limit', filters.limit);
  if (filters.offset) params.append('offset', filters.offset);
  
  const response = await apiClient.get(`/backend/feedback/all?${params.toString()}`);
  return response.data;
};

export const getFeedbackStatistics = async () => {
  const response = await apiClient.get('/backend/feedback/statistics');
  return response.data;
};

export const getFeedbackById = async (feedbackId) => {
  const response = await apiClient.get(`/backend/feedback/${feedbackId}`);
  return response.data;
};

export const updateFeedbackStatus = async (feedbackId, status, priority = null) => {
  const payload = { status };
  if (priority) {
    payload.priority = priority;
  }
  const response = await apiClient.patch(`/backend/feedback/${feedbackId}`, payload);
  return response.data;
};

export const deleteFeedback = async (feedbackId) => {
  const response = await apiClient.delete(`/backend/feedback/${feedbackId}`);
  return response.data;
};

// ==================== Curator Service ====================

/**
 * Get topic organization statistics from the curator service.
 * Returns counts of total, organized, and unorganized topics.
 */
export const getCuratorTopicStats = async () => {
  const response = await apiClient.get('/curator/topics/stats');
  return response.data;
};

/**
 * Get curator service status including job states.
 */
export const getCuratorStatus = async () => {
  const response = await apiClient.get('/curator/status');
  return response.data;
};

/**
 * Trigger topic curation job manually.
 * Requires admin role.
 */
export const triggerTopicCuration = async () => {
  const response = await apiClient.post('/curator/trigger/topics');
  return response.data;
};

/**
 * Trigger event reconciliation job manually.
 * Requires admin role.
 */
export const triggerEventReconciliation = async () => {
  const response = await apiClient.post('/curator/trigger/reconcile');
  return response.data;
};

export default apiClient;
