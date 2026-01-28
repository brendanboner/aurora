import React, { useState, useEffect, useCallback } from 'react';
import { getCuratorTopicStats, getCuratorStatus, triggerTopicCuration } from '../services/api';
import './Admin.css';
import { RefreshIcon, PlayIcon, CheckIcon, WarningIcon, HourglassIcon } from '../components/icons';

const AdminCuration = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [topicStats, setTopicStats] = useState(null);
  const [curatorStatus, setCuratorStatus] = useState(null);
  const [triggering, setTriggering] = useState(false);
  const [triggerMessage, setTriggerMessage] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [stats, status] = await Promise.all([
        getCuratorTopicStats(),
        getCuratorStatus()
      ]);
      setTopicStats(stats);
      setCuratorStatus(status);
    } catch (err) {
      console.error('Failed to load curator data:', err);
      setError(err.response?.data?.detail || err.message || 'Failed to load curator data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    
    // Auto-refresh every 30 seconds
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  const handleTriggerCuration = async () => {
    setTriggering(true);
    setTriggerMessage(null);
    try {
      const result = await triggerTopicCuration();
      setTriggerMessage({ type: 'success', text: result.message || 'Curation job triggered successfully!' });
      // Refresh status after triggering
      setTimeout(loadData, 1000);
    } catch (err) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to trigger curation';
      setTriggerMessage({ type: 'error', text: errorMsg });
    } finally {
      setTriggering(false);
    }
  };

  const getJobState = (jobName) => {
    if (!curatorStatus?.jobs) return null;
    return curatorStatus.jobs.find(j => j.name === jobName);
  };

  const topicJob = getJobState('topic_organization');
  const isRunning = topicJob?.is_running || false;

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Topic Curation</h1>
        <p>Manage knowledge graph topic hierarchy organization</p>
      </div>

      {error && <div className="admin-error"><WarningIcon size={16} /> {error}</div>}

      {loading && !topicStats ? (
        <div className="spinner" />
      ) : (
        <div className="admin-content">
          {/* Topic Statistics */}
          <div className="kg-stats-row">
            <div className="kg-stat-card">
              <div className="kg-stat-value">{topicStats?.total_topics || 0}</div>
              <div className="kg-stat-label">Total Topics</div>
            </div>
            <div className="kg-stat-card">
              <div className="kg-stat-value" style={{ color: 'var(--success)' }}>
                {topicStats?.organized_topics || 0}
              </div>
              <div className="kg-stat-label"><CheckIcon size={14} /> Organized</div>
            </div>
            <div className="kg-stat-card">
              <div className="kg-stat-value" style={{ color: topicStats?.unorganized_topics > 0 ? 'var(--warning)' : 'var(--success)' }}>
                {topicStats?.unorganized_topics || 0}
              </div>
              <div className="kg-stat-label"><WarningIcon size={14} /> Unorganized</div>
            </div>
            <div className="kg-stat-card">
              <div className="kg-stat-value">{topicStats?.curation_threshold || 0}</div>
              <div className="kg-stat-label">Mode Threshold</div>
            </div>
          </div>

          {/* Curation Mode Info */}
          <div className="curation-mode-card">
            <h3>Current Curation Mode</h3>
            <div className="curation-mode-info">
              <span className={`curation-mode-badge ${topicStats?.curation_mode || 'full'}`}>
                {topicStats?.curation_mode === 'incremental' ? 'INCREMENTAL' : 'FULL'}
              </span>
              <p className="curation-mode-description">
                {topicStats?.curation_mode === 'incremental' ? (
                  <>
                    <strong>Incremental mode:</strong> Only unorganized topics will be processed.
                    Each unorganized topic is clustered with nearby organized topics for context,
                    ensuring proper integration into the existing hierarchy.
                  </>
                ) : (
                  <>
                    <strong>Full mode:</strong> All topics will be processed to build a unified hierarchy.
                    This ensures comprehensive organization but uses more LLM calls.
                  </>
                )}
              </p>
              <p className="curation-mode-threshold">
                Mode switches to incremental when total topics exceed {topicStats?.curation_threshold || 4000}.
              </p>
            </div>
          </div>

          {/* Job Status */}
          <div className="curation-job-card">
            <div className="curation-job-header">
              <h3>Topic Organization Job</h3>
              <button 
                className="btn btn-icon" 
                onClick={loadData} 
                title="Refresh status"
                disabled={loading}
              >
                <RefreshIcon size={16} />
              </button>
            </div>
            
            <div className="curation-job-status">
              <div className="job-status-row">
                <span className="job-status-label">Status:</span>
                <span className={`job-status-value ${isRunning ? 'running' : 'idle'}`}>
                  {isRunning ? (
                    <><span className="spinner-small" /> Running...</>
                  ) : (
                    'Idle'
                  )}
                </span>
              </div>
              <div className="job-status-row">
                <span className="job-status-label">Last Run:</span>
                <span className="job-status-value">
                  <HourglassIcon size={14} /> {formatDate(topicJob?.last_run)}
                </span>
              </div>
              {topicJob?.next_run && (
                <div className="job-status-row">
                  <span className="job-status-label">Next Scheduled:</span>
                  <span className="job-status-value">
                    <HourglassIcon size={14} /> {formatDate(topicJob?.next_run)}
                  </span>
                </div>
              )}
              {topicJob?.last_error && (
                <div className="job-status-row error">
                  <span className="job-status-label">Last Error:</span>
                  <span className="job-status-value error">{topicJob.last_error}</span>
                </div>
              )}
            </div>

            {/* Trigger Button */}
            <div className="curation-trigger-section">
              <button
                className="btn btn-primary btn-lg"
                onClick={handleTriggerCuration}
                disabled={triggering || isRunning}
              >
                {triggering ? (
                  <><span className="spinner-small" /> Triggering...</>
                ) : isRunning ? (
                  <><span className="spinner-small" /> Job Running...</>
                ) : (
                  <><PlayIcon size={18} /> Run Topic Curation</>
                )}
              </button>
              
              {triggerMessage && (
                <div className={`trigger-message ${triggerMessage.type}`}>
                  {triggerMessage.type === 'success' ? <CheckIcon size={16} /> : <WarningIcon size={16} />}
                  {triggerMessage.text}
                </div>
              )}
              
              <p className="curation-trigger-help">
                {topicStats?.unorganized_topics > 0 ? (
                  <>
                    There {topicStats.unorganized_topics === 1 ? 'is' : 'are'} <strong>{topicStats.unorganized_topics}</strong> unorganized 
                    topic{topicStats.unorganized_topics === 1 ? '' : 's'} waiting to be integrated into the hierarchy.
                  </>
                ) : (
                  'All topics are currently organized in the hierarchy.'
                )}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminCuration;
