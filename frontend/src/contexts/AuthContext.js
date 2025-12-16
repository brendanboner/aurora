import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';

const AuthContext = createContext(undefined);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkAuthStatus();
  }, []);

  const checkAuthStatus = async () => {
    try {
      // Check if user is authenticated by calling /api/auth/me
      // This will use httpOnly cookies automatically
      const response = await axios.get('/api/auth/me', {
        withCredentials: true, // Include httpOnly cookies
      });
      setUser(response.data);
    } catch (error) {
      // Not authenticated or token expired
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

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
