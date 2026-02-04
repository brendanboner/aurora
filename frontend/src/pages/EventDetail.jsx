import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import './EventDetail.css';
import {
  CalendarIcon,
  CheckIcon,
  LinkIcon,
  UsersIcon,
  ChevronLeftIcon,
  MapPinIcon,
  FileTextIcon,
  DocumentIcon,
  UploadIcon,
  DownloadIcon,
} from '../components/icons';
import DocumentUploadModal from '../components/DocumentUploadModal';
import { getEventDocuments, getDocumentDownloadUrl } from '../services/api';

const EventDetail = () => {
  const { urlHash } = useParams();
  const navigate = useNavigate();
  
  const [event, setEvent] = useState(null);
  const [attendees, setAttendees] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attendanceLoading, setAttendanceLoading] = useState(false);
  const [showAttendees, setShowAttendees] = useState(false);
  const [availableDatasources, setAvailableDatasources] = useState([]);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [downloadingDoc, setDownloadingDoc] = useState(null);

  useEffect(() => {
    fetchFilterOptions();
    fetchEventDetails();
    fetchAttendees();
    fetchDocuments();
  }, [urlHash]);

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
        setAvailableDatasources(data.datasources || []);
      }
    } catch (err) {
      console.error('Error fetching filter options:', err);
    }
  };

  const fetchEventDetails = async () => {
    try {
      setLoading(true);
      setError(null);

      const token = localStorage.getItem('auth_token');
      const response = await fetch(`/api/backend/events/${urlHash}`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch event details');
      }

      const data = await response.json();
      setEvent(data);
    } catch (err) {
      console.error('Error fetching event details:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchAttendees = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`/api/backend/events/${urlHash}/attendees`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch attendees');
      }

      const data = await response.json();
      setAttendees(data.attendees || []);
    } catch (err) {
      console.error('Error fetching attendees:', err);
    }
  };

  const fetchDocuments = async () => {
    try {
      const docs = await getEventDocuments(urlHash);
      setDocuments(docs || []);
    } catch (err) {
      console.error('Error fetching documents:', err);
    }
  };

  const handleDownloadDocument = async (doc) => {
    try {
      setDownloadingDoc(doc.url_hash);
      const downloadUrl = await getDocumentDownloadUrl(doc.url_hash);
      if (downloadUrl) {
        window.open(downloadUrl, '_blank');
      }
    } catch (err) {
      console.error('Error downloading document:', err);
      alert('Failed to download document: ' + err.message);
    } finally {
      setDownloadingDoc(null);
    }
  };

  const handleUploadComplete = () => {
    setShowUploadModal(false);
    fetchDocuments();
  };

  const handleAttendanceToggle = async () => {
    try {
      setAttendanceLoading(true);

      const token = localStorage.getItem('auth_token');
      const response = await fetch(`/api/backend/events/${urlHash}/attendance`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          attending: !event.is_attending,
          is_presenting: event.is_presenting || false,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to update attendance');
      }

      // Refresh event details and attendees
      await fetchEventDetails();
      await fetchAttendees();
    } catch (err) {
      console.error('Error updating attendance:', err);
      alert('Failed to update attendance: ' + err.message);
    } finally {
      setAttendanceLoading(false);
    }
  };

  const handlePresentingToggle = async () => {
    if (!event.is_attending) {
      alert('You must be attending to mark yourself as presenting');
      return;
    }

    try {
      setAttendanceLoading(true);

      const token = localStorage.getItem('auth_token');
      const response = await fetch(`/api/backend/events/${urlHash}/attendance`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          attending: true,
          is_presenting: !event.is_presenting,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to update presenting status');
      }

      // Refresh event details and attendees
      await fetchEventDetails();
      await fetchAttendees();
    } catch (err) {
      console.error('Error updating presenting status:', err);
      alert('Failed to update presenting status: ' + err.message);
    } finally {
      setAttendanceLoading(false);
    }
  };

  const formatDate = (dateString) => {
    if (!dateString) return 'TBD';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatDateTime = (dateString) => {
    if (!dateString) return 'TBD';
    const date = new Date(dateString);
    return date.toLocaleString('en-US', {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  const getDatasourceName = (datasourceId) => {
    const datasource = availableDatasources.find(ds => ds.datasource_id === datasourceId);
    return datasource ? datasource.name : datasourceId;
  };

  const isUpcoming = (startDate) => {
    if (!startDate) return false;
    return new Date(startDate) >= new Date();
  };

  if (loading) {
    return (
      <div className="event-detail-container">
        <div className="loading-message">Loading event details...</div>
      </div>
    );
  }

  if (error || !event) {
    return (
      <div className="event-detail-container">
        <button className="back-button" onClick={() => navigate('/events')}>
          <ChevronLeftIcon size={20} /> Back to Events
        </button>
        <div className="error-message">
          {error || 'Event not found'}
        </div>
      </div>
    );
  }

  return (
    <div className="event-detail-container">
      <button className="back-button" onClick={() => navigate('/events')}>
        <ChevronLeftIcon size={20} /> Back to Events
      </button>

      <div className="event-detail-card">
        <div className="event-detail-header">
          <h1>{event.name}</h1>
          {event.url && (
            <a
              href={event.url}
              target="_blank"
              rel="noopener noreferrer"
              className="event-link-button"
            >
              <LinkIcon size={20} /> Visit Event Page
            </a>
          )}
        </div>

        <div className="event-detail-meta">
          <span className="event-type-badge">{event.event_type}</span>
          {event.datasource_id && (
            <span className="event-datasource-badge">
              {getDatasourceName(event.datasource_id)}
            </span>
          )}
          {event.status && event.status !== 'scheduled' && (
            <span className={`event-status-badge status-${event.status}`}>
              {event.status}
            </span>
          )}
          {!isUpcoming(event.start_date) && (
            <span className="past-badge">Past Event</span>
          )}
        </div>

        <div className="event-detail-section">
          <h2><CalendarIcon size={24} /> Date & Time</h2>
          <div className="event-dates">
            <div className="date-item">
              <strong>Start:</strong> {formatDateTime(event.start_date)}
            </div>
            {event.end_date && event.end_date !== event.start_date && (
              <div className="date-item">
                <strong>End:</strong> {formatDateTime(event.end_date)}
              </div>
            )}
            {event.timezone && (
              <div className="date-item">
                <strong>Timezone:</strong> {event.timezone}
              </div>
            )}
          </div>
        </div>

        {event.location && (
          <div className="event-detail-section">
            <h2><MapPinIcon size={24} /> Location</h2>
            <p>{event.location}</p>
          </div>
        )}

        {event.description && (
          <div className="event-detail-section">
            <h2><FileTextIcon size={24} /> Description</h2>
            <p className="event-description-text">{event.description}</p>
          </div>
        )}

        <div className="event-detail-section">
          <h2><UsersIcon size={24} /> Attendance</h2>
          <div className="attendance-stats">
            <div className="stat-item">
              <strong>{event.attendee_count || 0}</strong>
              <span>Attending</span>
            </div>
            {event.presenter_count > 0 && (
              <div className="stat-item">
                <strong>{event.presenter_count}</strong>
                <span>Presenting</span>
              </div>
            )}
          </div>

          <div className="attendance-actions">
            <button
              className={`attendance-button ${event.is_attending ? 'attending' : ''}`}
              onClick={handleAttendanceToggle}
              disabled={attendanceLoading}
            >
              <CheckIcon size={20} />
              {event.is_attending ? 'Not Attending' : 'Mark as Attending'}
            </button>

            {event.is_attending && (
              <button
                className={`presenting-button ${event.is_presenting ? 'presenting' : ''}`}
                onClick={handlePresentingToggle}
                disabled={attendanceLoading}
              >
                {event.is_presenting ? 'Not Presenting' : 'Mark as Presenting'}
              </button>
            )}
          </div>

          {attendees.length > 0 && (
            <div className="attendees-section">
              <button
                className="show-attendees-button"
                onClick={() => setShowAttendees(!showAttendees)}
              >
                {showAttendees ? 'Hide' : 'Show'} Attendees ({attendees.length})
              </button>

              {showAttendees && (
                <div className="attendees-list">
                  {attendees.map((attendee, index) => (
                    <div key={index} className="attendee-item">
                      <div className="attendee-info">
                        <strong>{attendee.name}</strong>
                        {attendee.email && (
                          <span className="attendee-email">{attendee.email}</span>
                        )}
                      </div>
                      {attendee.is_presenting && (
                        <span className="presenting-badge">Presenting</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Documents Section */}
        <div className="event-detail-section">
          <div className="section-header">
            <h2><DocumentIcon size={24} /> Documents</h2>
            <button
              className="upload-button"
              onClick={() => setShowUploadModal(true)}
            >
              <UploadIcon size={18} /> Upload
            </button>
          </div>

          {documents.length === 0 ? (
            <p className="no-documents">No documents have been uploaded for this event yet.</p>
          ) : (
            <div className="documents-list">
              {documents.map((doc) => (
                <div key={doc.url_hash} className="document-item">
                  <div className="document-info">
                    <DocumentIcon size={20} />
                    <div className="document-details">
                      <span className="document-title">{doc.title || doc.name || 'Untitled Document'}</span>
                      <span className="document-meta">
                        {doc.category && <span className="document-category">{doc.category}</span>}
                        {doc.uploaded_at && (
                          <span className="document-date">
                            Uploaded {new Date(doc.uploaded_at).toLocaleDateString()}
                          </span>
                        )}
                      </span>
                    </div>
                  </div>
                  <button
                    className="download-button"
                    onClick={() => handleDownloadDocument(doc)}
                    disabled={downloadingDoc === doc.url_hash}
                  >
                    <DownloadIcon size={18} />
                    {downloadingDoc === doc.url_hash ? 'Downloading...' : 'Download'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Document Upload Modal */}
      {showUploadModal && (
        <DocumentUploadModal
          eventId={urlHash}
          eventName={event?.name}
          onClose={() => setShowUploadModal(false)}
          onUploadComplete={handleUploadComplete}
        />
      )}
    </div>
  );
};

export default EventDetail;
