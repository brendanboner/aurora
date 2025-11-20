import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { ProfileIcon, BookIcon, BuildingIcon, BellIcon, CheckIcon, HourglassIcon, SaveIcon, ResetIcon, WarningIcon } from '../components/icons';
import {
  getUserPreferences,
  updateUserPreferences,
  getTopics,
  getOrganisations,
  getPeople,
} from '../services/api';
import './UserProfile.css';

const UserProfile = ({ currentUser, onUserChange }) => {
  const [preferences, setPreferences] = useState({
    topics: [],
    organisations: [],
    people: [],
    sources: [],
    notify_email: true,
    notify_digest: true,
  });
  const [availableTopics, setAvailableTopics] = useState([]);
  const [availableOrgs, setAvailableOrgs] = useState([]);
  const [availablePeople, setAvailablePeople] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState('');

  // Search states
  const [topicSearch, setTopicSearch] = useState('');
  const [orgSearch, setOrgSearch] = useState('');
  const [peopleSearch, setPeopleSearch] = useState('');

  const location = useLocation();
  const path = location.pathname;
  const selectedSection = path.includes('/profile/topics') ? 'topics'
    : path.includes('/profile/organisations') ? 'organisations'
    : path.includes('/profile/people') ? 'people'
    : path.includes('/profile/notifications') ? 'notifications'
    : null;

  useEffect(() => {
    loadData();
  }, [currentUser]);

  const loadData = async () => {
    if (!currentUser) return;

    setLoading(true);
    setError(null);
    try {
      const [prefs, topicsData, orgsData, peopleData] = await Promise.all([
        getUserPreferences(currentUser.id),
        getTopics(),
        getOrganisations(),
        getPeople(),
      ]);

      setPreferences(prefs);
      setAvailableTopics(topicsData.topics || []);
      setAvailableOrgs(orgsData.organisations || []);
      setAvailablePeople(peopleData.people || []);
    } catch (err) {
      console.error('Error loading profile data:', err);
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSavePreferences = async () => {
    if (!currentUser) return;

    setSaving(true);
    setError(null);
    setSuccessMessage('');
    try {
      const updated = await updateUserPreferences(currentUser.id, preferences);
      setPreferences(updated);
      setSuccessMessage('Preferences saved successfully!');
      setTimeout(() => setSuccessMessage(''), 3000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save preferences');
    } finally {
      setSaving(false);
    }
  };

  const togglePreference = (type, id) => {
    setPreferences((prev) => {
      const current = prev[type] || [];
      const isSelected = current.includes(id);
      return {
        ...prev,
        [type]: isSelected
          ? current.filter((item) => item !== id)
          : [...current, id],
      };
    });
  };

  const filteredTopics = availableTopics.filter((t) =>
    t.name?.toLowerCase().includes(topicSearch.toLowerCase())
  );

  const filteredOrgs = availableOrgs.filter((o) =>
    o.name?.toLowerCase().includes(orgSearch.toLowerCase())
  );

  const filteredPeople = availablePeople.filter((p) =>
    p.name?.toLowerCase().includes(peopleSearch.toLowerCase())
  );

  if (!currentUser) {
    return (
      <div className="profile-container">
        <div className="profile-empty">
          <div className="empty-icon"><ProfileIcon size={48} /></div>
          <h2>No User Selected</h2>
          <p>Please create or select a user in the Admin page to manage preferences.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="profile-container">
      <div className="profile-header">
        <div className="profile-avatar"><ProfileIcon size={48} /></div>
        <div className="profile-info">
          <h1>{currentUser.display_name || currentUser.email}</h1>
          <p className="profile-email">{currentUser.email}</p>
        </div>
      </div>

      {error && <div className="profile-error"><WarningIcon size={16} /> {error}</div>}
      {successMessage && <div className="profile-success"><CheckIcon size={16} /> {successMessage}</div>}

      {loading ? (
        <div className="spinner"></div>
      ) : (
        <>
          {(selectedSection === 'topics' || !selectedSection) && (
          <div className="profile-section">
            <h2><span className="icon-heading"><BookIcon size={20} /></span> Topics Preferences</h2>
            <p className="section-description">
              Select topics you're interested in. These will be used to filter content in your queries.
            </p>
            <input
              type="text"
              className="input search-input"
              placeholder="Search topics..."
              value={topicSearch}
              onChange={(e) => setTopicSearch(e.target.value)}
            />
            <div className="preferences-grid">
              {filteredTopics.slice(0, 100).map((topic) => (
                <div
                  key={topic.id}
                  className={`preference-item ${
                    preferences.topics?.includes(topic.id) ? 'selected' : ''
                  }`}
                  onClick={() => togglePreference('topics', topic.id)}
                >
                  <div className="preference-name">{topic.name}</div>
                  {topic.classification && (
                    <div className="preference-meta">{topic.classification}</div>
                  )}
                  {preferences.topics?.includes(topic.id) && (
                    <div className="preference-check"><CheckIcon size={14} /></div>
                  )}
                </div>
              ))}
            </div>
            {preferences.topics && preferences.topics.length > 0 && (
              <div className="selected-count">
                {preferences.topics.length} topic(s) selected
              </div>
            )}
          </div>)}

          {(selectedSection === 'organisations' || !selectedSection) && (
          <div className="profile-section">
            <h2><span className="icon-heading"><BuildingIcon size={20} /></span> Organisation Preferences</h2>
            <p className="section-description">
              Select organisations you want to follow.
            </p>
            <input
              type="text"
              className="input search-input"
              placeholder="Search organisations..."
              value={orgSearch}
              onChange={(e) => setOrgSearch(e.target.value)}
            />
            <div className="preferences-grid">
              {filteredOrgs.slice(0, 100).map((org) => (
                <div
                  key={org.id}
                  className={`preference-item ${
                    preferences.organisations?.includes(org.id) ? 'selected' : ''
                  }`}
                  onClick={() => togglePreference('organisations', org.id)}
                >
                  <div className="preference-name">{org.name}</div>
                  {org.org_type && (
                    <div className="preference-meta">{org.org_type}</div>
                  )}
                  {preferences.organisations?.includes(org.id) && (
                    <div className="preference-check"><CheckIcon size={14} /></div>
                  )}
                </div>
              ))}
            </div>
            {preferences.organisations && preferences.organisations.length > 0 && (
              <div className="selected-count">
                {preferences.organisations.length} organisation(s) selected
              </div>
            )}
          </div>)}

          {(selectedSection === 'people' || !selectedSection) && (
          <div className="profile-section">
            <h2><span className="icon-heading"><ProfileIcon size={20} /></span> People Preferences</h2>
            <p className="section-description">
              Select people you want to track.
            </p>
            <input
              type="text"
              className="input search-input"
              placeholder="Search people..."
              value={peopleSearch}
              onChange={(e) => setPeopleSearch(e.target.value)}
            />
            <div className="preferences-grid">
              {filteredPeople.slice(0, 100).map((person) => (
                <div
                  key={person.id}
                  className={`preference-item ${
                    preferences.people?.includes(person.id) ? 'selected' : ''
                  }`}
                  onClick={() => togglePreference('people', person.id)}
                >
                  <div className="preference-name">{person.name}</div>
                  {person.email && (
                    <div className="preference-meta">{person.email}</div>
                  )}
                  {preferences.people?.includes(person.id) && (
                    <div className="preference-check"><CheckIcon size={14} /></div>
                  )}
                </div>
              ))}
            </div>
            {preferences.people && preferences.people.length > 0 && (
              <div className="selected-count">
                {preferences.people.length} people selected
              </div>
            )}
          </div>)}

          {(selectedSection === 'notifications' || !selectedSection) && (
          <div className="profile-section">
            <h2><span className="icon-heading"><BellIcon size={20} /></span> Notification Settings</h2>
            <div className="notification-settings">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={preferences.notify_email}
                  onChange={(e) =>
                    setPreferences({ ...preferences, notify_email: e.target.checked })
                  }
                />
                <span>Email notifications</span>
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={preferences.notify_digest}
                  onChange={(e) =>
                    setPreferences({ ...preferences, notify_digest: e.target.checked })
                  }
                />
                <span>Daily digest</span>
              </label>
            </div>
          </div>)}

          <div className="profile-actions">
            <button
              className="btn btn-primary"
              onClick={handleSavePreferences}
              disabled={saving}
            >
              {saving ? (<><HourglassIcon size={16} /> Saving...</>) : (<><SaveIcon size={16} /> Save Preferences</>)}
            </button>
            <button className="btn btn-secondary" onClick={loadData} disabled={saving}>
              <ResetIcon size={16} /> Reset
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default UserProfile;
