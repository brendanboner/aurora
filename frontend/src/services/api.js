import apiClient from '../api/client';

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

// Knowledge Graph
export const getTopics = async (limit = 1000) => {
  const response = await apiClient.get(`/backend/graph/topics?limit=${limit}`);
  return response.data;
};

export const getOrganisations = async (limit = 1000) => {
  const response = await apiClient.get(`/backend/graph/organisations?limit=${limit}`);
  return response.data;
};

export const getPeople = async (limit = 1000) => {
  const response = await apiClient.get(`/backend/graph/people?limit=${limit}`);
  return response.data;
};

export const getGraphStatistics = async () => {
  const response = await apiClient.get('/backend/graph/statistics');
  return response.data;
};

// Query
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

export default apiClient;
