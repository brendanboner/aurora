import React, { useState, useEffect } from 'react';
import {
  createUser,
  getAllUsers,
  deleteUser,
  getTopics,
  getOrganisations,
  getPeople,
  getGraphStatistics,
} from '../services/api';
import './Admin.css';

const Admin = ({ onUserChange, currentUser }) => {
  const [activeTab, setActiveTab] = useState('users');
  const [users, setUsers] = useState([]);
  const [topics, setTopics] = useState([]);
  const [organisations, setOrganisations] = useState([]);
  const [people, setPeople] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // User creation form
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserName, setNewUserName] = useState('');

  // Search filters
  const [topicSearch, setTopicSearch] = useState('');
  const [orgSearch, setOrgSearch] = useState('');
  const [peopleSearch, setPeopleSearch] = useState('');

  useEffect(() => {
    loadData();
  }, [activeTab]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      if (activeTab === 'users') {
        const usersData = await getAllUsers();
        setUsers(usersData);
      } else if (activeTab === 'knowledge') {
        const [topicsData, orgsData, peopleData, statsData] = await Promise.all([
          getTopics(),
          getOrganisations(),
          getPeople(),
          getGraphStatistics(),
        ]);
        setTopics(topicsData.topics || []);
        setOrganisations(orgsData.organisations || []);
        setPeople(peopleData.people || []);
        setStatistics(statsData);
      }
    } catch (err) {
      console.error('Error loading data:', err);
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
    if (!window.confirm('Are you sure you want to delete this user?')) return;

    try {
      await deleteUser(userId);
      setUsers(users.filter((u) => u.id !== userId));
      if (currentUser && currentUser.id === userId) {
        onUserChange(null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to delete user');
    }
  };

  const handleSelectUser = (user) => {
    onUserChange(user);
  };

  const filteredTopics = topics.filter((t) =>
    t.name?.toLowerCase().includes(topicSearch.toLowerCase())
  );

  const filteredOrgs = organisations.filter((o) =>
    o.name?.toLowerCase().includes(orgSearch.toLowerCase())
  );

  const filteredPeople = people.filter((p) =>
    p.name?.toLowerCase().includes(peopleSearch.toLowerCase())
  );

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Administration</h1>
        <p>Manage users and browse the knowledge graph</p>
      </div>

      <div className="admin-tabs">
        <button
          className={`tab ${activeTab === 'users' ? 'active' : ''}`}
          onClick={() => setActiveTab('users')}
        >
          👥 Users
        </button>
        <button
          className={`tab ${activeTab === 'knowledge' ? 'active' : ''}`}
          onClick={() => setActiveTab('knowledge')}
        >
          📚 Knowledge Graph
        </button>
      </div>

      {error && <div className="admin-error">⚠️ {error}</div>}

      {loading && <div className="spinner"></div>}

      {!loading && activeTab === 'users' && (
        <div className="admin-content">
          <div className="admin-section">
            <h2>Create New User</h2>
            <form className="user-form" onSubmit={handleCreateUser}>
              <div className="form-row">
                <div className="form-group">
                  <label>Email</label>
                  <input
                    type="email"
                    className="input"
                    value={newUserEmail}
                    onChange={(e) => setNewUserEmail(e.target.value)}
                    placeholder="user@example.com"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Display Name</label>
                  <input
                    type="text"
                    className="input"
                    value={newUserName}
                    onChange={(e) => setNewUserName(e.target.value)}
                    placeholder="John Doe"
                    required
                  />
                </div>
              </div>
              <button type="submit" className="btn btn-primary">
                ➕ Create User
              </button>
            </form>
          </div>

          <div className="admin-section">
            <h2>Existing Users ({users.length})</h2>
            <div className="users-list">
              {users.map((user) => (
                <div
                  key={user.id}
                  className={`user-card ${currentUser?.id === user.id ? 'selected' : ''}`}
                >
                  <div className="user-info">
                    <div className="user-avatar">👤</div>
                    <div className="user-details">
                      <div className="user-name">{user.display_name}</div>
                      <div className="user-email">{user.email}</div>
                      <div className="user-meta">
                        Created: {new Date(user.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  </div>
                  <div className="user-actions">
                    {currentUser?.id !== user.id ? (
                      <button
                        className="btn btn-secondary"
                        onClick={() => handleSelectUser(user)}
                      >
                        Select
                      </button>
                    ) : (
                      <span className="badge">Active</span>
                    )}
                    <button
                      className="btn btn-danger"
                      onClick={() => handleDeleteUser(user.id)}
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!loading && activeTab === 'knowledge' && (
        <div className="admin-content">
          {statistics && (
            <div className="statistics-grid">
              <div className="stat-card">
                <div className="stat-icon">📄</div>
                <div className="stat-value">{statistics.resources}</div>
                <div className="stat-label">Resources</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon">📚</div>
                <div className="stat-value">{statistics.topics}</div>
                <div className="stat-label">Topics</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon">🏢</div>
                <div className="stat-value">{statistics.organisations}</div>
                <div className="stat-label">Organisations</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon">👤</div>
                <div className="stat-value">{statistics.people}</div>
                <div className="stat-label">People</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon">🔗</div>
                <div className="stat-value">{statistics.datasources}</div>
                <div className="stat-label">Data Sources</div>
              </div>
            </div>
          )}

          <div className="knowledge-sections">
            <div className="knowledge-section">
              <h2>Topics ({filteredTopics.length})</h2>
              <input
                type="text"
                className="input search-input"
                placeholder="Search topics..."
                value={topicSearch}
                onChange={(e) => setTopicSearch(e.target.value)}
              />
              <div className="items-list">
                {filteredTopics.slice(0, 50).map((topic) => (
                  <div key={topic.id} className="item-card">
                    <div className="item-name">{topic.name}</div>
                    {topic.classification && (
                      <div className="item-meta">Type: {topic.classification}</div>
                    )}
                    {topic.aliases && topic.aliases.length > 0 && (
                      <div className="item-aliases">
                        {topic.aliases.slice(0, 3).map((alias, i) => (
                          <span key={i} className="badge">
                            {alias}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="knowledge-section">
              <h2>Organisations ({filteredOrgs.length})</h2>
              <input
                type="text"
                className="input search-input"
                placeholder="Search organisations..."
                value={orgSearch}
                onChange={(e) => setOrgSearch(e.target.value)}
              />
              <div className="items-list">
                {filteredOrgs.slice(0, 50).map((org) => (
                  <div key={org.id} className="item-card">
                    <div className="item-name">{org.name}</div>
                    {org.org_type && (
                      <div className="item-meta">Type: {org.org_type}</div>
                    )}
                    {org.aliases && org.aliases.length > 0 && (
                      <div className="item-aliases">
                        {org.aliases.slice(0, 3).map((alias, i) => (
                          <span key={i} className="badge">
                            {alias}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="knowledge-section">
              <h2>People ({filteredPeople.length})</h2>
              <input
                type="text"
                className="input search-input"
                placeholder="Search people..."
                value={peopleSearch}
                onChange={(e) => setPeopleSearch(e.target.value)}
              />
              <div className="items-list">
                {filteredPeople.slice(0, 50).map((person) => (
                  <div key={person.id} className="item-card">
                    <div className="item-name">{person.name}</div>
                    {person.email && (
                      <div className="item-meta">📧 {person.email}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Admin;
