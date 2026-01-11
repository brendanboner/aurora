import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { 
  getOracleQueryHistory,
  getOracleQueryDetail,
  getOracleQueryStats 
} from '../services/api';
import './Admin.css';
import { ChatIcon, CalendarIcon, RefreshIcon } from '../components/icons';

// Intent badge colors
const INTENT_COLORS = {
  'factual_qa': { bg: '#e3f2fd', color: '#1565c0' },
  'topic_discovery': { bg: '#f3e5f5', color: '#7b1fa2' },
  'comparison': { bg: '#fff3e0', color: '#e65100' },
  'troubleshooting': { bg: '#ffebee', color: '#c62828' },
  'how_to': { bg: '#e8f5e9', color: '#2e7d32' },
  'definition': { bg: '#e0f7fa', color: '#00838f' },
  'unknown': { bg: '#f5f5f5', color: '#616161' },
};

// Confidence level colors
const CONFIDENCE_COLORS = {
  'high': { bg: '#e8f5e9', color: '#2e7d32' },
  'medium': { bg: '#fff3e0', color: '#f57c00' },
  'low': { bg: '#ffebee', color: '#c62828' },
};

const AdminChatSessions = () => {
  // Oracle queries state
  const [oracleQueries, setOracleQueries] = useState([]);
  const [selectedQuery, setSelectedQuery] = useState(null);
  const [queryDetail, setQueryDetail] = useState(null);
  const [oracleStats, setOracleStats] = useState(null);
  const [queryFilters, setQueryFilters] = useState({
    days: 7,
    intent: '',
    hasFeedback: '',
  });
  
  // Common state
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    loadOracleQueries();
    loadOracleStats();
  }, []);

  // === Oracle Queries Functions ===
  const loadOracleQueries = async () => {
    setLoading(true);
    setError(null);
    try {
      const options = {
        days: queryFilters.days,
        limit: 100,
      };
      if (queryFilters.intent) options.intent = queryFilters.intent;
      if (queryFilters.hasFeedback !== '') options.hasFeedback = queryFilters.hasFeedback === 'true';
      
      const data = await getOracleQueryHistory(options);
      setOracleQueries(data.items || []);
    } catch (err) {
      // If query history is not available, show empty state
      if (err.response?.status === 400) {
        setOracleQueries([]);
        setError('Query history storage is not enabled');
      } else {
        setError(err.response?.data?.detail || err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  const loadOracleStats = async () => {
    try {
      const stats = await getOracleQueryStats(queryFilters.days);
      setOracleStats(stats);
    } catch (err) {
      // Stats not available - not critical
      setOracleStats(null);
    }
  };

  const loadQueryDetail = async (queryId) => {
    setDetailLoading(true);
    setQueryDetail(null);
    try {
      const data = await getOracleQueryDetail(queryId);
      setQueryDetail(data);
      setSelectedQuery(queryId);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load query details');
    } finally {
      setDetailLoading(false);
    }
  };

  const handleFilterChange = (key, value) => {
    setQueryFilters(prev => ({ ...prev, [key]: value }));
  };

  useEffect(() => {
    loadOracleQueries();
    loadOracleStats();
  }, [queryFilters]);

  const filteredQueries = oracleQueries.filter(query => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return query.question?.toLowerCase().includes(term);
  });

  const formatDate = (dateString) => {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  const formatLatency = (ms) => {
    if (!ms) return 'N/A';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(2)}s`;
  };

  const getIntentStyle = (intent) => {
    return INTENT_COLORS[intent] || INTENT_COLORS['unknown'];
  };

  const getConfidenceStyle = (level) => {
    return CONFIDENCE_COLORS[level] || CONFIDENCE_COLORS['low'];
  };

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Oracle Query Analytics</h1>
        <p>View and analyze Oracle query performance and history</p>
      </div>

      {error && <div className="admin-error">{error}</div>}

      {/* Oracle Stats */}
      {oracleStats && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Total Queries</div>
            <div className="stat-value">{oracleStats.total_queries || 0}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Avg Latency</div>
            <div className="stat-value">{formatLatency(oracleStats.performance?.avg_latency_ms)}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Avg Confidence</div>
                <div className="stat-value">
                  {oracleStats.performance?.avg_confidence 
                    ? `${(oracleStats.performance.avg_confidence * 100).toFixed(0)}%` 
                    : 'N/A'}
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Positive Feedback</div>
                <div className="stat-value feedback-positive">
                  {oracleStats.feedback?.positive || 0}
                  {oracleStats.feedback?.total > 0 && (
                    <span className="stat-subvalue">
                      / {oracleStats.feedback.total} total
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Filters */}
          <div className="section-actions oracle-filters">
            <div className="filter-group">
              <label>Time Range:</label>
              <select 
                value={queryFilters.days} 
                onChange={(e) => handleFilterChange('days', parseInt(e.target.value))}
              >
                <option value={1}>Last 24 hours</option>
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
              </select>
            </div>
            <div className="filter-group">
              <label>Intent:</label>
              <select 
                value={queryFilters.intent} 
                onChange={(e) => handleFilterChange('intent', e.target.value)}
              >
                <option value="">All Intents</option>
                <option value="factual_qa">Factual Q&A</option>
                <option value="topic_discovery">Topic Discovery</option>
                <option value="comparison">Comparison</option>
                <option value="troubleshooting">Troubleshooting</option>
                <option value="how_to">How To</option>
                <option value="definition">Definition</option>
              </select>
            </div>
            <div className="filter-group">
              <label>Feedback:</label>
              <select 
                value={queryFilters.hasFeedback} 
                onChange={(e) => handleFilterChange('hasFeedback', e.target.value)}
              >
                <option value="">All</option>
                <option value="true">Has Feedback</option>
                <option value="false">No Feedback</option>
              </select>
            </div>
            <button className="btn btn-primary" onClick={() => { loadOracleQueries(); loadOracleStats(); }}>
              <RefreshIcon size={16} /> Refresh
            </button>
          </div>

          {loading && <div className="spinner" />}

          {!loading && (
            <div className="chat-sessions-layout">
              {/* Left Panel - Query List */}
              <div className="conversations-panel">
                <div className="panel-header">
                  <h2>Queries ({filteredQueries.length})</h2>
                  <input
                    type="text"
                    placeholder="Search queries..."
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    className="search-input"
                  />
                </div>

                <div className="conversations-list">
                  {filteredQueries.length === 0 ? (
                    <div className="empty-state">
                      <ChatIcon size={48} />
                      <p>No queries found</p>
                      <p className="empty-hint">Try adjusting the filters or time range</p>
                    </div>
                  ) : (
                    filteredQueries.map(query => (
                      <div
                        key={query.query_id}
                        className={`conversation-item query-item ${selectedQuery === query.query_id ? 'selected' : ''}`}
                        onClick={() => loadQueryDetail(query.query_id)}
                      >
                        <div className="query-question">
                          {query.question?.substring(0, 100)}{query.question?.length > 100 ? '...' : ''}
                        </div>
                        <div className="query-badges">
                          {query.intent && (
                            <span 
                              className="badge intent-badge"
                              style={{ backgroundColor: getIntentStyle(query.intent).bg, color: getIntentStyle(query.intent).color }}
                            >
                              {query.intent.replace('_', ' ')}
                            </span>
                          )}
                          {query.confidence_level && (
                            <span 
                              className="badge confidence-badge"
                              style={{ backgroundColor: getConfidenceStyle(query.confidence_level).bg, color: getConfidenceStyle(query.confidence_level).color }}
                            >
                              {query.confidence_level}
                            </span>
                          )}
                          {query.feedback_type && (
                            <span className={`badge feedback-badge ${query.feedback_type}`}>
                              {query.feedback_type === 'helpful' ? '👍' : '👎'}
                            </span>
                          )}
                          {query.cache_hit && (
                            <span className="badge cache-badge">cached</span>
                          )}
                        </div>
                        <div className="query-meta">
                          <span>{formatLatency(query.processing_time_ms)}</span>
                          <span>•</span>
                          <span>{query.documents_count || 0} docs</span>
                          <span>•</span>
                          <span>{formatDate(query.created_at)}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Right Panel - Query Detail */}
              <div className="conversation-detail-panel">
                {!selectedQuery && (
                  <div className="empty-state">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <circle cx="12" cy="12" r="10"/>
                      <path d="M12 6v6l4 2"/>
                    </svg>
                    <p>Select a query to view details</p>
                  </div>
                )}

                {detailLoading && <div className="spinner" />}

                {selectedQuery && queryDetail && !detailLoading && (
                  <div className="conversation-detail query-detail">
                    <div className="detail-header">
                      <h2>Query Details</h2>
                      <div className="detail-meta">
                        <span className="meta-item">
                          <CalendarIcon size={14} />
                          {formatDate(queryDetail.created_at)}
                        </span>
                        <span className="meta-item">
                          ID: {queryDetail.query_id?.substring(0, 12)}...
                        </span>
                      </div>
                    </div>

                    <div className="query-detail-content">
                      {/* Question */}
                      <div className="detail-section">
                        <h3>Question</h3>
                        <div className="question-text">{queryDetail.question}</div>
                      </div>

                      {/* Metrics Grid */}
                      <div className="detail-section">
                        <h3>Performance Metrics</h3>
                        <div className="metrics-grid">
                          <div className="metric">
                            <span className="metric-label">Intent</span>
                            <span 
                              className="metric-value badge"
                              style={{ backgroundColor: getIntentStyle(queryDetail.intent).bg, color: getIntentStyle(queryDetail.intent).color }}
                            >
                              {queryDetail.intent?.replace('_', ' ') || 'N/A'}
                            </span>
                          </div>
                          <div className="metric">
                            <span className="metric-label">Confidence</span>
                            <span 
                              className="metric-value badge"
                              style={{ backgroundColor: getConfidenceStyle(queryDetail.confidence_level).bg, color: getConfidenceStyle(queryDetail.confidence_level).color }}
                            >
                              {queryDetail.confidence_score 
                                ? `${(queryDetail.confidence_score * 100).toFixed(0)}%` 
                                : 'N/A'}
                            </span>
                          </div>
                          <div className="metric">
                            <span className="metric-label">Latency</span>
                            <span className="metric-value">{formatLatency(queryDetail.processing_time_ms)}</span>
                          </div>
                          <div className="metric">
                            <span className="metric-label">Documents</span>
                            <span className="metric-value">{queryDetail.documents_count || 0}</span>
                          </div>
                          <div className="metric">
                            <span className="metric-label">Mode</span>
                            <span className="metric-value">{queryDetail.effective_mode || queryDetail.mode}</span>
                          </div>
                          <div className="metric">
                            <span className="metric-label">Cache Hit</span>
                            <span className="metric-value">{queryDetail.cache_hit ? 'Yes' : 'No'}</span>
                          </div>
                          {queryDetail.llm_tokens_used && (
                            <div className="metric">
                              <span className="metric-label">Tokens Used</span>
                              <span className="metric-value">{queryDetail.llm_tokens_used}</span>
                            </div>
                          )}
                          {queryDetail.strategies_used && (
                            <div className="metric">
                              <span className="metric-label">Strategies</span>
                              <span className="metric-value">
                                {queryDetail.strategies_used.join(', ')}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Answer */}
                      {queryDetail.answer && (
                        <div className="detail-section">
                          <h3>Generated Answer</h3>
                          <div className="answer-text">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {queryDetail.answer}
                            </ReactMarkdown>
                          </div>
                        </div>
                      )}

                      {/* Documents */}
                      {queryDetail.documents && queryDetail.documents.length > 0 && (
                        <div className="detail-section">
                          <h3>Retrieved Documents ({queryDetail.documents.length})</h3>
                          <div className="documents-list">
                            {queryDetail.documents.map((doc, idx) => (
                              <div key={idx} className="document-item">
                                <div className="doc-title">{doc.title || 'Untitled'}</div>
                                <div className="doc-meta">
                                  <span>Relevance: {doc.relevance_score?.toFixed(2) || 'N/A'}</span>
                                  {doc.datasource_id && <span>Source: {doc.datasource_id}</span>}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Feedback */}
                      {queryDetail.feedback_type && (
                        <div className="detail-section">
                          <h3>User Feedback</h3>
                          <div className={`feedback-display ${queryDetail.feedback_type}`}>
                            <span className="feedback-icon">
                              {queryDetail.feedback_type === 'helpful' ? '👍' : '👎'}
                            </span>
                            <span className="feedback-type">{queryDetail.feedback_type}</span>
                            {queryDetail.feedback_comment && (
                              <p className="feedback-comment">"{queryDetail.feedback_comment}"</p>
                            )}
                            {queryDetail.feedback_at && (
                              <span className="feedback-time">
                                Submitted: {formatDate(queryDetail.feedback_at)}
                              </span>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Error */}
                      {queryDetail.error && (
                        <div className="detail-section error-section">
                          <h3>Error</h3>
                          <div className="error-message">{queryDetail.error_message}</div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
    </div>
  );
};

export default AdminChatSessions;
