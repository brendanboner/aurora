import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  ChatIcon,
  SearchIcon,
  StarIcon,
  CalendarIcon,
  FileTextIcon,
  SettingsIcon,
  AdminIcon,
} from './icons';
import { useAuth } from '../contexts/AuthContext';
import './IconRail.css';

const NAV_ITEMS = [
  { to: '/',           icon: ChatIcon,     label: 'Chat',            exact: true },
  { to: '/documents',  icon: SearchIcon,   label: 'Document Search' },
  { to: '/feed',       icon: StarIcon,     label: 'Creator Feed' },
  { to: '/events',     icon: CalendarIcon, label: 'Events',          startsWith: true },
  { to: '/my-documents', icon: FileTextIcon, label: 'My Documents' },
];

const IconRail = () => {
  const location = useLocation();
  const { user } = useAuth();

  const isActive = (item) => {
    if (item.exact) return location.pathname === item.to;
    if (item.startsWith) return location.pathname.startsWith(item.to);
    return location.pathname === item.to;
  };

  const isAdmin = user && (user.role === 'admin' || user.role === 'superadmin');

  return (
    <nav className="icon-rail" aria-label="Main navigation">
      <div className="icon-rail-nav">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              className={`icon-rail-item ${isActive(item) ? 'active' : ''}`}
              title={item.label}
              aria-label={item.label}
            >
              <Icon size={20} />
            </Link>
          );
        })}

        {isAdmin && (
          <Link
            to="/admin/users"
            className={`icon-rail-item ${location.pathname.startsWith('/admin') ? 'active' : ''}`}
            title="Admin"
            aria-label="Admin"
          >
            <AdminIcon size={20} />
          </Link>
        )}
      </div>

      <div className="icon-rail-bottom">
        <Link
          to="/profile/preferences"
          className={`icon-rail-item ${location.pathname.startsWith('/profile') ? 'active' : ''}`}
          title="Preferences"
          aria-label="Preferences"
        >
          <SettingsIcon size={20} />
        </Link>
      </div>
    </nav>
  );
};

export default IconRail;
