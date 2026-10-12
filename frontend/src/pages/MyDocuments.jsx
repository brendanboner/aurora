import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import './MyDocuments.css';
import {
  DocumentIcon,
  FileTextIcon,
  TrashIcon,
  EditIcon,
  DownloadIcon,
  RefreshIcon,
  CheckIcon,
  CloseIcon,
  CalendarIcon,
  LinkIcon,
  MapPinIcon,
  SearchIcon,
} from '../components/icons';
import {
  getUserUploads,
  getDocumentCategories,
  getDocumentDownloadUrl,
  updateDocument,
  deleteDocument,
  getDocumentEvents,
} from '../services/api';

const MyDocuments = () => {
  const navigate = useNavigate();
  const location = useLocation();
  
  // Documents list
  const [documents, setDocuments] = useState([]);
  const [categories, setCategories] = useState([]);
  
  // UI state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [editingDoc, setEditingDoc] = useState(null);
  const [editForm, setEditForm] = useState({ title: '', category: '' });
  const [saving, setSaving] = useState(false);
  const [deletingDoc, setDeletingDoc] = useState(null);
  const [expandedDoc, setExpandedDoc] = useState(null);
  const [docEvents, setDocEvents] = useState({});
  
  // Events for linking
  const [availableEvents, setAvailableEvents] = useState([]);
  const [eventDatasources, setEventDatasources] = useState([]);
  const [eventSearchTerm, setEventSearchTerm] = useState('');
  const [eventSourceFilter, setEventSourceFilter] = useState('');
  const [eventDateFilter, setEventDateFilter] = useState('all'); // 'all', 'upcoming', 'past'
  const [selectedEvents, setSelectedEvents] = useState([]);
  const [loadingEvents, setLoadingEvents] = useState(false);

  useEffect(() => {
    fetchDocuments();
    fetchCategories();
    
    // Check for success message from upload redirect
    if (location.state?.message) {
      setSuccessMessage(location.state.message);
      // Clear the state so message doesn't show again on refresh
      window.history.replaceState({}, document.title);
      // Auto-hide after 5 seconds
      setTimeout(() => setSuccessMessage(null), 5000);
    }
  }, [location.state]);

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getUserUploads(100, 0);
      setDocuments(data.documents || []);
    } catch (err) {
      console.error('Error fetching documents:', err);
      setError('Failed to load your documents');
    } finally {
      setLoading(false);
    }
  };

  const fetchCategories = async () => {
    try {
      const data = await getDocumentCategories();
      setCategories(data.categories || []);
    } catch (err) {
      console.error('Error fetching categories:', err);
    }
  };

  const fetchDocumentEvents = async (urlHash) => {
    try {
      const events = await getDocumentEvents(urlHash);
      setDocEvents(prev => ({ ...prev, [urlHash]: events }));
      return events;
    } catch (err) {
      console.error('Error fetching document events:', err);
      return [];
    }
  };

  const fetchAvailableEvents = async () => {
    try {
      setLoadingEvents(true);
      const token = localStorage.getItem('auth_token');
      
      // Fetch events
      const response = await fetch('/api/backend/events?limit=200', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      if (response.ok) {
        const data = await response.json();
        setAvailableEvents(data.events || []);
      }
      
      // Fetch filter options
      const filtersResponse = await fetch('/api/backend/events/metadata/filters', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      if (filtersResponse.ok) {
        const filterData = await filtersResponse.json();
        setEventDatasources(filterData.datasources || []);
      }
    } catch (err) {
      console.error('Error fetching events:', err);
    } finally {
      setLoadingEvents(false);
    }
  };

  const handleDownload = async (doc) => {
    try {
      const downloadUrl = await getDocumentDownloadUrl(doc.url_hash);
      if (downloadUrl) {
        window.open(downloadUrl, '_blank');
      }
    } catch (err) {
      console.error('Error downloading document:', err);
      alert('Failed to download document');
    }
  };

  const handleStartEdit = async (doc) => {
    setEditingDoc(doc.url_hash);
    setEditForm({
      title: doc.title || '',
      category: doc.category || 'general'
    });
    
    // Fetch available events if not already loaded
    if (availableEvents.length === 0) {
      await fetchAvailableEvents();
    }
    
    // Fetch current related events and set them as selected
    const currentEvents = await fetchDocumentEvents(doc.url_hash);
    setSelectedEvents(currentEvents?.map(e => e.url_hash) || []);
  };

  const handleCancelEdit = () => {
    setEditingDoc(null);
    setEditForm({ title: '', category: '' });
    setSelectedEvents([]);
    setEventSearchTerm('');
    setEventSourceFilter('');
    setEventDateFilter('all');
  };

  const handleSaveEdit = async (urlHash) => {
    try {
      setSaving(true);
      await updateDocument(urlHash, {
        ...editForm,
        related_events: selectedEvents
      });
      
      // Update local state
      setDocuments(prev => prev.map(doc => 
        doc.url_hash === urlHash 
          ? { ...doc, title: editForm.title, category: editForm.category }
          : doc
      ));
      
      // Refresh document events
      await fetchDocumentEvents(urlHash);
      
      setEditingDoc(null);
      setEditForm({ title: '', category: '' });
      setSelectedEvents([]);
    } catch (err) {
      console.error('Error updating document:', err);
      alert('Failed to update document');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (urlHash) => {
    if (!window.confirm('Are you sure you want to delete this document? This action cannot be undone.')) {
      return;
    }
    
    try {
      setDeletingDoc(urlHash);
      await deleteDocument(urlHash);
      
      // Remove from local state
      setDocuments(prev => prev.filter(doc => doc.url_hash !== urlHash));
    } catch (err) {
      console.error('Error deleting document:', err);
      alert('Failed to delete document');
    } finally {
      setDeletingDoc(null);
    }
  };

  const handleToggleExpand = async (urlHash) => {
    if (expandedDoc === urlHash) {
      setExpandedDoc(null);
    } else {
      setExpandedDoc(urlHash);
      if (!docEvents[urlHash]) {
        await fetchDocumentEvents(urlHash);
      }
    }
  };

  const toggleEventSelection = (eventHash) => {
    setSelectedEvents(prev => 
      prev.includes(eventHash)
        ? prev.filter(e => e !== eventHash)
        : [...prev, eventHash]
    );
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const getCategoryName = (categoryId) => {
    const cat = categories.find(c => c.id === categoryId);
    return cat ? cat.name : categoryId;
  };

  const getDatasourceName = (datasourceId) => {
    const ds = eventDatasources.find(d => d.datasource_id === datasourceId);
    return ds ? ds.name : datasourceId;
  };

  const isUpcoming = (startDate) => {
    if (!startDate) return false;
    return new Date(startDate) >= new Date();
  };

  // Filter events based on search and filters
  const filteredAvailableEvents = availableEvents.filter(event => {
    const matchesSearch = eventSearchTerm === '' || 
      event.name.toLowerCase().includes(eventSearchTerm.toLowerCase());
    
    const matchesSource = eventSourceFilter === '' || 
      event.datasource_id === eventSourceFilter;
    
    const matchesDate = 
      eventDateFilter === 'all' ||
      (eventDateFilter === 'upcoming' && isUpcoming(event.start_date)) ||
      (eventDateFilter === 'past' && !isUpcoming(event.start_date));
    
    return matchesSearch && matchesSource && matchesDate;
  });

  if (loading) {
    return (
      <div className="my-documents-container">
        <div className="documents-header">
          <h1><DocumentIcon size={32} /> My Documents</h1>
        </div>
        <div className="loading-state">Loading your documents...</div>
      </div>
    );
  }

  return (
    <div className="my-documents-container">
      <div className="documents-header">
        <div className="header-left">
          <h1><DocumentIcon size={32} /> My Documents</h1>
          <p>Manage your uploaded documents and link them to events</p>
        </div>
        <div className="header-actions">
          <button className="action-button secondary" onClick={fetchDocuments}>
            <RefreshIcon size={18} /> Refresh
          </button>
          <button className="action-button primary" onClick={() => navigate('/upload')}>
            Upload New
          </button>
        </div>
      </div>

      {successMessage && (
        <div className="success-message">
          <CheckIcon size={18} />
          {successMessage}
        </div>
      )}

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      {documents.length === 0 ? (
        <div className="empty-state">
          <FileTextIcon size={64} />
          <h3>No Documents Yet</h3>
          <p>You haven't uploaded any documents. Upload your first document to get started.</p>
          <button className="action-button primary" onClick={() => navigate('/upload')}>
            Upload Document
          </button>
        </div>
      ) : (
        <div className="documents-list">
          {documents.map((doc) => (
            <div 
              key={doc.url_hash} 
              className={`document-card ${expandedDoc === doc.url_hash ? 'expanded' : ''} ${editingDoc === doc.url_hash ? 'editing' : ''}`}
            >
              <div className="document-main" onClick={() => editingDoc !== doc.url_hash && handleToggleExpand(doc.url_hash)}>
                <div className="document-icon">
                  <FileTextIcon size={24} />
                </div>
                
                <div className="document-info">
                  {editingDoc === doc.url_hash ? (
                    <div className="edit-form" onClick={(e) => e.stopPropagation()}>
                      <div className="edit-row">
                        <label>Title</label>
                        <input
                          type="text"
                          value={editForm.title}
                          onChange={(e) => setEditForm(prev => ({ ...prev, title: e.target.value }))}
                          placeholder="Document title"
                        />
                      </div>
                      <div className="edit-row">
                        <label>Category</label>
                        <select
                          value={editForm.category}
                          onChange={(e) => setEditForm(prev => ({ ...prev, category: e.target.value }))}
                        >
                          {categories.map((cat) => (
                            <option key={cat.id} value={cat.id}>{cat.name}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ) : (
                    <>
                      <h3 className="document-title">{doc.title || 'Untitled Document'}</h3>
                      <div className="document-meta">
                        <span className="category-badge">{getCategoryName(doc.category)}</span>
                        <span className="upload-date">Uploaded {formatDate(doc.uploaded_at || doc.upload_timestamp)}</span>
                      </div>
                    </>
                  )}
                </div>

                {editingDoc !== doc.url_hash && (
                  <div className="document-actions" onClick={(e) => e.stopPropagation()}>
                    <button 
                      className="icon-button download" 
                      onClick={() => handleDownload(doc)}
                      title="Download"
                    >
                      <DownloadIcon size={18} />
                    </button>
                    <button 
                      className="icon-button edit" 
                      onClick={() => handleStartEdit(doc)}
                      title="Edit"
                    >
                      <EditIcon size={18} />
                    </button>
                    <button 
                      className="icon-button delete" 
                      onClick={() => handleDelete(doc.url_hash)}
                      disabled={deletingDoc === doc.url_hash}
                      title="Delete"
                    >
                      <TrashIcon size={18} />
                    </button>
                  </div>
                )}
              </div>

              {/* Edit Mode: Event Selection */}
              {editingDoc === doc.url_hash && (
                <div className="document-edit-panel" onClick={(e) => e.stopPropagation()}>
                  <div className="events-section">
                    <h4>Link to Events</h4>
                    <p className="section-description">Select events to associate with this document</p>
                    
                    {/* Filters */}
                    <div className="event-filters">
                      <div className="search-box">
                        <SearchIcon size={18} />
                        <input
                          type="text"
                          placeholder="Search events by title..."
                          value={eventSearchTerm}
                          onChange={(e) => setEventSearchTerm(e.target.value)}
                        />
                      </div>
                      
                      <div className="filter-selects">
                        <select
                          value={eventSourceFilter}
                          onChange={(e) => setEventSourceFilter(e.target.value)}
                        >
                          <option value="">All Sources</option>
                          {eventDatasources.map((ds) => (
                            <option key={ds.datasource_id} value={ds.datasource_id}>
                              {ds.name}
                            </option>
                          ))}
                        </select>
                        
                        <select
                          value={eventDateFilter}
                          onChange={(e) => setEventDateFilter(e.target.value)}
                        >
                          <option value="all">All Dates</option>
                          <option value="upcoming">Upcoming</option>
                          <option value="past">Past</option>
                        </select>
                      </div>
                    </div>

                    {/* Selected Events Summary */}
                    {selectedEvents.length > 0 && (
                      <div className="selected-summary">
                        <CheckIcon size={16} />
                        <span>{selectedEvents.length} event(s) selected</span>
                      </div>
                    )}

                    {/* Events Grid */}
                    {loadingEvents ? (
                      <div className="loading-events">Loading events...</div>
                    ) : (
                      <div className="doc-events-grid">
                        {filteredAvailableEvents.slice(0, 20).map((event) => (
                          <div
                            key={event.url_hash}
                            className={`doc-event-card ${selectedEvents.includes(event.url_hash) ? 'selected' : ''} ${!isUpcoming(event.start_date) ? 'past' : ''}`}
                            onClick={() => toggleEventSelection(event.url_hash)}
                          >
                            <div className="doc-event-card-check">
                              {selectedEvents.includes(event.url_hash) ? (
                                <CheckIcon size={16} />
                              ) : (
                                <div className="doc-check-empty" />
                              )}
                            </div>
                            <div className="doc-event-card-content">
                              <h5 className="doc-event-title">{event.name}</h5>
                              <div className="doc-event-meta">
                                <span className="doc-event-type-badge">{event.event_type}</span>
                                {event.datasource_id && (
                                  <span className="doc-event-source-badge">
                                    {getDatasourceName(event.datasource_id)}
                                  </span>
                                )}
                              </div>
                              <div className="doc-event-date">
                                <CalendarIcon size={14} />
                                <span>{formatDate(event.start_date)}</span>
                              </div>
                              {event.location && (
                                <div className="doc-event-location">
                                  <MapPinIcon size={14} />
                                  <span>{event.location.length > 30 ? event.location.substring(0, 30) + '...' : event.location}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                        {filteredAvailableEvents.length === 0 && (
                          <div className="no-events-found">
                            <p>No events match your filters</p>
                          </div>
                        )}
                        {filteredAvailableEvents.length > 20 && (
                          <div className="more-events-hint">
                            <p>Showing 20 of {filteredAvailableEvents.length} events. Use filters to narrow down.</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Edit Actions */}
                  <div className="edit-panel-actions">
                    <button 
                      className="edit-btn save" 
                      onClick={() => handleSaveEdit(doc.url_hash)}
                      disabled={saving}
                    >
                      <CheckIcon size={16} /> {saving ? 'Saving...' : 'Save Changes'}
                    </button>
                    <button 
                      className="edit-btn cancel" 
                      onClick={handleCancelEdit}
                      disabled={saving}
                    >
                      <CloseIcon size={16} /> Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* View Mode: Related Events */}
              {expandedDoc === doc.url_hash && editingDoc !== doc.url_hash && (
                <div className="document-details">
                  <div className="details-section">
                    <h4>Related Events</h4>
                    {docEvents[doc.url_hash] === undefined ? (
                      <p className="loading-text">Loading events...</p>
                    ) : docEvents[doc.url_hash]?.length > 0 ? (
                      <div className="related-events-list">
                        {docEvents[doc.url_hash].map((event) => (
                          <div 
                            key={event.url_hash} 
                            className="related-event"
                            onClick={() => navigate(`/events/${event.url_hash}`)}
                          >
                            <CalendarIcon size={16} />
                            <span className="event-name">{event.name}</span>
                            <span className="event-date">{formatDate(event.start_date)}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="no-events">No related events. Click Edit to link this document to events.</p>
                    )}
                  </div>
                  
                  {doc.url && (
                    <div className="details-section">
                      <h4>Source URL</h4>
                      <a 
                        href={doc.url} 
                        target="_blank" 
                        rel="noopener noreferrer" 
                        className="source-link"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <LinkIcon size={16} /> {doc.url}
                      </a>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default MyDocuments;
