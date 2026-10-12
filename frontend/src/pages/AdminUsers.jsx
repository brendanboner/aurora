import React, { useState, useEffect } from 'react';
import { getAllUsers, deleteUser, syncUserToGraph } from '../services/api';
import './Admin.css';
import { TrashIcon, ProfileIcon } from '../components/icons';

const AdminUsers = () => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [syncingUsers, setSyncingUsers] = useState(new Set());

  useEffect(() => { loadUsers(); }, []);

  const loadUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAllUsers();
      setUsers(data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (userId) => {
    if (!window.confirm('Delete this user?')) return;
    try {
      await deleteUser(userId);
      setUsers(users.filter(u => u.id !== userId));
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete user');
    }
  };

  const handleSyncUser = async (userId) => {
    setSyncingUsers(prev => new Set(prev).add(userId));
    setError(null);
    try {
      await syncUserToGraph(userId);
      // Reload users to get updated sync status
      await loadUsers();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to sync user to graph');
    } finally {
      setSyncingUsers(prev => {
        const newSet = new Set(prev);
        newSet.delete(userId);
        return newSet;
      });
    }
  };

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Users</h1>
        <p>View and manage application users</p>
      </div>
      {error && <div className="admin-error">{error}</div>}
      {loading && <div className="spinner" />}
      {!loading && (
        <div className="admin-content">
          <div className="admin-section">
            <h2><ProfileIcon size={18} /> Application Users ({users.length})</h2>
            <p className="section-note">
              Users are authenticated through AWS Cognito. 
              This view shows users who have accessed the application.
            </p>
            <div className="users-list">
              {users.length === 0 ? (
                <div className="empty-state">
                  <p>No users have accessed the application yet.</p>
                </div>
              ) : (
                users.map(user => (
                  <div key={user.id} className="user-card">
                    <div className="user-info">
                      <div className="user-avatar" aria-label="user avatar"><ProfileIcon size={28} /></div>
                      <div className="user-details">
                        <div className="user-name">{user.display_name || user.email}</div>
                        <div className="user-email">{user.email}</div>
                        <div className="user-meta">
                          Created: {new Date(user.created_at).toLocaleDateString()}
                          <span className={`sync-status ${user.synced_to_graph ? 'synced' : 'not-synced'}`}>
                            {user.synced_to_graph ? '● Synced to Graph' : '○ Not in Graph'}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="user-actions">
                      {!user.synced_to_graph && (
                        <button 
                          className="btn btn-primary" 
                          onClick={() => handleSyncUser(user.id)}
                          disabled={syncingUsers.has(user.id)}
                        >
                          {syncingUsers.has(user.id) ? 'Syncing...' : 'Sync to Graph'}
                        </button>
                      )}
                      <button className="btn btn-danger" onClick={() => handleDeleteUser(user.id)}>
                        <TrashIcon size={14} /> Delete
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminUsers;