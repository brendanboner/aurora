import React, { useState, useEffect, useCallback } from 'react';
import { getAllFeedback, getFeedbackStatistics, updateFeedbackStatus, deleteFeedback } from '../services/api';
import { FeedbackIcon, RefreshIcon, TrashIcon, WarningIcon, CheckIcon } from '../components/icons';
import './Admin.css';
import './AdminFeedback.css';

const AdminFeedback = () => {
  const [feedback, setFeedback] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState('');
  
  // Filters
  const [statusFilter, setStatusFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  
  // Currently editing feedback
  const [editingId, setEditingId] = useState(null);
  const [editStatus, setEditStatus] = useState('');
  const [editPriority, setEditPriority] = useState('');

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const filters = {};
      if (statusFilter) filters.status = statusFilter;
      if (categoryFilter) filters.category = categoryFilter;
      if (priorityFilter) filters.priority = priorityFilter;
      
      const [feedbackData, statsData] = await Promise.all([
        getAllFeedback(filters),
        getFeedbackStatistics()
      ]);
      
      setFeedback(feedbackData);
      setStatistics(statsData);
    } catch (err) {
      console.error('Error loading feedback:', err);
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, categoryFilter, priorityFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleEdit = (item) => {
    setEditingId(item.id);
    setEditStatus(item.status);
    setEditPriority(item.priority || '');
  };

  const handleCancelEdit = () => {
    setEditingId(null);
    setEditStatus('');
    setEditPriority('');
  };

  const handleSaveEdit = async (id) => {
    try {
      await updateFeedbackStatus(id, editStatus, editPriority || null);
      setSuccessMessage('Feedback updated successfully');
      setTimeout(() => setSuccessMessage(''), 3000);
      setEditingId(null);
      await loadData();
    } catch (err) {
      console.error('Error updating feedback:', err);
      setError(err.response?.data?.detail || 'Failed to update feedback');
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Are you sure you want to delete this feedback? This action cannot be undone.')) {
      return;
    }
    
    try {
      await deleteFeedback(id);
      setSuccessMessage('Feedback deleted successfully');
      setTimeout(() => setSuccessMessage(''), 3000);
      await loadData();
    } catch (err) {
      console.error('Error deleting feedback:', err);
      setError(err.response?.data?.detail || 'Failed to delete feedback');
    }
  };

  const getCategoryBadgeClass = (category) => {
    const classes = {
      'feedback': 'badge-feedback',
      'bug': 'badge-bug',
      'accessibility': 'badge-accessibility',
      'styling': 'badge-styling'
    };
    return classes[category] || 'badge-feedback';
  };

  const getStatusBadgeClass = (status) => {
    const classes = {
      'open': 'badge-status-open',
      'in_progress': 'badge-status-in-progress',
      'paused': 'badge-status-paused',
      'closed': 'badge-status-closed'
    };
    return classes[status] || 'badge-status-open';
  };

  const getPriorityBadgeClass = (priority) => {
    if (!priority) return 'badge-priority-none';
    const classes = {
      'low': 'badge-priority-low',
      'medium': 'badge-priority-medium',
      'high': 'badge-priority-high',
      'urgent': 'badge-priority-urgent'
    };
    return classes[priority] || 'badge-priority-none';
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
  };

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1><FeedbackIcon size={28} /> Feedback Management</h1>
        <p>View and manage user feedback submissions</p>
      </div>

      {error && (
        <div className="feedback-error-banner">
          <WarningIcon size={20} />
          <span>{error}</span>
        </div>
      )}

      {successMessage && (
        <div className="feedback-success-banner">
          <CheckIcon size={20} />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Statistics Dashboard */}
      {statistics && (
        <div className="feedback-stats-grid">
          <div className="stat-card">
            <div className="stat-value">{statistics.total_feedback}</div>
            <div className="stat-label">Total Submissions</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{statistics.open_count}</div>
            <div className="stat-label">Open</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{statistics.in_progress_count}</div>
            <div className="stat-label">In Progress</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{statistics.closed_count}</div>
            <div className="stat-label">Closed</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{statistics.bug_count}</div>
            <div className="stat-label">Bugs</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{statistics.urgent_count + statistics.high_count}</div>
            <div className="stat-label">High Priority</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="feedback-filters">
        <div className="filter-group">
          <label>Status</label>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="open">Open</option>
            <option value="in_progress">In Progress</option>
            <option value="paused">Paused</option>
            <option value="closed">Closed</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Category</label>
          <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
            <option value="">All Categories</option>
            <option value="feedback">General Feedback</option>
            <option value="bug">Bug Report</option>
            <option value="accessibility">Accessibility</option>
            <option value="styling">Styling/UI</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Priority</label>
          <select value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)}>
            <option value="">All Priorities</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
        </div>

        <button className="btn-refresh" onClick={loadData} disabled={loading}>
          <RefreshIcon size={16} />
          Refresh
        </button>
      </div>

      {/* Feedback List */}
      <div className="admin-content">
        {loading && <div className="spinner" />}
        
        {!loading && feedback.length === 0 && (
          <div className="empty-state">
            <FeedbackIcon size={48} />
            <p>No feedback submissions found</p>
          </div>
        )}

        {!loading && feedback.length > 0 && (
          <div className="feedback-list">
            {feedback.map(item => (
              <div key={item.id} className="feedback-item">
                <div className="feedback-item-header">
                  <div className="feedback-meta">
                    <span className={`badge ${getCategoryBadgeClass(item.category)}`}>
                      {item.category}
                    </span>
                    {editingId === item.id ? (
                      <>
                        <select
                          value={editStatus}
                          onChange={(e) => setEditStatus(e.target.value)}
                          className="inline-select"
                        >
                          <option value="open">Open</option>
                          <option value="in_progress">In Progress</option>
                          <option value="paused">Paused</option>
                          <option value="closed">Closed</option>
                        </select>
                        <select
                          value={editPriority}
                          onChange={(e) => setEditPriority(e.target.value)}
                          className="inline-select"
                        >
                          <option value="">No Priority</option>
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                          <option value="urgent">Urgent</option>
                        </select>
                      </>
                    ) : (
                      <>
                        <span className={`badge ${getStatusBadgeClass(item.status)}`}>
                          {item.status.replace('_', ' ')}
                        </span>
                        <span className={`badge ${getPriorityBadgeClass(item.priority)}`}>
                          {item.priority || 'No Priority'}
                        </span>
                      </>
                    )}
                  </div>
                  <div className="feedback-actions">
                    {editingId === item.id ? (
                      <>
                        <button
                          className="feedback-btn-save"
                          onClick={() => handleSaveEdit(item.id)}
                        >
                          Save
                        </button>
                        <button
                          className="feedback-btn-cancel"
                          onClick={handleCancelEdit}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="feedback-btn-edit"
                          onClick={() => handleEdit(item)}
                        >
                          Edit
                        </button>
                        <button
                          className="feedback-btn-delete"
                          onClick={() => handleDelete(item.id)}
                          title="Delete feedback"
                        >
                          <TrashIcon size={16} />
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <div className="feedback-item-body">
                  <div className="feedback-text">
                    {item.feedback_text}
                  </div>
                </div>

                <div className="feedback-item-footer">
                  <div className="feedback-user-info">
                    Submitted by <strong>{item.user_display_name || item.user_email}</strong>
                    {item.user_email && item.user_display_name && (
                      <span className="user-email-small"> ({item.user_email})</span>
                    )}
                  </div>
                  <div className="feedback-dates">
                    <span>Submitted: {formatDate(item.submitted_at)}</span>
                    {item.updated_at !== item.submitted_at && (
                      <span> • Updated: {formatDate(item.updated_at)}</span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default AdminFeedback;
