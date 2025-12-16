import axios from 'axios';

const apiClient = axios.create({
  baseURL: '/api', // Relative URL - works in dev (proxied) and production (nginx routing)
  withCredentials: true, // CRITICAL: Include httpOnly cookies in requests
  headers: {
    'Content-Type': 'application/json',
  },
});

// Response interceptor to handle 401 errors globally
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid - redirect to login
      // Don't redirect if already on login page or during auth check
      const currentPath = window.location.pathname;
      if (currentPath !== '/login' && !currentPath.includes('/api/auth/')) {
        console.log('Authentication required - redirecting to login');
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
