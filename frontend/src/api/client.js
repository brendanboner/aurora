import axios from 'axios';

const apiClient = axios.create({
  baseURL: '/api', // Relative URL - works in dev (proxied) and production (nginx routing)
  withCredentials: true, // CRITICAL: Include httpOnly cookies in requests
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add request retry logic for race conditions
apiClient.interceptors.request.use((config) => {
  // Add retry count to config
  config.retryCount = config.retryCount || 0;
  return config;
});

// Response interceptor to handle 401 errors globally
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    if (error.response?.status === 401 && !originalRequest._retry) {
      const currentPath = window.location.pathname;
      
      // Don't redirect if already on login page or during auth operations
      if (currentPath === '/login' || currentPath.includes('/api/auth/')) {
        return Promise.reject(error);
      }

      // Mark this request as retried to prevent infinite loops
      originalRequest._retry = true;

      // The auth service automatically handles token refresh when it detects
      // an expired access token. Let's test this by making a simple auth check
      // that goes through the auth service's refresh mechanism.
      try {
        console.log('Access token may have expired, testing session refresh');
        
        // Create a separate axios instance for the auth check to avoid interceptor loops
        const authCheckClient = axios.create({
          withCredentials: true,
          timeout: 10000,
        });
        
        // Make auth check that will trigger refresh if needed
        const authResponse = await authCheckClient.get('/api/auth/me');
        
        if (authResponse.status === 200) {
          console.log('Session refreshed successfully, retrying original request');
          // Small delay to ensure cookies are updated
          await new Promise(resolve => setTimeout(resolve, 100));
          return apiClient.request(originalRequest);
        }
      } catch (authError) {
        // If auth check failed, session is truly expired
        console.log('Session cannot be restored - redirecting to login');
        window.location.href = '/login';
        return Promise.reject(error);
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
