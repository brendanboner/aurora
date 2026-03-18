import React from 'react';
import { useAuth } from '../contexts/AuthContext';

export const ProtectedRoute = ({ children, requiredRole }) => {
  const { user, loading, isAuthenticated, login } = useAuth();

  if (loading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100vh',
        fontSize: '18px',
        color: '#666'
      }}>
        Loading...
      </div>
    );
  }

  if (!isAuthenticated) {
    // Redirect directly to Cognito login
    login();
    return null;
  }

  // Check role if required
  if (requiredRole && user) {
    const userRole = user.role || 'user';
    const allowedRoles = Array.isArray(requiredRole) ? requiredRole : [requiredRole];
    
    if (!allowedRoles.includes(userRole)) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100vh',
          padding: '20px',
          textAlign: 'center'
        }}>
          <h2>Access Denied</h2>
          <p>You don't have permission to access this page.</p>
          <p style={{ color: '#666', fontSize: '14px' }}>
            Required role: {allowedRoles.join(' or ')} | Your role: {userRole}
          </p>
        </div>
      );
    }
  }

  return <>{children}</>;
};
