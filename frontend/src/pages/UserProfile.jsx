import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { ProfileIcon, BookIcon, BuildingIcon, BellIcon, CheckIcon, ResetIcon, WarningIcon } from '../components/icons';
import { getUserPreferences, updateUserPreferences, getTopics, getOrganisations, getPeople } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import './UserProfile.css';

const UserProfile = () => {
  const { user } = useAuth();
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

  // Filter selections
  const [topicClassificationFilter, setTopicClassificationFilter] = useState([]);
  const [orgTypeFilter, setOrgTypeFilter] = useState([]);

  // Filter dropdown visibility
  const [showTopicFilterDropdown, setShowTopicFilterDropdown] = useState(false);
  const [showOrgFilterDropdown, setShowOrgFilterDropdown] = useState(false);

  const location = useLocation();
  const path = location.pathname;
  const selectedSection = path.includes('/profile/topics') ? 'topics'
    : path.includes('/profile/organisations') ? 'organisations'
    : path.includes('/profile/people') ? 'people'
    : path.includes('/profile/notifications') ? 'notifications'
    : null;

  useEffect(() => { loadData(); }, [user]);

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (!event.target.closest('.filter-dropdown-wrapper')) {
        setShowTopicFilterDropdown(false);
        setShowOrgFilterDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const loadData = async () => {
    if (!user) return;
    setLoading(true); setError(null);
    try {
      const [prefs, topicsData, orgsData, peopleData] = await Promise.all([
        getUserPreferences(user.user_id), getTopics(), getOrganisations(), getPeople()
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
    if (!user || !initialLoaded || !dirty) return;
    const changed = JSON.stringify(preferences) !== JSON.stringify(savedPreferences);
    if (!changed) { setDirty(false); return; }
    const timeout = setTimeout(async () => {
      setSaving(true);
      try {
        const updated = await updateUserPreferences(user.user_id, preferences);
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
  }, [preferences, user, initialLoaded, dirty, savedPreferences]);

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

  // Get unique classification values from topics
  const uniqueClassifications = [...new Set(availableTopics.map(t => t.classification).filter(Boolean))];
  const uniqueOrgTypes = [...new Set(availableOrgs.map(o => o.org_type).filter(Boolean))];

  // Apply filters
  const filteredTopics = availableTopics.filter(t => {
    const matchesSearch = t.name?.toLowerCase().includes(topicSearch.toLowerCase());
    const matchesClassification = topicClassificationFilter.length === 0 || topicClassificationFilter.includes(t.classification);
    return matchesSearch && matchesClassification;
  });

  const filteredOrgs = availableOrgs.filter(o => {
    const matchesSearch = o.name?.toLowerCase().includes(orgSearch.toLowerCase());
    const matchesType = orgTypeFilter.length === 0 || orgTypeFilter.includes(o.org_type);
    return matchesSearch && matchesType;
  });

  const filteredPeople = availablePeople.filter(p => p.name?.toLowerCase().includes(peopleSearch.toLowerCase()));

  if (!user) {
    return (
      <div className="profile-container">
        <div className="profile-empty">
          <div className="empty-icon"><ProfileIcon size={48} /></div>
          <h2>Please Log In</h2>
          <p>Please log in to manage your preferences.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="profile-container">
      <div className="profile-header">
        <div className="profile-avatar"><ProfileIcon size={48} /></div>
        <div className="profile-info">
          <h1>{user.email}</h1>
          <p className="profile-email">Role: {user.role || 'user'}</p>
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
              <div className="search-filter-container">
                <input className="input search-input" placeholder="Search topics..." value={topicSearch} onChange={e => setTopicSearch(e.target.value)} />
                <div className="filter-dropdown-wrapper">
                  <button 
                    className={`btn btn-secondary btn-sm filter-btn ${topicClassificationFilter.length > 0 ? 'active' : ''}`}
                    onClick={() => setShowTopicFilterDropdown(!showTopicFilterDropdown)}
                  >
                    Filter {topicClassificationFilter.length > 0 && `(${topicClassificationFilter.length})`}
                  </button>
                  {showTopicFilterDropdown && (
                    <div className="filter-dropdown">
                      <div className="filter-dropdown-header">
                        <strong>Classification</strong>
                        {topicClassificationFilter.length > 0 && (
                          <button className="btn-link" onClick={() => setTopicClassificationFilter([])}>Clear</button>
                        )}
                      </div>
                      {uniqueClassifications.map(classification => (
                        <label key={classification} className="filter-option">
                          <input
                            type="checkbox"
                            checked={topicClassificationFilter.includes(classification)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setTopicClassificationFilter([...topicClassificationFilter, classification]);
                              } else {
                                setTopicClassificationFilter(topicClassificationFilter.filter(c => c !== classification));
                              }
                            }}
                          />
                          <span>{classification}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>
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
              <div className="search-filter-container">
                <input className="input search-input" placeholder="Search organisations..." value={orgSearch} onChange={e => setOrgSearch(e.target.value)} />
                <div className="filter-dropdown-wrapper">
                  <button 
                    className={`btn btn-secondary btn-sm filter-btn ${orgTypeFilter.length > 0 ? 'active' : ''}`}
                    onClick={() => setShowOrgFilterDropdown(!showOrgFilterDropdown)}
                  >
                    Filter {orgTypeFilter.length > 0 && `(${orgTypeFilter.length})`}
                  </button>
                  {showOrgFilterDropdown && (
                    <div className="filter-dropdown">
                      <div className="filter-dropdown-header">
                        <strong>Organization Type</strong>
                        {orgTypeFilter.length > 0 && (
                          <button className="btn-link" onClick={() => setOrgTypeFilter([])}>Clear</button>
                        )}
                      </div>
                      {uniqueOrgTypes.map(orgType => (
                        <label key={orgType} className="filter-option">
                          <input
                            type="checkbox"
                            checked={orgTypeFilter.includes(orgType)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setOrgTypeFilter([...orgTypeFilter, orgType]);
                              } else {
                                setOrgTypeFilter(orgTypeFilter.filter(t => t !== orgType));
                              }
                            }}
                          />
                          <span>{orgType}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>
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
