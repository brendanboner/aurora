import React, { useState, useEffect, useRef } from 'react';
import './Header.css';
import ExtremeNetworksLogo from './ExtremeNetworksLogo';
import { useAuth } from '../contexts/AuthContext';

const Header = ({ onMenuToggle }) => {
  const { user, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef(null);

  const getUserInitials = () => {
    if (!user) return 'U';
    
    // Try to get initials from email
    if (user.email) {
      const emailParts = user.email.split('@')[0].split('.');
      if (emailParts.length > 1) {
        return `${emailParts[0][0]}${emailParts[1][0]}`.toUpperCase();
      }
      return user.email[0].toUpperCase();
    }
    
    return 'U';
  };

  const handleLogout = () => {
    setShowUserMenu(false);
    logout();
  };

  const toggleUserMenu = () => {
    setShowUserMenu(!showUserMenu);
  };

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setShowUserMenu(false);
      }
    };

    if (showUserMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showUserMenu]);

  return (
    <header className="app-header">
      <div className="header-brand">
        <button className="mobile-menu-btn" onClick={onMenuToggle} title="Menu">
          ☰
        </button>
        <ExtremeNetworksLogo height={36} />
        <div className="header-title">
          <span className="brand-name"><b>AURORA</b></span>
        </div>
      </div>

      <div className="header-actions">
        <div 
          className="user-badge-container"
          ref={menuRef}
        >
          <div 
            className="user-badge" 
            title={user?.email || 'User'}
            onClick={toggleUserMenu}
          >
            {getUserInitials()}
          </div>
          {showUserMenu && (
            <div className="user-menu">
              <div className="user-menu-info">
                <div className="user-menu-email">{user?.email}</div>
                <div className="user-menu-role">Role: {user?.role || 'user'}</div>
              </div>
              <button className="user-menu-logout" onClick={handleLogout}>
                Logout
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};

export default Header;
