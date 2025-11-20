import React, { useState, useEffect } from 'react';
import { createUser, getAllUsers, deleteUser } from '../services/api';
import './Admin.css';
import { PlusIcon, TrashIcon, ProfileIcon, CheckIcon } from '../components/icons';

const AdminUsers = ({ onUserChange, currentUser }) => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserName, setNewUserName] = useState('');

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

  const handleCreateUser = async (e) => {
    e.preventDefault();
    if (!newUserEmail || !newUserName) return;
    try {
      const newUser = await createUser(newUserEmail, newUserName);
      setUsers([newUser, ...users]);
      setNewUserEmail('');
      setNewUserName('');
      setError(null);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create user');
    }
  };

  const handleDeleteUser = async (userId) => {
    if (!window.confirm('Delete this user?')) return;
    try {
      await deleteUser(userId);
      setUsers(users.filter(u => u.id !== userId));
      if (currentUser?.id === userId) onUserChange(null);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete user');
    }
  };

  const handleSelectUser = (user) => onUserChange(user);

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Users</h1>
        <p>Manage application users</p>
      </div>
      {error && <div className="admin-error">{error}</div>}
      {loading && <div className="spinner" />}
      {!loading && (
        <div className="admin-content">
          <div className="admin-section">
            <h2><PlusIcon size={18} /> Create New User</h2>
            <form className="user-form" onSubmit={handleCreateUser}>
              <div className="form-row">
                <div className="form-group">
                  <label>Email</label>
                  <input type="email" className="input" value={newUserEmail} onChange={e => setNewUserEmail(e.target.value)} required />
                </div>
                <div className="form-group">
                  <label>Display Name</label>
                  <input type="text" className="input" value={newUserName} onChange={e => setNewUserName(e.target.value)} required />
                </div>
              </div>
              <button type="submit" className="btn btn-primary"><PlusIcon size={16} /> Create User</button>
            </form>
          </div>
          <div className="admin-section">
            <h2><ProfileIcon size={18} /> Existing Users ({users.length})</h2>
            <div className="users-list">
              {users.map(user => (
                <div key={user.id} className={`user-card ${currentUser?.id === user.id ? 'selected' : ''}`}>
                  <div className="user-info">
                    <div className="user-avatar" aria-label="user avatar"><ProfileIcon size={28} /></div>
                    <div className="user-details">
                      <div className="user-name">{user.display_name}</div>
                      <div className="user-email">{user.email}</div>
                      <div className="user-meta">Created: {new Date(user.created_at).toLocaleDateString()}</div>
                    </div>
                  </div>
                  <div className="user-actions">
                    {currentUser?.id !== user.id ? (
                      <button className="btn btn-secondary" onClick={() => handleSelectUser(user)}>Select</button>
                    ) : (
                      <span className="badge"><CheckIcon size={12} /> Active</span>
                    )}
                    <button className="btn btn-danger" onClick={() => handleDeleteUser(user.id)}><TrashIcon size={14} /> Delete</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminUsers;