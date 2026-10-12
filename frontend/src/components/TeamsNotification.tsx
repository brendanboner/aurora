/**
 * Teams-Style Notification Toast System
 * Displays alerts in top-right corner, auto-dismisses, supports actions
 */

import React, { useState, useEffect, useCallback } from 'react';
import './TeamsNotification.css';
import { ToastNotification } from '../services/eventBus';

interface ToastProps {
  notification: ToastNotification;
  onDismiss: (id: string) => void;
}

/**
 * Single toast notification component
 */
export const Toast: React.FC<ToastProps> = ({ notification, onDismiss }) => {
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    const duration = notification.duration || 4000;
    const timer = setTimeout(() => {
      setIsExiting(true);
      setTimeout(() => onDismiss(notification.id), 300); // Wait for animation
    }, duration);

    return () => clearTimeout(timer);
  }, [notification.id, notification.duration, onDismiss]);

  const handleDismiss = () => {
    setIsExiting(true);
    setTimeout(() => onDismiss(notification.id), 300);
  };

  const handleAction = () => {
    if (notification.action?.callback) {
      notification.action.callback();
    }
    handleDismiss();
  };

  const typeClass = `toast-${notification.type}`;
  const icon = getIcon(notification.type);

  return (
    <div className={`toast ${typeClass} ${isExiting ? 'toast-exit' : ''}`}>
      <div className="toast-icon">{icon}</div>
      <div className="toast-content">
        <div className="toast-title">{notification.title}</div>
        <div className="toast-message">{notification.message}</div>
      </div>
      {notification.action && (
        <button className="toast-action" onClick={handleAction}>
          {notification.action.label}
        </button>
      )}
      <button
        className="toast-close"
        onClick={handleDismiss}
        aria-label="Close notification"
      >
        ×
      </button>
    </div>
  );
};

function getIcon(type: string): string {
  switch (type) {
    case 'success':
      return '✓';
    case 'error':
      return '!';
    case 'warning':
      return '⚠';
    case 'info':
    default:
      return 'ℹ';
  }
}

/**
 * Toast container - manages multiple toasts
 */
interface ToastContainerProps {
  notifications: ToastNotification[];
  onDismiss: (id: string) => void;
}

export const ToastContainer: React.FC<ToastContainerProps> = ({
  notifications,
  onDismiss,
}) => {
  return (
    <div className="toast-container">
      {notifications.map((notification) => (
        <Toast
          key={notification.id}
          notification={notification}
          onDismiss={onDismiss}
        />
      ))}
    </div>
  );
};

/**
 * Hook to manage toast notifications
 */
export const useToasts = () => {
  const [notifications, setNotifications] = useState<ToastNotification[]>([]);

  const addNotification = useCallback((notification: ToastNotification) => {
    const id = notification.id || `toast-${Date.now()}`;
    setNotifications((prev) => [...prev, { ...notification, id }]);
  }, []);

  const removeNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((notif) => notif.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  return {
    notifications,
    addNotification,
    removeNotification,
    clearAll,
  };
};
