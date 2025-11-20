import React, { useState, useEffect } from 'react';
import './Admin.css';
import { MonitoringIcon, AdminIcon, LinkIcon } from '../components/icons';

const AdminMonitoring = () => {
  const [queueStatus, setQueueStatus] = useState(null);
  const [processingStatus, setProcessingStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let interval;
    const loadMonitoringData = async () => {
      try {
        const response = await fetch('http://localhost:8000/admin/dashboard');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        setQueueStatus(data.queue_status);
        setProcessingStatus(data.processing_status);
        setError(null);
      } catch (err) {
        setError('Failed to load monitoring data');
      }
    };
    loadMonitoringData();
    interval = setInterval(loadMonitoringData, 5000);
    return () => clearInterval(interval);
  }, []);

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
                    {processingStatus?.retriever_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
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
                    {processingStatus?.digester_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
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
          <div className="monitoring-section">
            <h2>Queue Status</h2>
            {queueStatus && (
              <>
                <div className="queue-stats">
                  <div className="queue-stat"><span className="stat-label">Queue:</span><span className="stat-value">{queueStatus.queue_name}</span></div>
                  <div className="queue-stat"><span className="stat-label">Pending:</span><span className="stat-value">{queueStatus.message_count}</span></div>
                  <div className="queue-stat"><span className="stat-label">Consumers:</span><span className="stat-value">{queueStatus.consumer_count}</span></div>
                </div>
                <div className="queue-resources">
                  <h3>Resources in Queue ({queueStatus.resources.length} shown)</h3>
                  {queueStatus.resources.length === 0 ? (
                    <div className="empty-state">Queue is empty</div>
                  ) : (
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
                          {queueStatus.resources.map(resource => (
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
                  )}
                </div>
              </>
            )}
          </div>
          <div className="monitoring-section">
            <h2>Recent Activity</h2>
            <div className="activity-columns">
              <div className="activity-column">
                <h3>Recently Completed</h3>
                {processingStatus?.recent_completed?.length ? (
                  <div className="activity-list">
                    {processingStatus.recent_completed.map((item, i) => (
                      <div key={i} className="activity-item completed">
                        <div className="activity-title">{item.title}</div>
                        <div className="activity-meta"><span>{item.category}</span><span>{new Date(item.updated_at).toLocaleTimeString()}</span></div>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty-state">No recent completions</div>}
              </div>
              <div className="activity-column">
                <h3>Recently Failed</h3>
                {processingStatus?.recent_failed?.length ? (
                  <div className="activity-list">
                    {processingStatus.recent_failed.map((item, i) => (
                      <div key={i} className="activity-item failed">
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
    </div>
  );
};

export default AdminMonitoring;