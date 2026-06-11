import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import './Header.css';
import A1LogoMark from './A1LogoMark';
import { useAuth } from '../contexts/AuthContext';

const Header = ({ onMenuToggle, isMenuOpen }) => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef(null);

  const getUserInitials = () => {
    if (!user?.email) return 'U';
    const local = user.email.split('@')[0];
    const parts = local.split(/[._-]+/).filter(Boolean);
    if (parts.length > 1) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    }
    const letters = local.replace(/[^a-zA-Z]/g, '') || local;
    return letters.slice(0, 2).toUpperCase() || 'U';
  };

  const handleLogout = () => {
    setShowUserMenu(false);
    logout();
  };

  const toggleUserMenu = () => {
    setShowUserMenu(!showUserMenu);
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setShowUserMenu(false);
      }
    };
    if (showUserMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showUserMenu]);

  return (
    <header className="app-header">
      {/*
        The hamburger is positioned OUTSIDE .header-brand (which has overflow:hidden)
        so it can never be clipped on narrow viewports. It is flex-shrink:0 and always
        the first visible element, giving users access to navigation on any screen size.
      */}
      <button
        className={`mobile-menu-btn ${isMenuOpen ? 'open' : ''}`}
        onClick={onMenuToggle}
        title="Menu"
        aria-label="Toggle navigation menu"
        aria-expanded={isMenuOpen}
      >
        <span></span>
        <span></span>
        <span></span>
      </button>

      <div className="header-brand">
        <A1LogoMark size={34} />

        <div className="header-divider" />

        <div className="header-wordmark">
          <span className="header-product-name">Aurora</span>
          <span className="header-by-badge">by the Office of the CTO</span>
        </div>
      </div>

      <div className="header-actions">
        <div className="user-badge-container" ref={menuRef}>
          <button
            className="user-avatar-btn"
            title={user?.email || 'User'}
            onClick={toggleUserMenu}
            aria-label="User menu"
          >
            <span className="user-initials">{getUserInitials()}</span>
          </button>

          {showUserMenu && (
            <div className="user-menu">
              <div className="user-menu-info">
                <div className="user-menu-email">{user?.email}</div>
                <div className="user-menu-role">{user?.role || 'user'}</div>
              </div>
              <button
                className="user-menu-item"
                onClick={() => { setShowUserMenu(false); navigate('/profile/preferences'); }}
              >
                Preferences
              </button>
              <button className="user-menu-item user-menu-logout" onClick={handleLogout}>
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};

export default Header;
