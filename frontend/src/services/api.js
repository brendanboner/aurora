import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Health check
export const testBackendConnection = async () => {
  try {
    const response = await api.get('/health');
    return response.data.status === 'ok';
  } catch (error) {
    console.error('Backend connection failed:', error);
    return false;
  }
};

// User Management
export const createUser = async (email, displayName) => {
  const response = await api.post('/users', {
    email,
    display_name: displayName,
  });
  return response.data;
};

export const getAllUsers = async () => {
  const response = await api.get('/users');
  return response.data;
};

export const getUserById = async (userId) => {
  const response = await api.get(`/users/${userId}`);
  return response.data;
};

export const getUserByEmail = async (email) => {
  const response = await api.get(`/users/email/${email}`);
  return response.data;
};

export const deleteUser = async (userId) => {
  const response = await api.delete(`/users/${userId}`);
  return response.data;
};

// User Preferences
export const getUserPreferences = async (userId) => {
  const response = await api.get(`/users/${userId}/preferences`);
  return response.data;
};

export const updateUserPreferences = async (userId, preferences) => {
  const response = await api.put(`/users/${userId}/preferences`, preferences);
  return response.data;
};

// Knowledge Graph
export const getTopics = async (limit = 1000) => {
  const response = await api.get(`/graph/topics?limit=${limit}`);
  return response.data;
};

export const getOrganisations = async (limit = 1000) => {
  const response = await api.get(`/graph/organisations?limit=${limit}`);
  return response.data;
};

export const getPeople = async (limit = 1000) => {
  const response = await api.get(`/graph/people?limit=${limit}`);
  return response.data;
};

export const getGraphStatistics = async () => {
  const response = await api.get('/graph/statistics');
  return response.data;
};

// Query
export const sendQuery = async (userId, question) => {
  const response = await api.post('/query', {
    user_id: userId,
    question,
  });
  return response.data;
};

export default api;
