import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './Sidebar.css';
import { ChatIcon, ProfileIcon, UsersIcon, KnowledgeGraphIcon, MonitoringIcon, AdminIcon, CollapseIcon } from '../components/icons';

const Sidebar = ({ isOpen, onToggle, backendStatus }) => {
  const location = useLocation();
  const [expandedMenus, setExpandedMenus] = useState({ admin: false, profile: false });

  const toggleMenu = (menu) => {
    setExpandedMenus(prev => ({ ...prev, [menu]: !prev[menu] }));
  };

  const getStatusClass = () => {
    return `status-indicator status-${backendStatus}`;
  };

  const isActive = (path) => location.pathname === path;

  return (
    <>
      {isOpen && <div className="sidebar-overlay" onClick={onToggle} />}
      
      <aside className={`sidebar ${isOpen ? 'open' : 'closed'}`}>
        <button className="hamburger-btn" onClick={onToggle} title={isOpen ? 'Collapse' : 'Expand'}>
          <CollapseIcon collapsed={!isOpen} />
        </button>

        <nav className="sidebar-nav">
          {/* Chat */}
          <Link 
            to="/" 
            className={`sidebar-item ${isActive('/') ? 'active' : ''}`}
            title="Chat"
          >
            <span className="sidebar-icon"><ChatIcon /></span>
            {isOpen && <span className="sidebar-label">Chat</span>}
          </Link>

          {/* Profile Menu with expandable submenu */}
          <div className="sidebar-menu">
            <button 
              className={`sidebar-item ${location.pathname.startsWith('/profile') ? 'active' : ''}`}
              onClick={() => toggleMenu('profile')}
              title="Profile"
            >
              <span className="sidebar-icon"><ProfileIcon /></span>
              {isOpen && (
                <>
                  <span className="sidebar-label">Profile Menu</span>
                  <span className={`expand-icon ${expandedMenus.profile ? 'expanded' : ''}`}>›</span>
                </>
              )}
            </button>
            {isOpen && expandedMenus.profile && (
              <div className="sidebar-submenu">
                <Link 
                  to="/profile/topics" 
                  className={`sidebar-subitem ${isActive('/profile/topics') ? 'active' : ''}`}
                >Topics</Link>
                <Link 
                  to="/profile/organisations" 
                  className={`sidebar-subitem ${isActive('/profile/organisations') ? 'active' : ''}`}
                >Organisations</Link>
                <Link 
                  to="/profile/people" 
                  className={`sidebar-subitem ${isActive('/profile/people') ? 'active' : ''}`}
                >People</Link>
                <Link 
                  to="/profile/notifications" 
                  className={`sidebar-subitem ${isActive('/profile/notifications') ? 'active' : ''}`}
                >Notifications</Link>
              </div>
            )}
          </div>

          {/* Admin with submenu including Monitoring */}
          <div className="sidebar-menu">
            <button 
              className={`sidebar-item ${location.pathname.startsWith('/admin') ? 'active' : ''}`}
              onClick={() => toggleMenu('admin')}
              title="Admin"
            >
              <span className="sidebar-icon"><AdminIcon /></span>
              {isOpen && (
                <>
                  <span className="sidebar-label">Admin</span>
                  <span className={`expand-icon ${expandedMenus.admin ? 'expanded' : ''}`}>›</span>
                </>
              )}
            </button>
            {isOpen && expandedMenus.admin && (
              <div className="sidebar-submenu">
                <Link 
                  to="/admin/users" 
                  className={`sidebar-subitem ${isActive('/admin/users') ? 'active' : ''}`}
                >
                  <span className="sidebar-icon"><UsersIcon size={16} /></span>
                  <span>Users</span>
                </Link>
                <Link 
                  to="/admin/knowledge-graph" 
                  className={`sidebar-subitem ${isActive('/admin/knowledge-graph') ? 'active' : ''}`}
                >
                  <span className="sidebar-icon"><KnowledgeGraphIcon size={16} /></span>
                  <span>Knowledge Graph</span>
                </Link>
                <Link 
                  to="/admin/monitoring" 
                  className={`sidebar-subitem ${isActive('/admin/monitoring') ? 'active' : ''}`}
                >
                  <span className="sidebar-icon"><MonitoringIcon size={16} /></span>
                  <span>Monitoring</span>
                </Link>
              </div>
            )}
          </div>
        </nav>

        {/* Status indicator at bottom */}
        {isOpen && (
          <div className="sidebar-footer">
            <div className="status-badge">
              <span className={getStatusClass()}></span>
              <span className="status-text">
                {backendStatus === 'connected' ? 'Connected' : 
                 backendStatus === 'disconnected' ? 'Disconnected' : 'Checking...'}
              </span>
            </div>
          </div>
        )}
      </aside>
    </>
  );
};

export default Sidebar;
