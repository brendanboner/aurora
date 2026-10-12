import React, { useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';
import A1LogoMark from '../components/A1LogoMark';
import './LoginPage.css';

const LoginPage = () => {
  const { login, isAuthenticated } = useAuth();

  useEffect(() => {
    if (!isAuthenticated) {
      const timer = setTimeout(() => {
        login();
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [login, isAuthenticated]);

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="login-page bg-nova-glow">
      <div className="login-container">
        <div className="login-card">
          <div className="login-header">
            <A1LogoMark size={56} />
            <h1 className="login-title">Aurora</h1>
            <span className="login-by-badge">by the Office of the CTO</span>
            <p className="login-subtitle">Wi-Fi Alliance Knowledge Assistant</p>
          </div>

          <div className="login-content">
            <p className="login-description">
              Redirecting to secure login…
            </p>

            <div className="login-spinner">
              <div className="spinner"></div>
            </div>

            <p className="login-info">
              Not redirected?{' '}
              <button onClick={login} className="link-button">Click here to login</button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
