import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './Events.css';
import { CalendarIcon, RefreshIcon, CheckIcon, LinkIcon, EyeIcon, EyeOffIcon } from '../components/icons';

const Events = () => {
  const navigate = useNavigate();
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Available filter options
  const [availableEventTypes, setAvailableEventTypes] = useState([]);
  const [availableDatasources, setAvailableDatasources] = useState([]);
  
  // Filters
  const [filter, setFilter] = useState('upcoming'); // 'upcoming', 'past', 'all'
  const [eventType, setEventType] = useState('');
  const [datasourceId, setDatasourceId] = useState('');
  const [sortBy, setSortBy] = useState('start_date');
  const [sortOrder, setSortOrder] = useState('asc');
  const [showCancelled, setShowCancelled] = useState(true); // Toggle for cancelled events

  // Fetch available filter options on mount
  useEffect(() => {
    fetchFilterOptions();
  }, []);

  useEffect(() => {
    fetchEvents();
  }, [filter, eventType, datasourceId, sortBy, sortOrder]);

  const fetchFilterOptions = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch('/api/backend/events/metadata/filters', {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setAvailableEventTypes(data.event_types || []);
        setAvailableDatasources(data.datasources || []);
      }
    } catch (err) {
      console.error('Error fetching filter options:', err);
    }
  };

  const fetchEvents = async () => {
    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams();
      
      if (filter === 'upcoming') {
        params.append('upcoming', 'true');
      } else if (filter === 'past') {
        params.append('upcoming', 'false');
      }
      
      if (eventType) params.append('event_type', eventType);
      if (datasourceId) params.append('datasource_id', datasourceId);
      params.append('sort_by', sortBy);
      params.append('sort_order', sortOrder);
      params.append('limit', '100');

      const token = localStorage.getItem('auth_token');
      const response = await fetch(`/api/backend/events?${params.toString()}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch events');
      }

      const data = await response.json();
      setEvents(data.events || []);
    } catch (err) {
      console.error('Error fetching events:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'TBD';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatDateTime = (dateString) => {
    if (!dateString) return 'TBD';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  const isUpcoming = (startDate) => {
    if (!startDate) return false;
    return new Date(startDate) >= new Date();
  };

  const handleEventClick = (urlHash) => {
    navigate(`/events/${urlHash}`);
  };

  const handleExternalLink = (e, url) => {
    e.stopPropagation();
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  // Filter events based on cancelled toggle
  const getFilteredEvents = () => {
    if (showCancelled) {
      return events; // Show all events including cancelled
    }
    return events.filter(event => event.status !== 'cancelled');
  };

  const filteredEvents = getFilteredEvents();

  if (loading && events.length === 0) {
    return (
      <div className="events-container">
        <div className="events-header">
          <h1><CalendarIcon size={32} /> Events</h1>
        </div>
        <div className="loading-message">Loading events...</div>
      </div>
    );
  }

  return (
    <div className="events-container">
      <div className="events-header">
        <h1><CalendarIcon size={32} /> Events</h1>
        <button className="refresh-button" onClick={fetchEvents} disabled={loading}>
          <RefreshIcon size={20} /> Refresh
        </button>
      </div>

      {error && (
        <div className="error-message">
          Error loading events: {error}
        </div>
      )}

      <div className="events-filters">
        <div className="filter-group">
          <label>Show:</label>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="upcoming">Upcoming Events</option>
            <option value="past">Past Events</option>
            <option value="all">All Events</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Type:</label>
          <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
            <option value="">All Types</option>
            {availableEventTypes.map((et) => (
              <option key={et.type} value={et.type}>
                {et.type.charAt(0).toUpperCase() + et.type.slice(1)} ({et.count})
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Source:</label>
          <select value={datasourceId} onChange={(e) => setDatasourceId(e.target.value)}>
            <option value="">All Sources</option>
            {availableDatasources.map((ds) => (
              <option key={ds.datasource_id} value={ds.datasource_id}>
                {ds.name} ({ds.event_count})
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Sort By:</label>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="start_date">Date</option>
            <option value="name">Name</option>
            <option value="event_type">Type</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Order:</label>
          <select value={sortOrder} onChange={(e) => setSortOrder(e.target.value)}>
            <option value="asc">Ascending</option>
            <option value="desc">Descending</option>
          </select>
        </div>
        
        <div className="filter-group">
          <label>Cancelled Events:</label>
          <button
            className={`toggle-button ${showCancelled ? 'active' : ''}`}
            onClick={() => setShowCancelled(!showCancelled)}
          >
            {showCancelled ? <EyeIcon size={16} /> : <EyeOffIcon size={16} />}
          </button>
        </div>
      </div>

      <div className="events-grid">
        {filteredEvents.length === 0 ? (
          <div className="no-events">
            <CalendarIcon size={48} color="#999" />
            <p>No events found</p>
          </div>
        ) : (
          filteredEvents.map((event) => (
            <div
              key={event.url_hash}
              className={`event-card ${!isUpcoming(event.start_date) ? 'past-event' : ''}`}
              onClick={() => handleEventClick(event.url_hash)}
            >
              <div className="event-card-header">
                <h3 className="event-name">{event.name}</h3>
                {event.url && (
                  <button
                    className="external-link-button"
                    onClick={(e) => handleExternalLink(e, event.url)}
                    title="Open event link"
                  >
                    <LinkIcon size={18} />
                  </button>
                )}
              </div>

              <div className="event-meta">
                <span className="event-type">{event.event_type}</span>
                {event.status && event.status !== 'scheduled' && (
                  <span className={`event-status status-${event.status}`}>
                    {event.status}
                  </span>
                )}
              </div>

              <div className="event-date">
                <CalendarIcon size={16} />
                <span>
                  {formatDate(event.start_date)}
                  {event.end_date && event.end_date !== event.start_date && (
                    <> - {formatDate(event.end_date)}</>
                  )}
                </span>
              </div>

              {event.location && (
                <div className="event-location">
                  📍 {event.location}
                </div>
              )}

              {event.description && (
                <div className="event-description">
                  {event.description.length > 150
                    ? `${event.description.substring(0, 150)}...`
                    : event.description}
                </div>
              )}

              <div className="event-footer">
                <div className="attendance-info">
                  <CheckIcon size={16} />
                  <span>{event.attendee_count || 0} attending</span>
                  {event.presenter_count > 0 && (
                    <span className="presenter-count">
                      ({event.presenter_count} presenting)
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default Events;
