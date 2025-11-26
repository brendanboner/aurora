import React from 'react';
import './Header.css';
import ExtremeNetworksLogo from './ExtremeNetworksLogo';

const Header = ({ currentUser, onLogout }) => {
  const getUserInitials = () => {
    if (!currentUser) return 'U';
    if (currentUser.display_name) {
      const names = currentUser.display_name.split(' ');
      return names.length > 1 
        ? `${names[0][0]}${names[names.length - 1][0]}`.toUpperCase()
        : names[0][0].toUpperCase();
    }
    return currentUser.email ? currentUser.email[0].toUpperCase() : 'U';
  };

  return (
    <header className="app-header">
      <div className="header-brand">
        <ExtremeNetworksLogo height={36} />
        <div className="header-title">
          <span className="brand-name"><b>Extreme</b> Platform ONE | Aurora</span>
        </div>
      </div>

      <div className="header-actions">
        <button className="header-icon-btn" title="Notifications">
          🔔
        </button>
        <div className="user-badge" title={currentUser?.email || 'User'}>
          {getUserInitials()}
        </div>
        <button className="header-icon-btn app-launcher" title="Apps">
          <span className="grid-icon">⊞</span>
        </button>
      </div>
    </header>
  );
};

export default Header;
