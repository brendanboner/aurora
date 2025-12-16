import React, { useState, useEffect } from 'react';
import './Admin.css';
import { MonitoringIcon, AdminIcon, LinkIcon } from '../components/icons';

const AdminMonitoring = () => {
  const [queueStatus, setQueueStatus] = useState(null);
  const [processingStatus, setProcessingStatus] = useState(null);
  const [activeBatches, setActiveBatches] = useState([]);
  const [error, setError] = useState(null);
  const [queuePage, setQueuePage] = useState(1);
  const queueItemsPerPage = 5;
  const [selectedDocument, setSelectedDocument] = useState(null);

  useEffect(() => {
    let interval;
    const loadMonitoringData = async () => {
      try {
        const response = await fetch('/api/backend/admin/dashboard');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        setQueueStatus(data.queue_status);
        setProcessingStatus(data.processing_status);
        setActiveBatches(data.active_batches || []);
        setError(null);
      } catch (err) {
        setError('Failed to load monitoring data');
      }
    };
    loadMonitoringData();
    interval = setInterval(loadMonitoringData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleClearCompleted = async () => {
    try {
      const response = await fetch('/api/backend/admin/clear-completed', {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      // Refresh data immediately
      const dashboardResponse = await fetch('/api/backend/admin/dashboard');
      const data = await dashboardResponse.json();
      setQueueStatus(data.queue_status);
      setProcessingStatus(data.processing_status);
      setActiveBatches(data.active_batches || []);
    } catch (err) {
      setError('Failed to clear completed list');
    }
  };

  const handleClearFailed = async () => {
    try {
      const response = await fetch('/api/backend/admin/clear-failed', {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      // Refresh data immediately
      const dashboardResponse = await fetch('/api/backend/admin/dashboard');
      const data = await dashboardResponse.json();
      setQueueStatus(data.queue_status);
      setProcessingStatus(data.processing_status);
      setActiveBatches(data.active_batches || []);
    } catch (err) {
      setError('Failed to clear failed list');
    }
  };

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>System Monitoring</h1>
        <p>Realtime status of processing services, queue and recent activity</p>
      </div>
      {error && <div className="admin-error">{error}</div>}
      <div className="admin-content">
        <div className="monitoring-grid">
          <div className="monitoring-section">
            <h2>Service Status</h2>
            <div className="service-cards">
              <div className={`service-card ${processingStatus?.retriever_active ? 'active' : 'inactive'}`}>
                <div className="service-header">
                  <span className="service-icon"><MonitoringIcon size={18} /></span>
                  <span className="service-name">Retriever</span>
                  <span className={`status-badge ${processingStatus?.retriever_active ? 'active' : 'inactive'}`}>
                    {processingStatus?.retriever_instances ? 
                      `${processingStatus.retriever_instances.active}/${processingStatus.retriever_instances.total}` : 
                      (processingStatus?.retriever_active ? 'Active' : 'Inactive')}
                  </span>
                </div>
                {processingStatus?.retriever_health && (
                  <div className="service-health">
                    <span className="health-label">Health:</span>
                    <span className={`health-status health-${processingStatus.retriever_health.status}`}>
                      {processingStatus.retriever_health.status}
                    </span>
                  </div>
                )}
                {processingStatus?.retriever_current && (
                  <div className="service-current">
                    <div className="current-label">Currently Processing:</div>
                    <div className="current-title">{processingStatus.retriever_current.title}</div>
                    <div className="current-status">{processingStatus.retriever_current.stage}</div>
                  </div>
                )}
              </div>
              <div className={`service-card ${processingStatus?.digester_active ? 'active' : 'inactive'}`}>
                <div className="service-header">
                  <span className="service-icon"><AdminIcon size={18} /></span>
                  <span className="service-name">Digester</span>
                  <span className={`status-badge ${processingStatus?.digester_active ? 'active' : 'inactive'}`}>
                    {processingStatus?.digester_instances ? 
                      `${processingStatus.digester_instances.active}/${processingStatus.digester_instances.total}` : 
                      (processingStatus?.digester_active ? 'Active' : 'Inactive')}
                  </span>
                </div>
                {processingStatus?.digester_health && (
                  <div className="service-health">
                    <span className="health-label">Health:</span>
                    <span className={`health-status health-${processingStatus.digester_health.status}`}>
                      {processingStatus.digester_health.status}
                    </span>
                  </div>
                )}
                {processingStatus?.digester_current && (
                  <div className="service-current">
                    <div className="current-label">Currently Processing:</div>
                    <div className="current-title">{processingStatus.digester_current.title}</div>
                    <div className="current-status">{processingStatus.digester_current.stage}</div>
                  </div>
                )}
              </div>
            </div>
          </div>
          
          {/* Batch Progress Section */}
          {activeBatches && activeBatches.length > 0 && (
            <div className="monitoring-section">
              <h2>Active Ingestion Batches</h2>
              <div className="batch-list">
                {activeBatches.map((batch) => (
                  <div key={batch.batch_id} className="batch-item">
                    <div className="batch-header">
                      <div className="batch-source">{batch.datasource_id}</div>
                      <div className={`batch-status status-${batch.status}`}>{batch.status}</div>
                    </div>
                    <div className="batch-progress-container">
                      <div className="batch-progress-bar">
                        <div 
                          className="batch-progress-fill" 
                          style={{ width: `${batch.progress_percent}%` }}
                        ></div>
                      </div>
                      <div className="batch-progress-text">
                        {batch.items_digested} / {batch.items_scraped} items ({batch.progress_percent}%)
                      </div>
                    </div>
                    <div className="batch-meta">
                      {batch.started_at && <span>Started: {new Date(batch.started_at).toLocaleString()}</span>}
                      {batch.updated_at && <span>Updated: {new Date(batch.updated_at).toLocaleString()}</span>}
                      {!batch.started_at && !batch.updated_at && <span>No timestamps available</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          <div className="monitoring-section">
            <h2>Processing Queue</h2>
            {queueStatus && (
              <>
                <div className="queue-stats">
                  <div className="queue-stat"><span className="stat-label">Queue:</span><span className="stat-value">{queueStatus.queue_name}</span></div>
                  <div className="queue-stat"><span className="stat-label">Total Messages:</span><span className="stat-value">{queueStatus.message_count}</span></div>
                  <div className="queue-stat"><span className="stat-label">Unique Docs:</span><span className="stat-value">{queueStatus.resources.length}</span></div>
                  <div className="queue-stat"><span className="stat-label">Consumers:</span><span className="stat-value">{queueStatus.consumer_count}</span></div>
                </div>
                
                {/* Current Processing Section */}
                {(processingStatus?.retriever_current || processingStatus?.digester_current) && (
                  <div className="current-processing-section">
                    <h3>Currently Processing</h3>
                    <div className="current-processing-items">
                      {processingStatus?.retriever_current && (
                        <div className="current-processing-item">
                          <div className="processing-service">Retriever</div>
                          <div className="processing-title">{processingStatus.retriever_current.title}</div>
                          <div className="processing-stage">{processingStatus.retriever_current.stage}</div>
                        </div>
                      )}
                      {processingStatus?.digester_current && (
                        <div className="current-processing-item">
                          <div className="processing-service">Digester</div>
                          <div className="processing-title">{processingStatus.digester_current.title}</div>
                          <div className="processing-stage">{processingStatus.digester_current.stage}</div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
                
                {/* Queue Contents */}
                <div className="queue-resources">
                  <h3>Pending Documents ({queueStatus.resources.length} unique)</h3>
                  {queueStatus.resources.length === 0 ? (
                    <div className="empty-state">Queue is empty</div>
                  ) : (
                    <>
                      <div className="resources-table">
                        <table>
                          <thead>
                            <tr>
                              <th>#</th>
                              <th>Title</th>
                              <th>Category</th>
                              <th>URL</th>
                              <th>Date</th>
                            </tr>
                          </thead>
                          <tbody>
                            {queueStatus.resources
                              .slice((queuePage - 1) * queueItemsPerPage, queuePage * queueItemsPerPage)
                              .map(resource => (
                                <tr key={resource.position}>
                                  <td>{resource.position}</td>
                                  <td className="resource-title">{resource.title}</td>
                                  <td><span className="category-badge">{resource.category}</span></td>
                                  <td className="resource-url"><a href={resource.url} target="_blank" rel="noopener noreferrer"><LinkIcon size={14} /></a></td>
                                  <td>{resource.publish_date || 'N/A'}</td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                      {queueStatus.resources.length > queueItemsPerPage && (
                        <div className="pagination">
                          <button 
                            onClick={() => setQueuePage(p => Math.max(1, p - 1))}
                            disabled={queuePage === 1}
                            className="pagination-btn"
                          >
                            Previous
                          </button>
                          <span className="pagination-info">
                            Page {queuePage} of {Math.ceil(queueStatus.resources.length / queueItemsPerPage)}
                          </span>
                          <button 
                            onClick={() => setQueuePage(p => Math.min(Math.ceil(queueStatus.resources.length / queueItemsPerPage), p + 1))}
                            disabled={queuePage >= Math.ceil(queueStatus.resources.length / queueItemsPerPage)}
                            className="pagination-btn"
                          >
                            Next
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </>
            )}
          </div>
          <div className="monitoring-section">
            <h2>Recent Activity</h2>
            <div className="activity-columns">
              <div className="activity-column">
                <div className="activity-header">
                  <h3>Recently Completed</h3>
                  {processingStatus?.recent_completed?.length > 0 && (
                    <button className="clear-btn" onClick={handleClearCompleted}>Clear</button>
                  )}
                </div>
                {processingStatus?.recent_completed?.length ? (
                  <div className="activity-list">
                    {processingStatus.recent_completed.map((item, i) => (
                      <div 
                        key={i} 
                        className="activity-item completed clickable"
                        onClick={() => setSelectedDocument(item)}
                      >
                        <div className="activity-title">{item.title}</div>
                        <div className="activity-meta"><span>{item.category}</span><span>{new Date(item.updated_at).toLocaleTimeString()}</span></div>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty-state">No recent completions</div>}
              </div>
              <div className="activity-column">
                <div className="activity-header">
                  <h3>Recently Failed</h3>
                  {processingStatus?.recent_failed?.length > 0 && (
                    <button className="clear-btn" onClick={handleClearFailed}>Clear</button>
                  )}
                </div>
                {processingStatus?.recent_failed?.length ? (
                  <div className="activity-list">
                    {processingStatus.recent_failed.map((item, i) => (
                      <div 
                        key={i} 
                        className="activity-item failed clickable"
                        onClick={() => setSelectedDocument(item)}
                      >
                        <div className="activity-title">{item.title}</div>
                        <div className="activity-meta"><span>{item.category}</span><span>{new Date(item.updated_at).toLocaleTimeString()}</span></div>
                        {item.error && <div className="activity-error">{item.error}</div>}
                      </div>
                    ))}
                  </div>
                ) : <div className="empty-state">No recent failures</div>}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Document Details Modal */}
      {selectedDocument && (
        <div className="modal-overlay" onClick={() => setSelectedDocument(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Document Details</h2>
              <button className="modal-close" onClick={() => setSelectedDocument(null)}>×</button>
            </div>
            <div className="modal-body">
              <div className="detail-section">
                <h3>Basic Information</h3>
                <div className="detail-row">
                  <span className="detail-label">Title:</span>
                  <span className="detail-value">{selectedDocument.title}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">URL:</span>
                  <span className="detail-value">
                    <a href={selectedDocument.url} target="_blank" rel="noopener noreferrer">
                      {selectedDocument.url}
                    </a>
                  </span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Category:</span>
                  <span className="detail-value">
                    <span className="category-badge">{selectedDocument.category}</span>
                  </span>
                </div>
                {selectedDocument.datasource_id && (
                  <div className="detail-row">
                    <span className="detail-label">Source:</span>
                    <span className="detail-value">{selectedDocument.datasource_id}</span>
                  </div>
                )}
                {selectedDocument.publish_date && (
                  <div className="detail-row">
                    <span className="detail-label">Publish Date:</span>
                    <span className="detail-value">{selectedDocument.publish_date}</span>
                  </div>
                )}
                {selectedDocument.uploaded_by && (
                  <div className="detail-row">
                    <span className="detail-label">Uploaded By:</span>
                    <span className="detail-value">{selectedDocument.uploaded_by}</span>
                  </div>
                )}
              </div>

              {selectedDocument.metadata?.nodes?.resource && (
                <div className="detail-section">
                  <h3>Document Summary</h3>
                  <div className="detail-row">
                    <span className="detail-label">Summary:</span>
                    <span className="detail-value">{selectedDocument.metadata.nodes.resource.summary}</span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-label">Importance:</span>
                    <span className="detail-value">
                      {(selectedDocument.metadata.nodes.resource.importance * 100).toFixed(0)}%
                      {selectedDocument.metadata.nodes.resource.importance_explanation && 
                        ` - ${selectedDocument.metadata.nodes.resource.importance_explanation}`}
                    </span>
                  </div>
                  {selectedDocument.metadata.nodes.resource.extreme_impact && (
                    <div className="detail-row">
                      <span className="detail-label">Extreme Impact:</span>
                      <span className="detail-value">{selectedDocument.metadata.nodes.resource.extreme_impact}</span>
                    </div>
                  )}
                </div>
              )}

              {selectedDocument.metadata?.nodes?.topics && selectedDocument.metadata.nodes.topics.length > 0 && (
                <div className="detail-section">
                  <h3>Topics ({selectedDocument.metadata.nodes.topics.length})</h3>
                  <div className="topics-list">
                    {selectedDocument.metadata.nodes.topics.map((topic, i) => (
                      <div key={i} className="topic-item">
                        <div className="topic-name">{topic.name}</div>
                        <div className="topic-meta">
                          <span className="topic-classification">{topic.classification}</span>
                          {topic.identifier && <span className="topic-identifier">{topic.identifier}</span>}
                          {topic.issuer && <span className="topic-issuer">Issuer: {topic.issuer}</span>}
                        </div>
                        {topic.aliases && topic.aliases.length > 0 && (
                          <div className="topic-aliases">
                            Aliases: {topic.aliases.join(', ')}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedDocument.metadata?.nodes?.organizations && selectedDocument.metadata.nodes.organizations.length > 0 && (
                <div className="detail-section">
                  <h3>Organizations ({selectedDocument.metadata.nodes.organizations.length})</h3>
                  <div className="entities-list">
                    {selectedDocument.metadata.nodes.organizations.map((org, i) => (
                      <div key={i} className="entity-item">
                        <div className="entity-name">{org.name}</div>
                        {org.org_type && <div className="entity-meta">Type: {org.org_type}</div>}
                        {org.homepage_url && (
                          <div className="entity-meta">
                            <a href={org.homepage_url} target="_blank" rel="noopener noreferrer">{org.homepage_url}</a>
                          </div>
                        )}
                        {org.aliases && org.aliases.length > 0 && (
                          <div className="entity-meta">Aliases: {org.aliases.join(', ')}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedDocument.metadata?.nodes?.people && selectedDocument.metadata.nodes.people.length > 0 && (
                <div className="detail-section">
                  <h3>People ({selectedDocument.metadata.nodes.people.length})</h3>
                  <div className="entities-list">
                    {selectedDocument.metadata.nodes.people.map((person, i) => (
                      <div key={i} className="entity-item">
                        <div className="entity-name">{person.name}</div>
                        {person.email && <div className="entity-meta">{person.email}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {selectedDocument.metadata?.relationships && selectedDocument.metadata.relationships.length > 0 && (
                <div className="detail-section">
                  <h3>Relationships ({selectedDocument.metadata.relationships.length})</h3>
                  <div className="relationships-list">
                    {selectedDocument.metadata.relationships.slice(0, 10).map((rel, i) => (
                      <div key={i} className="relationship-item">
                        <div className="relationship-type">{rel.relationship_type}</div>
                        <div className="relationship-details">
                          {rel.source_identifier} → {rel.target_identifier}
                        </div>
                        {rel.confidence && (
                          <div className="relationship-meta">
                            Confidence: {(rel.confidence * 100).toFixed(0)}%
                          </div>
                        )}
                        {rel.evidence && (
                          <div className="relationship-evidence">"{rel.evidence}"</div>
                        )}
                      </div>
                    ))}
                    {selectedDocument.metadata.relationships.length > 10 && (
                      <div className="relationship-more">
                        + {selectedDocument.metadata.relationships.length - 10} more relationships
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="detail-section">
                <h3>Processing Status</h3>
                <div className="detail-row">
                  <span className="detail-label">Status:</span>
                  <span className="detail-value">
                    <span className={`status-badge ${selectedDocument.status}`}>{selectedDocument.status}</span>
                  </span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Stage:</span>
                  <span className="detail-value">{selectedDocument.stage}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Started:</span>
                  <span className="detail-value">{new Date(selectedDocument.started_at).toLocaleString()}</span>
                </div>
                <div className="detail-row">
                  <span className="detail-label">Updated:</span>
                  <span className="detail-value">{new Date(selectedDocument.updated_at).toLocaleString()}</span>
                </div>
                {selectedDocument.error && (
                  <div className="detail-row">
                    <span className="detail-label">Error:</span>
                    <span className="detail-value error-text">{selectedDocument.error}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminMonitoring;