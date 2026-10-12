import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  getCuratorTopicStats,
  getCuratorStatus,
  triggerTopicCuration,
  getTopicsHierarchy,
} from '../services/api';
import TopicTree from '../components/TopicTree';
import './Admin.css';
import { RefreshIcon, PlayIcon, CheckIcon, WarningIcon, HourglassIcon } from '../components/icons';

const AdminCuration = () => {
  const [statsError, setStatsError] = useState(null);
  const [topicStats, setTopicStats] = useState(null);
  const [curatorStatus, setCuratorStatus] = useState(null);
  const [statsRefreshing, setStatsRefreshing] = useState(false);

  const [hierarchyData, setHierarchyData] = useState(null);
  const [hierarchyLoading, setHierarchyLoading] = useState(false);
  const [hierarchyError, setHierarchyError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const hierarchyLoadedRef = useRef(false);

  const [triggering, setTriggering] = useState(false);
  const [triggerMessage, setTriggerMessage] = useState(null);

  // Load stats without blocking the page — update in place
  const loadStats = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) setStatsRefreshing(true);
    setStatsError(null);
    try {
      const [stats, status] = await Promise.all([
        getCuratorTopicStats(),
        getCuratorStatus(),
      ]);
      setTopicStats(stats);
      setCuratorStatus(status);
    } catch (err) {
      setStatsError(err.response?.data?.detail || err.message || 'Failed to load curator data');
    } finally {
      setStatsRefreshing(false);
    }
  }, []);

  // Load topic hierarchy once — it's large and doesn't change frequently
  const loadHierarchy = useCallback(async () => {
    if (hierarchyLoadedRef.current) return;
    hierarchyLoadedRef.current = true;
    setHierarchyLoading(true);
    setHierarchyError(null);
    try {
      const data = await getTopicsHierarchy();
      setHierarchyData(data);
    } catch (err) {
      setHierarchyError(err.response?.data?.detail || err.message || 'Failed to load topic hierarchy');
      hierarchyLoadedRef.current = false; // allow retry
    } finally {
      setHierarchyLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
    loadHierarchy();
    const interval = setInterval(() => loadStats(), 30000);
    return () => clearInterval(interval);
  }, [loadStats, loadHierarchy]);

  const handleTriggerCuration = async () => {
    setTriggering(true);
    setTriggerMessage(null);
    try {
      const result = await triggerTopicCuration();
      setTriggerMessage({ type: 'success', text: result.message || 'Curation job triggered successfully!' });
      setTimeout(() => loadStats(false), 1500);
    } catch (err) {
      setTriggerMessage({
        type: 'error',
        text: err.response?.data?.detail || err.message || 'Failed to trigger curation',
      });
    } finally {
      setTriggering(false);
    }
  };

  const handleRefreshHierarchy = () => {
    hierarchyLoadedRef.current = false;
    setHierarchyData(null);
    loadHierarchy();
  };

  const getJobState = (jobName) => curatorStatus?.jobs?.find(j => j.name === jobName) || null;
  const topicJob = getJobState('topic_organization');
  const isRunning = topicJob?.is_running || false;

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Never';
    return new Date(dateStr).toLocaleString();
  };

  const topicCount = hierarchyData?.nodes ? Object.keys(hierarchyData.nodes).length : null;

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Topic Curation</h1>
        <p>Browse and manage the knowledge graph topic hierarchy</p>
      </div>

      {/* Stats row — always visible; shows skeleton values until loaded */}
      <div className="kg-stats-row">
        <div className="kg-stat-card">
          <div className="kg-stat-value">{topicStats?.total_topics ?? '—'}</div>
          <div className="kg-stat-label">Total Topics</div>
        </div>
        <div className="kg-stat-card">
          <div className="kg-stat-value" style={{ color: 'var(--success)' }}>
            {topicStats?.organized_topics ?? '—'}
          </div>
          <div className="kg-stat-label"><CheckIcon size={14} /> Organized</div>
        </div>
        <div className="kg-stat-card">
          <div
            className="kg-stat-value"
            style={{ color: topicStats?.unorganized_topics > 0 ? 'var(--warning)' : 'var(--success)' }}
          >
            {topicStats?.unorganized_topics ?? '—'}
          </div>
          <div className="kg-stat-label"><WarningIcon size={14} /> Unorganized</div>
        </div>
        <div className="kg-stat-card">
          <div className="kg-stat-value">
            <span className={`curation-mode-badge ${topicStats?.curation_mode || 'full'}`}>
              {topicStats ? (topicStats.curation_mode === 'incremental' ? 'INC' : 'FULL') : '—'}
            </span>
          </div>
          <div className="kg-stat-label">Curation Mode</div>
        </div>
      </div>

      {statsError && <div className="admin-error"><WarningIcon size={16} /> {statsError}</div>}

      {/* Two-column layout: topic browser | job controls */}
      <div className="curation-layout">

        {/* Topic hierarchy browser */}
        <div className="curation-tree-panel">
          <div className="curation-panel-header">
            <h3>
              Topic Hierarchy
              {topicCount !== null && (
                <span className="curation-topic-count">{topicCount.toLocaleString()} topics</span>
              )}
            </h3>
            <div className="curation-panel-actions">
              <input
                className="curation-search"
                type="search"
                placeholder="Search topics…"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
              />
              <button
                className="btn btn-icon"
                onClick={handleRefreshHierarchy}
                disabled={hierarchyLoading}
                title="Reload hierarchy"
              >
                <RefreshIcon size={16} />
              </button>
            </div>
          </div>

          {hierarchyError && (
            <div className="admin-error" style={{ margin: '0 0 12px' }}>
              <WarningIcon size={16} /> {hierarchyError}
              <button className="btn btn-sm" onClick={handleRefreshHierarchy} style={{ marginLeft: 8 }}>
                Retry
              </button>
            </div>
          )}

          {hierarchyLoading ? (
            <div className="curation-tree-loading">
              <div className="spinner" />
              <span>Loading topic hierarchy…</span>
            </div>
          ) : hierarchyData ? (
            <div className="curation-tree-scroll">
              <TopicTree
                hierarchyData={hierarchyData}
                selectedIds={new Set()}
                onSelectionChange={() => {}}
                isLoading={false}
                searchTerm={searchTerm}
              />
            </div>
          ) : !hierarchyError ? (
            <div className="curation-tree-loading">
              <div className="spinner" />
              <span>Loading topic hierarchy…</span>
            </div>
          ) : null}
        </div>

        {/* Right panel: job controls */}
        <div className="curation-controls-panel">

          {/* Mode info */}
          {topicStats && (
            <div className="curation-mode-card">
              <h3>Curation Mode</h3>
              <div className="curation-mode-info">
                <span className={`curation-mode-badge ${topicStats.curation_mode}`}>
                  {topicStats.curation_mode === 'incremental' ? 'INCREMENTAL' : 'FULL'}
                </span>
                <p className="curation-mode-description">
                  {topicStats.curation_mode === 'incremental' ? (
                    <><strong>Incremental:</strong> Only unorganized topics will be processed.</>
                  ) : (
                    <><strong>Full:</strong> All topics rebuilt into a unified hierarchy.</>
                  )}
                </p>
                <p className="curation-mode-threshold">
                  Switches to incremental above {topicStats.curation_threshold.toLocaleString()} topics.
                </p>
              </div>
            </div>
          )}

          {/* Job status */}
          <div className="curation-job-card">
            <div className="curation-job-header">
              <h3>Topic Organization Job</h3>
              <button
                className="btn btn-icon"
                onClick={() => loadStats(true)}
                title="Refresh status"
                disabled={statsRefreshing}
              >
                <RefreshIcon size={16} />
              </button>
            </div>

            <div className="curation-job-status">
              <div className="job-status-row">
                <span className="job-status-label">Status:</span>
                <span className={`job-status-value ${isRunning ? 'running' : 'idle'}`}>
                  {isRunning ? <><span className="spinner-small" /> Running…</> : 'Idle'}
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
                    <HourglassIcon size={14} /> {formatDate(topicJob.next_run)}
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

            <div className="curation-trigger-section">
              <button
                className="btn btn-primary btn-lg"
                onClick={handleTriggerCuration}
                disabled={triggering || isRunning}
              >
                {triggering ? (
                  <><span className="spinner-small" /> Triggering…</>
                ) : isRunning ? (
                  <><span className="spinner-small" /> Job Running…</>
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
                    <strong>{topicStats.unorganized_topics}</strong> unorganized topic
                    {topicStats.unorganized_topics === 1 ? '' : 's'} waiting to be integrated.
                  </>
                ) : topicStats ? (
                  'All topics are currently organized.'
                ) : null}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminCuration;
