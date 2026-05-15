import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ProfileIcon, BookIcon, BuildingIcon, BellIcon, CheckIcon, ResetIcon, WarningIcon } from '../components/icons';
import { getUserPreferences, updateUserPreferences, getTopics, getOrganisations, getPeople, getTopicsHierarchy } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import TopicTree from '../components/TopicTree';
import PreferencesPanel from '../components/PreferencesPanel';
import './UserProfile.css';

const UserProfile = ({ initialSection, initialPreferencesTab }) => {
  const { user } = useAuth();
  const hierarchyLoadingRef = useRef(false);
  const loadDataRef = useRef(false);
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

  // Pagination state
  const [topicsPage, setTopicsPage] = useState(1);
  const [orgsPage, setOrgsPage] = useState(1);
  const [peoplePage, setPeoplePage] = useState(1);
  const [topicsTotalCount, setTopicsTotalCount] = useState(0);
  const [orgsTotalCount, setOrgsTotalCount] = useState(0);
  const [peopleTotalCount, setPeopleTotalCount] = useState(0);
  const pageSize = 100;

  // Search inputs
  const [topicSearch, setTopicSearch] = useState('');
  const [orgSearch, setOrgSearch] = useState('');
  const [peopleSearch, setPeopleSearch] = useState('');

  // Filter selections
  const [topicClassificationFilter, setTopicClassificationFilter] = useState([]);
  const [orgTypeFilter, setOrgTypeFilter] = useState([]);

  // Sort options
  const [topicSortBy, setTopicSortBy] = useState('popularity');
  const [orgSortBy, setOrgSortBy] = useState('popularity');
  const [peopleSortBy, setPeopleSortBy] = useState('popularity');

  // Filter dropdown visibility
  const [showTopicFilterDropdown, setShowTopicFilterDropdown] = useState(false);
  const [showOrgFilterDropdown, setShowOrgFilterDropdown] = useState(false);
  
  // Sort dropdown visibility
  const [showTopicSortDropdown, setShowTopicSortDropdown] = useState(false);
  const [showOrgSortDropdown, setShowOrgSortDropdown] = useState(false);
  const [showPeopleSortDropdown, setShowPeopleSortDropdown] = useState(false);

  // Topic view mode (hierarchical vs flat)
  const [topicViewMode, setTopicViewMode] = useState('flat');
  const [hierarchyData, setHierarchyData] = useState(null);
  const [hierarchyLoading, setHierarchyLoading] = useState(false);

  const location = useLocation();
  const navigate = useNavigate();
  const path = location.pathname;
  // Default to 'preferences' (Groups tab) so it's always the landing section
  const selectedSection = initialSection
    || (path.includes('/profile/preferences') || path.includes('/profile/memberships') ? 'preferences'
    : path.includes('/profile/topics') ? 'topics'
    : path.includes('/profile/organisations') ? 'organisations'
    : path.includes('/profile/people') ? 'people'
    : path.includes('/profile/notifications') ? 'notifications'
    : 'preferences');

  const PROFILE_NAV = [
    { id: 'preferences',  label: 'Groups & Sources', path: '/profile/preferences' },
    { id: 'topics',       label: 'Topics',            path: '/profile/topics' },
    { id: 'organisations',label: 'Companies',         path: '/profile/organisations' },
    { id: 'notifications',label: 'Notifications',     path: '/profile/notifications' },
  ];

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (!event.target.closest('.filter-dropdown-wrapper')) {
        setShowTopicFilterDropdown(false);
        setShowOrgFilterDropdown(false);
        setShowTopicSortDropdown(false);
        setShowOrgSortDropdown(false);
        setShowPeopleSortDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const loadTopicsPage = useCallback(async (page) => {
    const offset = (page - 1) * pageSize;
    const topicsData = await getTopics(pageSize, offset, topicSearch, topicSortBy);
    
    const normalizeTopics = (data) => {
      const topics = data?.topics || [];
      return topics.filter(t => t && typeof t === 'object').map(t => ({
        ...t,
        id: t.topic_id || t.id
      }));
    };
    
    setAvailableTopics(normalizeTopics(topicsData));
    setTopicsTotalCount(topicsData.total_count || 0);
    setTopicsPage(page);
  }, [pageSize, topicSearch, topicSortBy]);

  const loadHierarchyData = useCallback(async () => {
    if (hierarchyLoadingRef.current || hierarchyData) {
      return;
    }
    
    hierarchyLoadingRef.current = true;
    setHierarchyLoading(true);
    try {
      const data = await getTopicsHierarchy('');
      setHierarchyData(data);
    } catch (err) {
      console.error('Failed to load hierarchy:', err);
      setError('Failed to load topic hierarchy');
    } finally {
      setHierarchyLoading(false);
      hierarchyLoadingRef.current = false;
    }
  }, [hierarchyData]);

  const loadOrgsPage = useCallback(async (page) => {
    const offset = (page - 1) * pageSize;
    const orgsData = await getOrganisations(pageSize, offset, orgSortBy, orgSearch);
    
    const normalizeOrgs = (data) => {
      const orgs = data?.organisations || [];
      return orgs.filter(o => o && typeof o === 'object').map(o => ({
        ...o,
        id: o.org_id || o.id
      }));
    };
    
    setAvailableOrgs(normalizeOrgs(orgsData));
    setOrgsTotalCount(orgsData.total_count || 0);
    setOrgsPage(page);
  }, [pageSize, orgSortBy, orgSearch]);

  const loadPeoplePage = useCallback(async (page) => {
    const offset = (page - 1) * pageSize;
    const peopleData = await getPeople(pageSize, offset, peopleSortBy, peopleSearch);
    
    const normalizePeople = (data) => {
      const people = data?.people || [];
      return people.filter(p => p && typeof p === 'object').map(p => ({
        ...p,
        id: p.person_id || p.id
      }));
    };
    
    setAvailablePeople(normalizePeople(peopleData));
    setPeopleTotalCount(peopleData.total_count || 0);
    setPeoplePage(page);
  }, [pageSize, peopleSortBy, peopleSearch]);

  const loadData = useCallback(async () => {
    // Prevent duplicate calls during initial load (React StrictMode)
    if (!user || (loadDataRef.current && !initialLoaded)) return;
    
    loadDataRef.current = true;
    setLoading(true); setError(null);
    try {
      const prefs = await getUserPreferences(user.id);
      setPreferences(prefs);
      setSavedPreferences(prefs);
      
      // Load data based on active section (or all if viewing all sections)
      const loadPromises = [];
      
      if (!selectedSection || selectedSection === 'topics') {
        if (topicViewMode === 'hierarchical') {
          loadPromises.push(loadHierarchyData());
        } else {
          loadPromises.push(loadTopicsPage(1));
        }
      }
      
      if (!selectedSection || selectedSection === 'organisations') {
        loadPromises.push(loadOrgsPage(1));
      }
      
      if (!selectedSection || selectedSection === 'people') {
        loadPromises.push(loadPeoplePage(1));
      }
      
      await Promise.all(loadPromises);
      
      setInitialLoaded(true);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally { 
      setLoading(false);
      loadDataRef.current = false;
    }
  }, [initialLoaded, loadHierarchyData, loadOrgsPage, loadPeoplePage, loadTopicsPage, selectedSection, topicViewMode, user]);

  // Initial load when user is available
  useEffect(() => {
    if (user && !initialLoaded) {
      loadData();
    }
  }, [user, initialLoaded, loadData]);

  // Load data when navigating between sections
  useEffect(() => {
    if (!user || !initialLoaded) return;

    if (selectedSection === 'organisations' && availableOrgs.length === 0) {
      loadOrgsPage(1);
    } else if (selectedSection === 'people' && availablePeople.length === 0) {
      loadPeoplePage(1);
    } else if (selectedSection === 'topics' && availableTopics.length === 0 && topicViewMode === 'flat') {
      loadTopicsPage(1);
    } else if (selectedSection === 'topics' && !hierarchyData && topicViewMode === 'hierarchical') {
      loadHierarchyData();
    } else if (selectedSection === null) {
      const loadPromises = [];
      if (availableOrgs.length === 0) {
        loadPromises.push(loadOrgsPage(1));
      }
      if (availablePeople.length === 0) {
        loadPromises.push(loadPeoplePage(1));
      }
      if (availableTopics.length === 0 && topicViewMode === 'flat') {
        loadPromises.push(loadTopicsPage(1));
      }
      if (!hierarchyData && topicViewMode === 'hierarchical') {
        loadPromises.push(loadHierarchyData());
      }
      if (loadPromises.length > 0) {
        Promise.all(loadPromises);
      }
    }
  }, [availableOrgs.length, availablePeople.length, availableTopics.length, hierarchyData, initialLoaded, loadHierarchyData, loadOrgsPage, loadPeoplePage, loadTopicsPage, selectedSection, topicViewMode, user]);

  useEffect(() => {
    if (initialLoaded && user && topicViewMode === 'flat') {
      loadTopicsPage(1);
    }
  }, [initialLoaded, loadTopicsPage, topicSortBy, topicViewMode, user]);

  useEffect(() => {
    if (initialLoaded && user && (selectedSection === 'organisations' || !selectedSection)) {
      loadOrgsPage(1);
    }
  }, [initialLoaded, loadOrgsPage, orgSortBy, selectedSection, user]);

  useEffect(() => {
    if (initialLoaded && user && (selectedSection === 'people' || !selectedSection)) {
      loadPeoplePage(1);
    }
  }, [initialLoaded, loadPeoplePage, peopleSortBy, selectedSection, user]);

  useEffect(() => {
    if (!initialLoaded || !user || topicViewMode !== 'flat') return;
    const timeout = setTimeout(() => {
      loadTopicsPage(1);
    }, 300);
    return () => clearTimeout(timeout);
  }, [initialLoaded, loadTopicsPage, topicSearch, topicViewMode, user]);

  useEffect(() => {
    if (!initialLoaded || !user || (selectedSection !== 'organisations' && selectedSection !== null)) return;
    const timeout = setTimeout(() => {
      loadOrgsPage(1);
    }, 300);
    return () => clearTimeout(timeout);
  }, [initialLoaded, loadOrgsPage, orgSearch, selectedSection, user]);

  useEffect(() => {
    if (!initialLoaded || !user || (selectedSection !== 'people' && selectedSection !== null)) return;
    const timeout = setTimeout(() => {
      loadPeoplePage(1);
    }, 300);
    return () => clearTimeout(timeout);
  }, [initialLoaded, loadPeoplePage, peopleSearch, selectedSection, user]);

  // Debounced auto-save only when dirty & actually changed
  useEffect(() => {
    if (!user || !initialLoaded || !dirty) return;
    const changed = JSON.stringify(preferences) !== JSON.stringify(savedPreferences);
    if (!changed) { setDirty(false); return; }
    const timeout = setTimeout(async () => {
      setSaving(true);
      try {
        const updated = await updateUserPreferences(user.id, preferences);
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
    // Filter out any undefined, null, or invalid values
    const validValues = values.filter(v => v !== undefined && v !== null && v !== '');
    
    setPreferences(prev => ({ ...prev, [type]: validValues }));
    setDirty(true);
    
    // Show feedback message
    if (isSelectAll) {
      const totalCount = type === 'topics' ? availableTopics.length 
        : type === 'organisations' ? availableOrgs.length 
        : availablePeople.length;
      setSuccessMessage(validValues.length > 0 
        ? `Selected all ${totalCount} ${type}` 
        : `Deselected all ${type}`);
      setTimeout(() => setSuccessMessage(''), 3000);
    }
  };

  // Get unique classification values from topics
  const uniqueClassifications = [...new Set(availableTopics.map(t => t.classification).filter(Boolean))];
  const uniqueOrgTypes = [...new Set(availableOrgs.map(o => o.org_type).filter(Boolean))];

  // Apply client-side filters (classification and type filters only - search is server-side)
  const filteredTopics = availableTopics.filter(t => {
    const matchesClassification = topicClassificationFilter.length === 0 || topicClassificationFilter.includes(t.classification);
    return matchesClassification;
  });

  const filteredOrgs = availableOrgs.filter(o => {
    const matchesType = orgTypeFilter.length === 0 || orgTypeFilter.includes(o.org_type);
    return matchesType;
  });

  const filteredPeople = availablePeople; // No client-side filtering for people, all done server-side

  // Calculate total pages
  const topicsTotalPages = Math.ceil(topicsTotalCount / pageSize);
  const orgsTotalPages = Math.ceil(orgsTotalCount / pageSize);
  const peopleTotalPages = Math.ceil(peopleTotalCount / pageSize);

  // Render pagination controls
  const renderPagination = (currentPage, totalPages, onPageChange, label) => {
    if (totalPages <= 1) return null;

    return (
      <div className="pagination">
        <button 
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1 || loading}
          className="pagination-btn"
        >
          Previous
        </button>
        
        <div className="pagination-info">
          Page {currentPage} of {totalPages}
        </div>
        
        <button 
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages || loading}
          className="pagination-btn"
        >
          Next
        </button>
      </div>
    );
  };

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

      {/* Section navigation tabs */}
      <nav className="profile-section-nav" role="tablist">
        {PROFILE_NAV.map(item => (
          <button
            key={item.id}
            role="tab"
            aria-selected={selectedSection === item.id}
            className={`profile-nav-tab${selectedSection === item.id ? ' active' : ''}`}
            onClick={() => navigate(item.path)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {error && <div className="profile-error"><WarningIcon size={16} /> {error}</div>}
      {/* Success & saving indicators moved to bottom; show only after real changes */}

      {loading ? (<div className="spinner" />) : (
        <>
          {/* Unified preferences panel (Groups/Sources/Technology/Companies) */}
          {selectedSection === 'preferences' && user && (
            <div className="profile-section" style={{ padding: 0, overflow: 'hidden' }}>
              <PreferencesPanel
                userId={user.id}
                defaultTab={initialPreferencesTab || 'group'}
              />
            </div>
          )}

          {(selectedSection === 'topics' || !selectedSection) && (
            <div className="profile-section">
              <h2><span className="icon-heading"><BookIcon size={20} /></span> Topics Preferences</h2>
              <p className="section-description">Select topics you're interested in.</p>
              
              {/* Selected Topics Display */}
              {preferences.topics.length > 0 && (
                <div className="selected-items-display">
                  <div className="selected-items-header">
                    <strong>Selected Topics ({preferences.topics.length})</strong>
                    <button 
                      className="btn-link" 
                      onClick={() => bulkSet('topics', [], false)}
                      title="Clear all selected topics"
                    >
                      Clear All
                    </button>
                  </div>
                  <div className="selected-chips">
                    {preferences.topics.map(topicId => {
                      const topic = topicViewMode === 'hierarchical' && hierarchyData
                        ? hierarchyData.nodes[topicId]
                        : availableTopics.find(t => t.id === topicId);
                      const topicName = topic?.name || topicId;
                      return (
                        <span key={topicId} className="chip topic-chip">
                          {topicName}
                          <button 
                            onClick={() => togglePreference('topics', topicId)} 
                            className="chip-remove"
                            title={`Remove ${topicName}`}
                          >×</button>
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* View Toggle */}
              <div className="view-toggle">
                <button 
                  className={topicViewMode === 'flat' ? 'active' : ''}
                  onClick={() => {
                    setTopicViewMode('flat');
                    if (availableTopics.length === 0 && initialLoaded) {
                      loadTopicsPage(1);
                    }
                  }}
                >
                  List View
                </button>
                <button 
                  className={topicViewMode === 'hierarchical' ? 'active' : ''}
                  onClick={() => {
                    setTopicViewMode('hierarchical');
                    if (!hierarchyData) {
                      loadHierarchyData();
                    }
                  }}
                >
                  Tree View
                </button>
              </div>

              {topicViewMode === 'flat' ? (
                <>
                  <div className="search-filter-container">
                    <input className="input search-input" placeholder="Search topics..." value={topicSearch} onChange={e => setTopicSearch(e.target.value)} />
                    <div className="filter-dropdown-wrapper">
                      <button 
                        className={`btn btn-secondary btn-sm filter-btn ${topicSortBy !== 'popularity' ? 'active' : ''}`}
                        onClick={() => setShowTopicSortDropdown(!showTopicSortDropdown)}
                      >
                        Sort
                      </button>
                      {showTopicSortDropdown && (
                        <div className="filter-dropdown">
                          <div className="filter-dropdown-header">
                            <strong>Sort By</strong>
                          </div>
                          <label className="filter-option">
                            <input
                              type="radio"
                              name="topic-sort"
                              checked={topicSortBy === 'alphabetical'}
                              onChange={() => {
                                setTopicSortBy('alphabetical');
                                setShowTopicSortDropdown(false);
                              }}
                            />
                            <span>Alphabetical</span>
                          </label>
                          <label className="filter-option">
                            <input
                              type="radio"
                              name="topic-sort"
                              checked={topicSortBy === 'popularity'}
                              onChange={() => {
                                setTopicSortBy('popularity');
                                setShowTopicSortDropdown(false);
                              }}
                            />
                            <span>Popularity</span>
                          </label>
                        </div>
                      )}
                    </div>
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
                    {(topicSearch || topicClassificationFilter.length > 0) && (
                      <span className="filter-info">
                        Showing {filteredTopics.length} of {topicsTotalCount} total
                        {topicSearch && ` matching "${topicSearch}"`}
                      </span>
                    )}
                  </div>
                  <div className="preferences-grid">
                    {filteredTopics.filter(topic => topic && topic.id && topic.name).map(topic => (
                      <div key={topic.id} className={`preference-item ${preferences.topics.includes(topic.id) ? 'selected':''}`} onClick={() => togglePreference('topics', topic.id)}>
                        <div className="preference-name">{topic.name}</div>
                        <div className="preference-meta-row">
                          {topic.classification && <span className="preference-meta">{topic.classification}</span>}
                          {topic.relationship_count !== undefined && (
                            <span className="preference-count" title="Number of relationships in knowledge graph">
                              {topic.relationship_count} connections
                            </span>
                          )}
                        </div>
                        {preferences.topics.includes(topic.id) && <div className="preference-check"><CheckIcon size={14} /></div>}
                      </div>
                    ))}
                  </div>
                  {renderPagination(topicsPage, topicsTotalPages, loadTopicsPage, 'topics')}
                </>
              ) : (
                <>
                  <div className="search-filter-container">
                    <input className="input search-input" placeholder="Search topics..." value={topicSearch} onChange={e => setTopicSearch(e.target.value)} />
                  </div>
                  <TopicTree
                    hierarchyData={hierarchyData}
                    selectedIds={new Set(preferences.topics)}
                    searchTerm={topicSearch}
                    onSelectionChange={(newSelectedSet) => {
                      setPreferences(prev => ({
                        ...prev,
                        topics: Array.from(newSelectedSet)
                      }));
                      setDirty(true);
                    }}
                    isLoading={hierarchyLoading}
                  />
                </>
              )}
              
              {preferences.topics.length > 0 && <div className="selected-count">{preferences.topics.length} topic(s) selected</div>}
            </div>
          )}

          {(selectedSection === 'organisations' || !selectedSection) && (
            <div className="profile-section">
              <h2><span className="icon-heading"><BuildingIcon size={20} /></span> Organisation Preferences</h2>
              <p className="section-description">Select organisations you want to follow.</p>
              
              {/* Selected Organizations Display */}
              {preferences.organisations.length > 0 && (
                <div className="selected-items-display">
                  <div className="selected-items-header">
                    <strong>Selected Organisations ({preferences.organisations.length})</strong>
                    <button 
                      className="btn-link" 
                      onClick={() => bulkSet('organisations', [], false)}
                      title="Clear all selected organisations"
                    >
                      Clear All
                    </button>
                  </div>
                  <div className="selected-chips">
                    {preferences.organisations.map(orgId => {
                      const org = availableOrgs.find(o => o.id === orgId);
                      const orgName = org?.name || orgId;
                      return (
                        <span key={orgId} className="chip org-chip">
                          {orgName}
                          <button 
                            onClick={() => togglePreference('organisations', orgId)} 
                            className="chip-remove"
                            title={`Remove ${orgName}`}
                          >×</button>
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="search-filter-container">
                <input className="input search-input" placeholder="Search organisations..." value={orgSearch} onChange={e => setOrgSearch(e.target.value)} />
                <div className="filter-dropdown-wrapper">
                  <button 
                    className={`btn btn-secondary btn-sm filter-btn ${orgSortBy !== 'popularity' ? 'active' : ''}`}
                    onClick={() => setShowOrgSortDropdown(!showOrgSortDropdown)}
                  >
                    Sort
                  </button>
                  {showOrgSortDropdown && (
                    <div className="filter-dropdown">
                      <div className="filter-dropdown-header">
                        <strong>Sort By</strong>
                      </div>
                      <label className="filter-option">
                        <input
                          type="radio"
                          name="org-sort"
                          checked={orgSortBy === 'alphabetical'}
                          onChange={() => {
                            setOrgSortBy('alphabetical');
                            setShowOrgSortDropdown(false);
                          }}
                        />
                        <span>Alphabetical</span>
                      </label>
                      <label className="filter-option">
                        <input
                          type="radio"
                          name="org-sort"
                          checked={orgSortBy === 'popularity'}
                          onChange={() => {
                            setOrgSortBy('popularity');
                            setShowOrgSortDropdown(false);
                          }}
                        />
                        <span>Popularity</span>
                      </label>
                    </div>
                  )}
                </div>
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
                {(orgSearch || orgTypeFilter.length > 0) && (
                  <span className="filter-info">
                    Showing {filteredOrgs.length} of {orgsTotalCount} total
                    {orgSearch && ` matching "${orgSearch}"`}
                  </span>
                )}
              </div>
              <div className="preferences-grid">
                {filteredOrgs.filter(org => org && org.id && org.name).map(org => (
                  <div key={org.id} className={`preference-item ${preferences.organisations.includes(org.id) ? 'selected':''}`} onClick={() => togglePreference('organisations', org.id)}>
                    <div className="preference-name">{org.name}</div>
                    <div className="preference-meta-row">
                      {org.org_type && <span className="preference-meta">{org.org_type}</span>}
                      {org.relationship_count !== undefined && (
                        <span className="preference-count" title="Number of relationships in knowledge graph">
                          {org.relationship_count} connections
                        </span>
                      )}
                    </div>
                    {preferences.organisations.includes(org.id) && <div className="preference-check"><CheckIcon size={14} /></div>}
                  </div>
                ))}
              </div>
              {renderPagination(orgsPage, orgsTotalPages, loadOrgsPage, 'organizations')}
              {preferences.organisations.length > 0 && <div className="selected-count">{preferences.organisations.length} organisation(s) selected</div>}
            </div>
          )}

          {(selectedSection === 'people' || !selectedSection) && (
            <div className="profile-section">
              <h2><span className="icon-heading"><ProfileIcon size={20} /></span> People Preferences</h2>
              <p className="section-description">Select people you want to track.</p>
              
              {/* Selected People Display */}
              {preferences.people.length > 0 && (
                <div className="selected-items-display">
                  <div className="selected-items-header">
                    <strong>Selected People ({preferences.people.length})</strong>
                    <button 
                      className="btn-link" 
                      onClick={() => bulkSet('people', [], false)}
                      title="Clear all selected people"
                    >
                      Clear All
                    </button>
                  </div>
                  <div className="selected-chips">
                    {preferences.people.map(personId => {
                      const person = availablePeople.find(p => p.id === personId);
                      const personName = person?.name || personId;
                      return (
                        <span key={personId} className="chip person-chip">
                          {personName}
                          <button 
                            onClick={() => togglePreference('people', personId)} 
                            className="chip-remove"
                            title={`Remove ${personName}`}
                          >×</button>
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="search-filter-container">
                <input className="input search-input" placeholder="Search people..." value={peopleSearch} onChange={e => setPeopleSearch(e.target.value)} />
                <div className="filter-dropdown-wrapper">
                  <button 
                    className={`btn btn-secondary btn-sm filter-btn ${peopleSortBy !== 'popularity' ? 'active' : ''}`}
                    onClick={() => setShowPeopleSortDropdown(!showPeopleSortDropdown)}
                  >
                    Sort
                  </button>
                  {showPeopleSortDropdown && (
                    <div className="filter-dropdown">
                      <div className="filter-dropdown-header">
                        <strong>Sort By</strong>
                      </div>
                      <label className="filter-option">
                        <input
                          type="radio"
                          name="people-sort"
                          checked={peopleSortBy === 'alphabetical'}
                          onChange={() => {
                            setPeopleSortBy('alphabetical');
                            setShowPeopleSortDropdown(false);
                          }}
                        />
                        <span>Alphabetical</span>
                      </label>
                      <label className="filter-option">
                        <input
                          type="radio"
                          name="people-sort"
                          checked={peopleSortBy === 'popularity'}
                          onChange={() => {
                            setPeopleSortBy('popularity');
                            setShowPeopleSortDropdown(false);
                          }}
                        />
                        <span>Popularity</span>
                      </label>
                    </div>
                  )}
                </div>
              </div>
              <div className="bulk-actions">
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('people', filteredPeople.map(p => p.id), true)} title={`Select all ${filteredPeople.length} visible people`}>Select All ({filteredPeople.length})</button>
                <button className="btn btn-secondary btn-sm" onClick={() => bulkSet('people', preferences.people.filter(id => !filteredPeople.map(p => p.id).includes(id)), true)} title="Deselect all visible people">Select None</button>
                {peopleSearch && (
                  <span className="filter-info">
                    Showing {filteredPeople.length} of {peopleTotalCount} total matching "{peopleSearch}"
                  </span>
                )}
              </div>
              <div className="preferences-grid">
                {filteredPeople.filter(person => person && person.id && person.name).map(person => (
                  <div key={person.id} className={`preference-item ${preferences.people.includes(person.id) ? 'selected':''}`} onClick={() => togglePreference('people', person.id)}>
                    <div className="preference-name">{person.name}</div>
                    <div className="preference-meta-row">
                      {person.email && <span className="preference-meta">{person.email}</span>}
                      {person.relationship_count !== undefined && (
                        <span className="preference-count" title="Number of relationships in knowledge graph">
                          {person.relationship_count} connections
                        </span>
                      )}
                    </div>
                    {preferences.people.includes(person.id) && <div className="preference-check"><CheckIcon size={14} /></div>}
                  </div>
                ))}
              </div>
              {renderPagination(peoplePage, peopleTotalPages, loadPeoplePage, 'people')}
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
