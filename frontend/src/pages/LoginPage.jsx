import React, { useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';
import './LoginPage.css';

const LoginPage = () => {
  const { login, isAuthenticated } = useAuth();

  // Auto-redirect to Cognito login
  useEffect(() => {
    // Only redirect if not already authenticated
    if (!isAuthenticated) {
      // Small delay to show loading message (optional)
      const timer = setTimeout(() => {
        login();
      }, 500);
      
      return () => clearTimeout(timer);
    }
  }, [login, isAuthenticated]);

  // If already authenticated, redirect to home
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="login-page">
      <div className="login-container">
        <div className="login-card">
          <div className="login-header">
            <h1>Welcome to Aurora</h1>
            <p className="login-subtitle">Your Knowledge Management Assistant</p>
          </div>
          
          <div className="login-content">
            <p className="login-description">
              Redirecting to secure login...
            </p>
            
            <div className="login-spinner">
              <div className="spinner"></div>
            </div>
            
            <p className="login-info" style={{ marginTop: '20px' }}>
              Not redirected? <button onClick={login} className="link-button">Click here to login</button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
