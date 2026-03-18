import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const AuthContext = createContext(undefined);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const checkAuthStatus = useCallback(async () => {
    try {
      // Check if user is authenticated by calling /api/auth/me
      // This will use httpOnly cookies automatically and trigger refresh if needed
      const response = await axios.get('/api/auth/me', {
        withCredentials: true, // Include httpOnly cookies
      });
      setUser(response.data);
    } catch (error) {
      // Not authenticated or token expired
      // Only log if we had a user before (to avoid spam on startup)
      if (user && error.response?.status === 401) {
        console.log('Session expired, user needs to re-authenticate');
      }
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    checkAuthStatus();
    
    // Set up periodic session check (every 5 minutes)
    const sessionCheckInterval = setInterval(checkAuthStatus, 5 * 60 * 1000);
    
    return () => clearInterval(sessionCheckInterval);
  }, [checkAuthStatus]);

  const login = () => {
    // Redirect to auth service login endpoint
    // This will redirect to Cognito Hosted UI
    window.location.href = '/api/auth/login';
  };

  const logout = async () => {
    try {
      // Redirect to logout endpoint (GET request)
      window.location.href = '/api/auth/logout';
    } catch (error) {
      console.error('Logout failed:', error);
    }
  };

  const isAuthenticated = !!user;

  return (
    <AuthContext.Provider 
      value={{ 
        user, 
        loading, 
        login, 
        logout, 
        isAuthenticated,
        checkAuthStatus // Allow manual refresh of auth status
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
