import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './Sidebar.css';
import { ChatIcon, ProfileIcon, UsersIcon, KnowledgeGraphIcon, MonitoringIcon, AdminIcon, CollapseIcon, CalendarIcon, StarIcon, SearchIcon, TargetIcon, SettingsIcon, BookIcon, FeedbackIcon, AlertCircleIcon } from '../components/icons';
import { useAuth } from '../contexts/AuthContext';

const Sidebar = ({ isOpen, onToggle, backendStatus }) => {
  const location = useLocation();
  const { user } = useAuth();
  const [expandedMenus, setExpandedMenus] = useState({ admin: false, profile: false });
  
  // Check if user has admin or superadmin role
  const isAdmin = user && (user.role === 'admin' || user.role === 'superadmin');

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

          {/* Document Search */}
          <Link 
            to="/documents" 
            className={`sidebar-item ${isActive('/documents') ? 'active' : ''}`}
            title="Document Search"
          >
            <span className="sidebar-icon"><SearchIcon /></span>
            {isOpen && <span className="sidebar-label">Document Search</span>}
          </Link>

          {/* Creator Feed */}
          <Link 
            to="/feed" 
            className={`sidebar-item ${isActive('/feed') ? 'active' : ''}`}
            title="Creator Feed"
          >
            <span className="sidebar-icon"><StarIcon /></span>
            {isOpen && <span className="sidebar-label">Creator Feed</span>}
          </Link>

          {/* Events */}
          <Link 
            to="/events" 
            className={`sidebar-item ${isActive('/events') || location.pathname.startsWith('/events/') ? 'active' : ''}`}
            title="Events"
          >
            <span className="sidebar-icon"><CalendarIcon /></span>
            {isOpen && <span className="sidebar-label">Events</span>}
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
                  to="/profile/agents" 
                  className={`sidebar-subitem ${isActive('/profile/agents') ? 'active' : ''}`}
                >Follow Agents</Link>
                <Link 
                  to="/profile/notifications" 
                  className={`sidebar-subitem ${isActive('/profile/notifications') ? 'active' : ''}`}
                >Notifications</Link>
              </div>
            )}
          </div>

          {/* Admin with submenu including Monitoring */}
          {isAdmin && (
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
                  <Link 
                    to="/admin/agents" 
                    className={`sidebar-subitem ${isActive('/admin/agents') ? 'active' : ''}`}
                  >
                    <span className="sidebar-icon"><StarIcon size={16} /></span>
                    <span>Creator Agents</span>
                  </Link>
                  <Link 
                    to="/admin/system-config" 
                    className={`sidebar-subitem ${isActive('/admin/system-config') ? 'active' : ''}`}
                  >
                    <span className="sidebar-icon"><SettingsIcon size={16} /></span>
                    <span>System Config</span>
                  </Link>
                  <Link 
                    to="/admin/content-quality" 
                    className={`sidebar-subitem ${isActive('/admin/content-quality') ? 'active' : ''}`}
                  >
                    <span className="sidebar-icon"><TargetIcon size={16} /></span>
                    <span>Content Quality</span>
                  </Link>
                  <Link 
                    to="/admin/chat-sessions" 
                    className={`sidebar-subitem ${isActive('/admin/chat-sessions') ? 'active' : ''}`}
                  >
                    <span className="sidebar-icon"><ChatIcon size={16} /></span>
                    <span>Chat Sessions</span>
                  </Link>
                  <Link 
                    to="/admin/dlq" 
                    className={`sidebar-subitem ${isActive('/admin/dlq') ? 'active' : ''}`}
                  >
                    <span className="sidebar-icon"><AlertCircleIcon size={16} /></span>
                    <span>Dead Letter Queue</span>
                  </Link>
                  <Link 
                    to="/admin/feedback" 
                    className={`sidebar-subitem ${isActive('/admin/feedback') ? 'active' : ''}`}
                  >
                    <span className="sidebar-icon"><FeedbackIcon size={16} /></span>
                    <span>Feedback</span>
                  </Link>
                </div>
              )}
            </div>
          )}

          {/* Submit Feedback - Above User Guide */}
          <Link 
            to="/feedback" 
            className={`sidebar-item ${isActive('/feedback') ? 'active' : ''}`}
            title="Submit Feedback"
          >
            <span className="sidebar-icon"><FeedbackIcon /></span>
            {isOpen && <span className="sidebar-label">Submit Feedback</span>}
          </Link>

          {/* User Guide - Always visible at the bottom */}
          <Link 
            to="/guide" 
            className={`sidebar-item ${isActive('/guide') ? 'active' : ''}`}
            title="User Guide"
          >
            <span className="sidebar-icon"><BookIcon /></span>
            {isOpen && <span className="sidebar-label">User Guide</span>}
          </Link>
        </nav>

        {/* Status indicator at bottom */}
        <div className="sidebar-footer">
          {isOpen ? (
            <div className="status-badge">
              <span className={getStatusClass()}></span>
              <span className="status-text">
                {backendStatus === 'connected' ? 'Connected' : 
                 backendStatus === 'disconnected' ? 'Disconnected' : 'Checking...'}
              </span>
            </div>
          ) : (
            <div className="status-badge-collapsed">
              <span className={getStatusClass()}></span>
            </div>
          )}
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
