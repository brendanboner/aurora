import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { ProfileIcon, BookIcon, BuildingIcon, BellIcon, CheckIcon, ResetIcon, WarningIcon } from '../components/icons';
import { getUserPreferences, updateUserPreferences, getTopics, getOrganisations, getPeople } from '../services/api';
import './UserProfile.css';

const UserProfile = ({ currentUser }) => {
  const [preferences, setPreferences] = useState({
    topics: [], organisations: [], people: [], sources: [], notify_email: true, notify_digest: true,
  });
  const [savedPreferences, setSavedPreferences] = useState(null); // snapshot of last saved prefs
  const [dirty, setDirty] = useState(false); // track user-driven changes
  const [availableTopics, setAvailableTopics] = useState([]);
  const [availableOrgs, setAvailableOrgs] = useState([]);
  const [availablePeople, setAvailablePeople] = useState([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState('');
  const [initialLoaded, setInitialLoaded] = useState(false);

  // Search inputs
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

  useEffect(() => { loadData(); }, [currentUser]);

  const loadData = async () => {
    if (!currentUser) return;
    setLoading(true); setError(null);
    try {
      const [prefs, topicsData, orgsData, peopleData] = await Promise.all([
        getUserPreferences(currentUser.id), getTopics(), getOrganisations(), getPeople()
      ]);
      setPreferences(prefs);
      setSavedPreferences(prefs);
      setAvailableTopics(topicsData.topics || []);
      setAvailableOrgs(orgsData.organisations || []);
      setAvailablePeople(peopleData.people || []);
      setInitialLoaded(true);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally { setLoading(false); }
  };

  // Debounced auto-save only when dirty & actually changed
  useEffect(() => {
    if (!currentUser || !initialLoaded || !dirty) return;
    const changed = JSON.stringify(preferences) !== JSON.stringify(savedPreferences);
    if (!changed) { setDirty(false); return; }
    const timeout = setTimeout(async () => {
      setSaving(true);
      try {
        const updated = await updateUserPreferences(currentUser.id, preferences);
        setPreferences(updated);
        setSavedPreferences(updated);
        setDirty(false);
        setSuccessMessage('Preferences auto-saved');
        setTimeout(() => setSuccessMessage(''), 3000);
      } catch (err) {
        setError(err.response?.data?.detail || 'Failed to auto-save preferences');
      } finally { setSaving(false); }
    }, 600);
    return () => clearTimeout(timeout);
  }, [preferences, currentUser, initialLoaded, dirty, savedPreferences]);

  const togglePreference = (type, id) => {
    setPreferences(prev => {
      const current = prev[type] || [];
      const next = current.includes(id) ? current.filter(x => x !== id) : [...current, id];
      return { ...prev, [type]: next };
    });
    setDirty(true);
  };

  const bulkSet = (type, values, isSelectAll = false) => {
    setPreferences(prev => ({ ...prev, [type]: values }));
    setDirty(true);
    
    // Show feedback message
    if (isSelectAll) {
      const totalCount = type === 'topics' ? availableTopics.length 
        : type === 'organisations' ? availableOrgs.length 
        : availablePeople.length;
      setSuccessMessage(values.length > 0 
        ? `Selected all ${totalCount} ${type}` 
        : `Deselected all ${type}`);
      setTimeout(() => setSuccessMessage(''), 3000);
    }
  };

  const filteredTopics = availableTopics.filter(t => t.name?.toLowerCase().includes(topicSearch.toLowerCase()));
  const filteredOrgs = availableOrgs.filter(o => o.name?.toLowerCase().includes(orgSearch.toLowerCase()));
  const filteredPeople = availablePeople.filter(p => p.name?.toLowerCase().includes(peopleSearch.toLowerCase()));

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
      {/* Success & saving indicators moved to bottom; show only after real changes */}

      {loading ? (<div className="spinner" />) : (
        <>
          {(selectedSection === 'topics' || !selectedSection) && (
            <div className="profile-section">
              <h2><span className="icon-heading"><BookIcon size={20} /></span> Topics Preferences</h2>
              <p className="section-description">Select topics you're interested in.</p>
              <input className="input search-input" placeholder="Search topics..." value={topicSearch} onChange={e => setTopicSearch(e.target.value)} />
              <div className="bulk-actions">
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('topics', filteredTopics.map(t => t.id), true)} title={`Select all ${filteredTopics.length} visible topics`}>Select All ({filteredTopics.length})</button>
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('topics', preferences.topics.filter(id => !filteredTopics.map(t => t.id).includes(id)), true)} title="Deselect all visible topics">Select None</button>
                {topicSearch && filteredTopics.length < availableTopics.length && (
                  <span className="filter-info">{filteredTopics.length} of {availableTopics.length} shown</span>
                )}
              </div>
              <div className="preferences-grid">
                {filteredTopics.slice(0,100).map(topic => (
                  <div key={topic.id} className={`preference-item ${preferences.topics.includes(topic.id) ? 'selected':''}`} onClick={() => togglePreference('topics', topic.id)}>
                    <div className="preference-name">{topic.name}</div>
                    {topic.classification && <div className="preference-meta">{topic.classification}</div>}
                    {preferences.topics.includes(topic.id) && <div className="preference-check"><CheckIcon size={14} /></div>}
                  </div>
                ))}
              </div>
              {preferences.topics.length > 0 && <div className="selected-count">{preferences.topics.length} topic(s) selected</div>}
            </div>
          )}

          {(selectedSection === 'organisations' || !selectedSection) && (
            <div className="profile-section">
              <h2><span className="icon-heading"><BuildingIcon size={20} /></span> Organisation Preferences</h2>
              <p className="section-description">Select organisations you want to follow.</p>
              <input className="input search-input" placeholder="Search organisations..." value={orgSearch} onChange={e => setOrgSearch(e.target.value)} />
              <div className="bulk-actions">
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('organisations', filteredOrgs.map(o => o.id), true)} title={`Select all ${filteredOrgs.length} visible organisations`}>Select All ({filteredOrgs.length})</button>
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('organisations', preferences.organisations.filter(id => !filteredOrgs.map(o => o.id).includes(id)), true)} title="Deselect all visible organisations">Select None</button>
                {orgSearch && filteredOrgs.length < availableOrgs.length && (
                  <span className="filter-info">{filteredOrgs.length} of {availableOrgs.length} shown</span>
                )}
              </div>
              <div className="preferences-grid">
                {filteredOrgs.slice(0,100).map(org => (
                  <div key={org.id} className={`preference-item ${preferences.organisations.includes(org.id) ? 'selected':''}`} onClick={() => togglePreference('organisations', org.id)}>
                    <div className="preference-name">{org.name}</div>
                    {org.org_type && <div className="preference-meta">{org.org_type}</div>}
                    {preferences.organisations.includes(org.id) && <div className="preference-check"><CheckIcon size={14} /></div>}
                  </div>
                ))}
              </div>
              {preferences.organisations.length > 0 && <div className="selected-count">{preferences.organisations.length} organisation(s) selected</div>}
            </div>
          )}

          {(selectedSection === 'people' || !selectedSection) && (
            <div className="profile-section">
              <h2><span className="icon-heading"><ProfileIcon size={20} /></span> People Preferences</h2>
              <p className="section-description">Select people you want to track.</p>
              <input className="input search-input" placeholder="Search people..." value={peopleSearch} onChange={e => setPeopleSearch(e.target.value)} />
              <div className="bulk-actions">
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('people', filteredPeople.map(p => p.id), true)} title={`Select all ${filteredPeople.length} visible people`}>Select All ({filteredPeople.length})</button>
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('people', preferences.people.filter(id => !filteredPeople.map(p => p.id).includes(id)), true)} title="Deselect all visible people">Select None</button>
                {peopleSearch && filteredPeople.length < availablePeople.length && (
                  <span className="filter-info">{filteredPeople.length} of {availablePeople.length} shown</span>
                )}
              </div>
              <div className="preferences-grid">
                {filteredPeople.slice(0,100).map(person => (
                  <div key={person.id} className={`preference-item ${preferences.people.includes(person.id) ? 'selected':''}`} onClick={() => togglePreference('people', person.id)}>
                    <div className="preference-name">{person.name}</div>
                    {person.email && <div className="preference-meta">{person.email}</div>}
                    {preferences.people.includes(person.id) && <div className="preference-check"><CheckIcon size={14} /></div>}
                  </div>
                ))}
              </div>
              {preferences.people.length > 0 && <div className="selected-count">{preferences.people.length} people selected</div>}
            </div>
          )}

          {(selectedSection === 'notifications' || !selectedSection) && (
            <div className="profile-section">
              <h2><span className="icon-heading"><BellIcon size={20} /></span> Notification Settings</h2>
              <div className="notification-settings">
                <label className="checkbox-label">
                  <input type="checkbox" checked={preferences.notify_email} onChange={e => setPreferences({ ...preferences, notify_email: e.target.checked })} />
                  <span>Email notifications</span>
                </label>
                <label className="checkbox-label">
                  <input type="checkbox" checked={preferences.notify_digest} onChange={e => setPreferences({ ...preferences, notify_digest: e.target.checked })} />
                  <span>Daily digest</span>
                </label>
              </div>
            </div>
          )}

          <div className="profile-actions">
            <button className="btn btn-secondary" onClick={loadData} disabled={saving}> <ResetIcon size={16} /> Reset </button>
          </div>
          <div className="profile-footer-status">
            {saving && <div className="auto-save-indicator">Saving...</div>}
            {successMessage && !saving && <div className="profile-success"><CheckIcon size={16} /> {successMessage}</div>}
          </div>
        </>
      )}
    </div>
  );
};

export default UserProfile;
