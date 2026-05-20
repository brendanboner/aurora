import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './Sidebar.css';
import A1LogoMark from './A1LogoMark';
import {
  ChatIcon,
  ProfileIcon,
  UsersIcon,
  KnowledgeGraphIcon,
  MonitoringIcon,
  AdminIcon,
  CalendarIcon,
  StarIcon,
  SearchIcon,
  TargetIcon,
  SettingsIcon,
  BookIcon,
  FeedbackIcon,
  AlertCircleIcon,
  ToolIcon,
  FileTextIcon,
  ChevronDownIcon,
} from '../components/icons';
import { useAuth } from '../contexts/AuthContext';

const MAIN_ITEMS = [
  { to: '/', label: 'Chat', icon: ChatIcon, exact: true },
  { to: '/documents', label: 'Document Search', icon: SearchIcon },
  { to: '/feed', label: 'Creator Feed', icon: StarIcon },
  { to: '/events', label: 'Events', icon: CalendarIcon, startsWith: true },
  { to: '/my-documents', label: 'My Documents', icon: FileTextIcon },
];

const PROFILE_ITEMS = [
  { to: '/profile/preferences', label: 'Preferences', icon: SettingsIcon, startsWith: true },
  { to: '/profile/agents', label: 'Follow Agents', icon: StarIcon },
  { to: '/profile/my-agents', label: 'My Agents', icon: StarIcon },
];

const ADMIN_ITEMS = [
  { to: '/admin/users', label: 'Users', icon: UsersIcon },
  { to: '/admin/knowledge-graph', label: 'Knowledge Graph', icon: KnowledgeGraphIcon },
  { to: '/admin/monitoring', label: 'Monitoring', icon: MonitoringIcon },
  { to: '/admin/agents', label: 'Creator Agents', icon: StarIcon },
  { to: '/admin/system-config', label: 'System Config', icon: SettingsIcon },
  { to: '/admin/chat-sessions', label: 'Chat Sessions', icon: ChatIcon },
  { to: '/admin/feedback', label: 'Feedback', icon: FeedbackIcon },
];

const ADMIN_ADVANCED_ITEMS = [
  { to: '/admin/content-quality', label: 'Content Quality', icon: TargetIcon },
  { to: '/admin/oracle-settings', label: 'Oracle Settings', icon: SettingsIcon },
  { to: '/admin/dlq', label: 'Dead Letter Queue', icon: AlertCircleIcon },
  { to: '/admin/curation', label: 'Topic Curation', icon: ToolIcon },
];

const UTILITY_ITEMS = [
  { to: '/feedback', label: 'Submit Feedback', icon: FeedbackIcon },
  { to: '/guide', label: 'User Guide', icon: BookIcon },
];

const Sidebar = ({ isOpen, onClose, backendStatus }) => {
  const location = useLocation();
  const { user } = useAuth();
  const [expandedGroups, setExpandedGroups] = useState({
    profile: true,
    admin: false,
    advanced: false,
  });

  const isAdmin = user && (user.role === 'admin' || user.role === 'superadmin');

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  const isActive = (item) => {
    if (item.startsWith) {
      return location.pathname.startsWith(item.to);
    }
    return location.pathname === item.to;
  };

  const getStatusClass = () => `status-indicator status-${backendStatus}`;

  const getStatusText = () => {
    if (backendStatus === 'connected') return 'Connected';
    if (backendStatus === 'disconnected') return 'Disconnected';
    return 'Checking...';
  };

  const toggleGroup = (groupName) => {
    setExpandedGroups((prev) => ({
      ...prev,
      [groupName]: !prev[groupName],
    }));
  };

  const renderItems = (items, nested = false) =>
    items.map((item) => {
      const Icon = item.icon;
      return (
        <Link
          key={item.to}
          to={item.to}
          className={`drawer-item ${nested ? 'nested' : ''} ${isActive(item) ? 'active' : ''}`}
          onClick={onClose}
        >
          <span className="drawer-item-icon"><Icon size={18} /></span>
          <span className="drawer-item-label">{item.label}</span>
        </Link>
      );
    });

  return (
    <>
      <div className={`sidebar-overlay ${isOpen ? 'open' : ''}`} onClick={onClose} />

      <aside className={`sidebar-drawer ${isOpen ? 'open' : ''}`} aria-hidden={!isOpen}>
        <div className="drawer-header">
          <div className="drawer-brand">
            <A1LogoMark size={30} />
            <div className="drawer-brand-text">
              <span className="drawer-brand-name">Aurora</span>
              <span className="drawer-brand-sub">by Agent One</span>
            </div>
          </div>
        </div>

        <nav className="drawer-nav">
          <div className="drawer-section">{renderItems(MAIN_ITEMS)}</div>

          <div className="drawer-divider" />

          <div className="drawer-section">
            <button
              type="button"
              className={`drawer-item drawer-group-toggle ${expandedGroups.profile ? 'expanded' : ''}`}
              onClick={() => toggleGroup('profile')}
            >
              <span className="drawer-item-icon"><ProfileIcon size={18} /></span>
              <span className="drawer-item-label">My Profile</span>
              <span className="drawer-group-chevron">
                <ChevronDownIcon style={{ width: 14, height: 14 }} />
              </span>
            </button>

            {expandedGroups.profile && (
              <div className="drawer-submenu">
                {renderItems(PROFILE_ITEMS, true)}
              </div>
            )}
          </div>

          {isAdmin && (
            <div className="drawer-section">
              <button
                type="button"
                className={`drawer-item drawer-group-toggle ${expandedGroups.admin ? 'expanded' : ''}`}
                onClick={() => toggleGroup('admin')}
              >
                <span className="drawer-item-icon"><AdminIcon size={18} /></span>
                <span className="drawer-item-label">Admin</span>
                <span className="drawer-group-chevron">
                  <ChevronDownIcon style={{ width: 14, height: 14 }} />
                </span>
              </button>

              {expandedGroups.admin && (
                <div className="drawer-submenu">
                  {renderItems(ADMIN_ITEMS, true)}
                  {/* Advanced submenu nested inside Admin */}
                  <button
                    type="button"
                    className={`drawer-item nested drawer-group-toggle ${expandedGroups.advanced ? 'expanded' : ''}`}
                    onClick={() => toggleGroup('advanced')}
                    style={{ paddingLeft: '2rem' }}
                  >
                    <span className="drawer-item-icon"><ToolIcon size={16} /></span>
                    <span className="drawer-item-label">Advanced</span>
                    <span className="drawer-group-chevron">
                      <ChevronDownIcon style={{ width: 12, height: 12 }} />
                    </span>
                  </button>
                  {expandedGroups.advanced && (
                    <div className="drawer-submenu" style={{ paddingLeft: '0.75rem' }}>
                      {renderItems(ADMIN_ADVANCED_ITEMS, true)}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="drawer-divider" />

          <div className="drawer-section">{renderItems(UTILITY_ITEMS)}</div>
        </nav>

        <div className="drawer-footer">
          <span className={getStatusClass()}></span>
          <span className="drawer-footer-text">{getStatusText()}</span>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
