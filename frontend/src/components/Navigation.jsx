import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import './Navigation.css';

const Navigation = ({ backendStatus, currentUser, onLogout }) => {
  const location = useLocation();

  const getStatusClass = () => {
    return `status-indicator status-${backendStatus}`;
  };

  const getStatusText = () => {
    switch (backendStatus) {
      case 'connected':
        return 'Connected';
      case 'disconnected':
        return 'Disconnected';
      case 'checking':
        return 'Checking...';
      default:
        return 'Unknown';
    }
  };

  return (
    <nav className="navigation">
      <div className="nav-container">
        <div className="nav-brand">
          <span className="nav-logo">🌟</span>
          <span className="nav-title">Aurora</span>
        </div>

        <div className="nav-links">
          <Link 
            to="/" 
            className={`nav-link ${location.pathname === '/' ? 'active' : ''}`}
          >
            <span className="nav-icon">💬</span>
            Chat
          </Link>
          <Link 
            to="/profile" 
            className={`nav-link ${location.pathname === '/profile' ? 'active' : ''}`}
          >
            <span className="nav-icon">👤</span>
            Profile
          </Link>
          <Link 
            to="/admin" 
            className={`nav-link ${location.pathname === '/admin' ? 'active' : ''}`}
          >
            <span className="nav-icon">⚙️</span>
            Admin
          </Link>
        </div>

        <div className="nav-status">
          <div className="status-badge">
            <span className={getStatusClass()}></span>
            <span className="status-text">{getStatusText()}</span>
          </div>
          
          {currentUser && (
            <div className="user-info">
              <span className="user-name">{currentUser.display_name || currentUser.email}</span>
              <button onClick={onLogout} className="btn-logout" title="Logout">
                🚪
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Navigation;
