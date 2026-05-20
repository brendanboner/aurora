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
    if (!user) return 'U';
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
      <div className="header-brand">
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
