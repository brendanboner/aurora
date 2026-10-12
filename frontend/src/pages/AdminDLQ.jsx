import React, { useState, useEffect, useCallback, useRef } from 'react';
import './AdminDLQ.css';
import { AlertCircleIcon, RefreshIcon, LinkIcon, TrashIcon, PlayIcon, WarningIcon, SearchIcon } from '../components/icons';

const AdminDLQ = () => {
  const [dlqStatus, setDlqStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedMessages, setSelectedMessages] = useState(new Set());
  const [filters, setFilters] = useState({
    error: '',
    batchId: '',
    datasourceId: ''
  });
  const [appliedFilters, setAppliedFilters] = useState({
    error: '',
    batchId: '',
    datasourceId: ''
  });
  const [retrying, setRetrying] = useState(false);
  const [successMessage, setSuccessMessage] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 10;
  
  // Ref to prevent duplicate requests
  const fetchingRef = useRef(false);

  const fetchDLQMessages = useCallback(async () => {
    // Prevent duplicate requests
    if (fetchingRef.current) {
      return;
    }
    fetchingRef.current = true;
    
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (appliedFilters.error) params.append('error_filter', appliedFilters.error);
      if (appliedFilters.batchId) params.append('batch_id', appliedFilters.batchId);
      if (appliedFilters.datasourceId) params.append('datasource_id', appliedFilters.datasourceId);
      
      const url = `/api/backend/admin/dlq-messages${params.toString() ? '?' + params.toString() : ''}`;
      const response = await fetch(url);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      setDlqStatus(data);
      setError(null);
      setSelectedMessages(new Set());
    } catch (err) {
      console.error('Error fetching DLQ messages:', err);
      setError(err.message);
    } finally {
      setLoading(false);
      fetchingRef.current = false;
    }
  }, [appliedFilters]);

  useEffect(() => {
    fetchDLQMessages();
    // Auto-refresh every 5 minutes (300 seconds) - user actions trigger immediate refresh
    const interval = setInterval(fetchDLQMessages, 300000);
    return () => clearInterval(interval);
  }, [fetchDLQMessages]);

  const handleClearFilters = () => {
    setFilters({ error: '', batchId: '', datasourceId: '' });
    setAppliedFilters({ error: '', batchId: '', datasourceId: '' });
    setCurrentPage(1);
  };

  const handleSelectAll = () => {
    if (!dlqStatus?.messages) return;
    
    const currentPageMessages = dlqStatus.messages.slice(
      (currentPage - 1) * itemsPerPage,
      currentPage * itemsPerPage
    );
    
    if (selectedMessages.size === currentPageMessages.length) {
      setSelectedMessages(new Set());
    } else {
      setSelectedMessages(new Set(currentPageMessages.map(m => m.message_id)));
    }
  };

  const handleSelectMessage = (messageId) => {
    const newSelected = new Set(selectedMessages);
    if (newSelected.has(messageId)) {
      newSelected.delete(messageId);
    } else {
      newSelected.add(messageId);
    }
    setSelectedMessages(newSelected);
  };

  const handleRetrySelected = async () => {
    if (selectedMessages.size === 0) return;
    
    if (!window.confirm(`Retry ${selectedMessages.size} selected message(s)? They will be moved back to the processing queue.`)) {
      return;
    }
    
    try {
      setRetrying(true);
      const response = await fetch('/api/backend/admin/dlq-retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_ids: Array.from(selectedMessages) })
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const result = await response.json();
      setSuccessMessage(`✅ Retried ${result.retried_count} message(s)${result.failed_count > 0 ? `, ${result.failed_count} failed` : ''}`);
      setTimeout(() => setSuccessMessage(null), 5000);
      
      // Refresh the list
      await fetchDLQMessages();
    } catch (err) {
      setError(`Failed to retry messages: ${err.message}`);
    } finally {
      setRetrying(false);
    }
  };

  const handleRetryAll = async () => {
    if (!dlqStatus?.message_count) return;
    
    if (!window.confirm(`⚠️ WARNING: Retry ALL ${dlqStatus.message_count} message(s) in the Dead Letter Queue?\n\nThis will move all failed messages back to the processing queue.`)) {
      return;
    }
    
    try {
      setRetrying(true);
      const response = await fetch('/api/backend/admin/dlq-retry-all', {
        method: 'POST'
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const result = await response.json();
      setSuccessMessage(`✅ Retried ${result.retried_count} message(s)${result.failed_count > 0 ? `, ${result.failed_count} failed` : ''}`);
      setTimeout(() => setSuccessMessage(null), 5000);
      
      // Refresh the list
      await fetchDLQMessages();
    } catch (err) {
      setError(`Failed to retry all messages: ${err.message}`);
    } finally {
      setRetrying(false);
    }
  };

  const handlePurgeDLQ = async () => {
    if (!window.confirm('⚠️ DANGER: Permanently DELETE all messages from the Dead Letter Queue?\n\nThis action cannot be undone!')) {
      return;
    }
    
    try {
      const response = await fetch('/api/backend/admin/dlq-purge', {
        method: 'DELETE'
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const result = await response.json();
      setSuccessMessage(`✅ Purged ${result.messages_purged} message(s) from DLQ`);
      setTimeout(() => setSuccessMessage(null), 5000);
      
      // Refresh the list
      await fetchDLQMessages();
    } catch (err) {
      setError(`Failed to purge DLQ: ${err.message}`);
    }
  };

  const handleDedupe = async () => {
    if (!dlqStatus?.duplicate_count) return;
    
    if (!window.confirm(`Remove ${dlqStatus.duplicate_message_count} duplicate message(s) from the DLQ?\n\nThis will keep only the most recent message for each URL.`)) {
      return;
    }
    
    try {
      setRetrying(true);
      const response = await fetch('/api/backend/admin/dlq-dedupe', {
        method: 'POST'
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const result = await response.json();
      setSuccessMessage(`✅ Removed ${result.duplicates_removed} duplicate(s), kept ${result.unique_messages_kept} unique message(s)`);
      setTimeout(() => setSuccessMessage(null), 5000);
      
      // Refresh the list
      await fetchDLQMessages();
    } catch (err) {
      setError(`Failed to dedupe DLQ: ${err.message}`);
    } finally {
      setRetrying(false);
    }
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'N/A';
    try {
      const date = new Date(timestamp);
      return date.toLocaleString();
    } catch {
      return timestamp;
    }
  };

  const truncateError = (error, maxLength = 100) => {
    if (!error) return 'Unknown error';
    return error.length > maxLength ? error.substring(0, maxLength) + '...' : error;
  };

  // Pagination
  const totalPages = dlqStatus?.messages ? Math.ceil(dlqStatus.messages.length / itemsPerPage) : 0;
  const paginatedMessages = dlqStatus?.messages?.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  ) || [];

  return (
    <div className="admin-container admin-dlq">
      <div className="admin-header">
        <div className="header-content">
          <h1>
            <AlertCircleIcon size={24} />
            Dead Letter Queue
          </h1>
          <p>View and manage failed messages that couldn't be processed</p>
        </div>
        <button 
          className="refresh-btn"
          onClick={fetchDLQMessages}
          disabled={loading}
          title="Refresh"
        >
          <RefreshIcon size={18} className={loading ? 'spinning' : ''} />
        </button>
      </div>

      {error && (
        <div className="alert alert-error">
          <WarningIcon size={18} />
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {successMessage && (
        <div className="alert alert-success">
          <span>{successMessage}</span>
        </div>
      )}

      <div className="admin-content">
        {/* Filters Section */}
        <div className="filters-section">
          <h3><SearchIcon size={16} /> Filter Messages</h3>
          <div className="filters-grid">
            <div className="filter-group">
              <label htmlFor="error-filter">Error Type</label>
              <select
                id="error-filter"
                value={filters.error}
                onChange={(e) => {
                  setFilters({ ...filters, error: e.target.value });
                  setAppliedFilters({ ...appliedFilters, error: e.target.value });
                  setCurrentPage(1);
                }}
              >
                <option value="">All Errors</option>
                {dlqStatus?.filter_options?.error_types?.map((errorType) => (
                  <option key={errorType} value={errorType}>
                    {errorType}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="batch-filter">Batch ID</label>
              <select
                id="batch-filter"
                value={filters.batchId}
                onChange={(e) => {
                  setFilters({ ...filters, batchId: e.target.value });
                  setAppliedFilters({ ...appliedFilters, batchId: e.target.value });
                  setCurrentPage(1);
                }}
              >
                <option value="">All Batches</option>
                {dlqStatus?.filter_options?.batch_ids?.map((batchId) => (
                  <option key={batchId} value={batchId}>
                    {batchId.length > 20 ? `${batchId.substring(0, 20)}...` : batchId}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="datasource-filter">Datasource</label>
              <select
                id="datasource-filter"
                value={filters.datasourceId}
                onChange={(e) => {
                  setFilters({ ...filters, datasourceId: e.target.value });
                  setAppliedFilters({ ...appliedFilters, datasourceId: e.target.value });
                  setCurrentPage(1);
                }}
              >
                <option value="">All Datasources</option>
                {dlqStatus?.filter_options?.datasource_ids?.map((datasourceId) => (
                  <option key={datasourceId} value={datasourceId}>
                    {datasourceId}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-actions">
              <button 
                className="btn-secondary" 
                onClick={handleClearFilters}
                disabled={!filters.error && !filters.batchId && !filters.datasourceId}
              >
                Clear Filters
              </button>
            </div>
          </div>
        </div>

        {/* Queue Stats */}
        <div className="queue-stats">
          <div className="stat-card">
            <div className="stat-value">{dlqStatus?.message_count || 0}</div>
            <div className="stat-label">Total Messages</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{dlqStatus?.messages?.length || 0}</div>
            <div className="stat-label">Filtered Messages</div>
          </div>
          <div className={`stat-card ${dlqStatus?.duplicate_count > 0 ? 'has-duplicates' : ''}`}>
            <div className="stat-value">{dlqStatus?.duplicate_message_count || 0}</div>
            <div className="stat-label">Duplicates</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{selectedMessages.size}</div>
            <div className="stat-label">Selected</div>
          </div>
        </div>

        {/* Duplicates Section */}
        {dlqStatus?.duplicate_count > 0 && (
          <div className="duplicates-section">
            <div className="duplicates-header">
              <h3>
                <WarningIcon size={16} />
                {dlqStatus.duplicate_count} URL(s) with Duplicates ({dlqStatus.duplicate_message_count} extra messages)
              </h3>
              <button 
                className="btn-dedupe"
                onClick={handleDedupe}
                disabled={retrying}
              >
                <TrashIcon size={16} />
                Remove Duplicates
              </button>
            </div>
            <div className="duplicates-list">
              {dlqStatus.duplicates?.slice(0, 5).map((dup, idx) => (
                <div key={idx} className="duplicate-item">
                  <span className="dup-count">{dup.count}×</span>
                  <span className="dup-title" title={dup.url}>{dup.title}</span>
                  <span className="dup-range">
                    {formatTimestamp(dup.oldest_error_timestamp)} → {formatTimestamp(dup.newest_error_timestamp)}
                  </span>
                </div>
              ))}
              {dlqStatus.duplicates?.length > 5 && (
                <div className="duplicates-more">
                  ...and {dlqStatus.duplicates.length - 5} more
                </div>
              )}
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="action-buttons">
          <button 
            className="btn-primary"
            onClick={handleRetrySelected}
            disabled={selectedMessages.size === 0 || retrying}
          >
            <PlayIcon size={16} />
            Retry Selected ({selectedMessages.size})
          </button>
          <button 
            className="btn-warning"
            onClick={handleRetryAll}
            disabled={!dlqStatus?.message_count || retrying}
          >
            <PlayIcon size={16} />
            Retry All ({dlqStatus?.message_count || 0})
          </button>
          <button 
            className="btn-danger"
            onClick={handlePurgeDLQ}
            disabled={!dlqStatus?.message_count}
          >
            <TrashIcon size={16} />
            Purge DLQ
          </button>
        </div>

        {/* Messages Table */}
        <div className="messages-section">
          <div className="messages-header">
            <h3>Failed Messages</h3>
            {totalPages > 1 && (
              <div className="pagination-info">
                Page {currentPage} of {totalPages}
              </div>
            )}
          </div>
          
          {loading ? (
            <div className="loading-state">Loading DLQ messages...</div>
          ) : paginatedMessages.length === 0 ? (
            <div className="empty-state">
              <AlertCircleIcon size={48} />
              <p>No messages in the Dead Letter Queue</p>
              {(appliedFilters.error || appliedFilters.batchId || appliedFilters.datasourceId) && (
                <p className="hint">Try adjusting your filters</p>
              )}
            </div>
          ) : (
            <>
              <div className="messages-table-wrapper">
                <table className="messages-table">
                  <thead>
                    <tr>
                      <th className="checkbox-col">
                        <input
                          type="checkbox"
                          checked={selectedMessages.size === paginatedMessages.length && paginatedMessages.length > 0}
                          onChange={handleSelectAll}
                          title="Select all on this page"
                        />
                      </th>
                      <th>Title</th>
                      <th>Type</th>
                      <th>Error</th>
                      <th>Batch ID</th>
                      <th>Failed At</th>
                      <th>URL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedMessages.map((message) => (
                      <tr 
                        key={message.message_id}
                        className={`${selectedMessages.has(message.message_id) ? 'selected' : ''} ${message.is_duplicate ? 'duplicate-row' : ''}`}
                      >
                        <td className="checkbox-col">
                          <input
                            type="checkbox"
                            checked={selectedMessages.has(message.message_id)}
                            onChange={() => handleSelectMessage(message.message_id)}
                          />
                        </td>
                        <td className="title-col">
                          <span className="message-title" title={message.title}>
                            {message.is_duplicate && (
                              <span className="duplicate-badge" title={`${message.duplicate_count} copies of this URL`}>
                                {message.duplicate_count}×
                              </span>
                            )}
                            {message.title}
                          </span>
                        </td>
                        <td>
                          <span className={`type-badge ${message.message_type}`}>
                            {message.message_type || 'resource'}
                          </span>
                        </td>
                        <td className="error-col">
                          <span className="error-text" title={message.error}>
                            {truncateError(message.error)}
                          </span>
                        </td>
                        <td className="batch-col">
                          {message.batch_id ? (
                            <span className="batch-id" title={message.batch_id}>
                              {message.batch_id.substring(0, 8)}...
                            </span>
                          ) : (
                            <span className="no-batch">—</span>
                          )}
                        </td>
                        <td className="timestamp-col">
                          {formatTimestamp(message.error_timestamp)}
                        </td>
                        <td className="url-col">
                          {message.url ? (
                            <a 
                              href={message.url} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              title={message.url}
                            >
                              <LinkIcon size={14} />
                            </a>
                          ) : (
                            <span className="no-url">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              
              {/* Pagination */}
              {totalPages > 1 && (
                <div className="pagination">
                  <button
                    className="pagination-btn"
                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                  >
                    Previous
                  </button>
                  <div className="pagination-numbers">
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      let pageNum;
                      if (totalPages <= 5) {
                        pageNum = i + 1;
                      } else if (currentPage <= 3) {
                        pageNum = i + 1;
                      } else if (currentPage >= totalPages - 2) {
                        pageNum = totalPages - 4 + i;
                      } else {
                        pageNum = currentPage - 2 + i;
                      }
                      return (
                        <button
                          key={pageNum}
                          className={`pagination-num ${currentPage === pageNum ? 'active' : ''}`}
                          onClick={() => setCurrentPage(pageNum)}
                        >
                          {pageNum}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    className="pagination-btn"
                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Batch Interaction Info */}
        <div className="info-section">
          <h3>How DLQ Interacts with Ingestion Batches</h3>
          <div className="info-content">
            <p>
              When a message fails processing and is sent to the DLQ, the batch progress is still updated 
              to allow the batch to complete. This means:
            </p>
            <ul>
              <li>
                <strong>Batch Completion:</strong> A batch can complete even if some items fail. 
                The failed items are tracked in the DLQ with their batch ID.
              </li>
              <li>
                <strong>Retry Behavior:</strong> When you retry DLQ messages, they are re-queued 
                to the main processing queue with a fresh retry counter. They will be processed 
                independently of the original batch.
              </li>
              <li>
                <strong>Filtering by Batch:</strong> Use the Batch ID filter above to see all 
                failed messages from a specific ingestion batch.
              </li>
              <li>
                <strong>Common Failure Reasons:</strong> Timeout during processing, connection 
                errors to external services, validation failures, or duplicate content detection.
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminDLQ;
