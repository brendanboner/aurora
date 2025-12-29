import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './News.css';
import { useAuth } from '../contexts/AuthContext';
import apiClient from '../api/client';
import { NewsIcon, RefreshIcon, CalendarIcon, BookIcon, BuildingIcon, StarIcon } from '../components/icons';

const News = ({ backendStatus }) => {
  const { user } = useAuth();
  const [newsContent, setNewsContent] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [timeRange, setTimeRange] = useState('1month');
  const [expandedSections, setExpandedSections] = useState({});

  const timeRangeOptions = [
    { value: '1week', label: '1 Week', description: 'Past week + upcoming week' },
    { value: '1month', label: '1 Month', description: 'Past month + next 2 months' },
    { value: '6months', label: '6 Months', description: 'Past 6 months + next 6 months' },
    { value: '1year', label: '1 Year', description: 'Past year + next year' }
  ];

  const loadNews = async (forceRefresh = false) => {
    if (!user) {
      setError('Please log in to view news.');
      return;
    }

    if (backendStatus !== 'connected') {
      setError('Backend is not connected. Please check your connection.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await apiClient.post('/backend/news', {
        user_id: user.id,
        time_range: timeRange,
        force_refresh: forceRefresh
      });

      const data = response.data;
      setNewsContent(data);
      
      // Expand all sections by default
      const expanded = {};
      data.sections?.forEach((section, idx) => {
        expanded[idx] = true;
      });
      setExpandedSections(expanded);
      
    } catch (err) {
      console.error('News loading error:', err);
      setError(err.message || 'Failed to load news content');
    } finally {
      setIsLoading(false);
    }
  };

  // Load news on mount and when user/timeRange changes
  useEffect(() => {
    loadNews();
  }, [user, timeRange]);

  const handleRefresh = () => {
    loadNews(true);
  };

  const toggleSection = (index) => {
    setExpandedSections(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  const formatDate = (dateString) => {
    try {
      const date = new Date(dateString);
      return date.toLocaleString();
    } catch {
      return dateString;
    }
  };

  const getImportanceColor = (importance) => {
    if (importance >= 0.8) return '#ff4444';
    if (importance >= 0.6) return '#ff9944';
    if (importance >= 0.4) return '#ffdd44';
    return '#44dd44';
  };

  if (!user) {
    return (
      <div className="news-container">
        <div className="news-header">
          <div className="header-title">
            <NewsIcon size={32} />
            <h1>News & Events</h1>
          </div>
        </div>
        <div className="news-empty-state">
          <p>Please log in to view curated news and events.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="news-container">
      <div className="news-header">
        <div className="header-title">
          <NewsIcon size={32} />
          <h1>News & Events</h1>
        </div>
        <div className="header-controls">
          <select 
            value={timeRange} 
            onChange={(e) => setTimeRange(e.target.value)}
            className="time-range-selector"
            disabled={isLoading}
          >
            {timeRangeOptions.map(option => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button 
            onClick={handleRefresh} 
            className="refresh-button"
            disabled={isLoading}
            title="Refresh news"
          >
            <RefreshIcon size={20} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="news-error">
          <p>{error}</p>
        </div>
      )}

      {isLoading && (
        <div className="news-loading">
          <div className="loading-spinner"></div>
          <p>Generating curated news content...</p>
        </div>
      )}

      {!isLoading && newsContent && (
        <div className="news-content">
          {/* Headline and Summary */}
          <div className="news-hero">
            <h2 className="news-headline">{newsContent.headline}</h2>
            <div className="news-meta">
              <span className="meta-item">
                <CalendarIcon size={16} />
                <span>{timeRangeOptions.find(o => o.value === timeRange)?.description}</span>
              </span>
              <span className="meta-item">
                <BookIcon size={16} />
                <span>{newsContent.document_count} documents analyzed</span>
              </span>
              <span className="meta-item">
                <span className="meta-label">Updated:</span>
                <span>{formatDate(newsContent.generated_at)}</span>
              </span>
            </div>
            <div className="news-summary">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {newsContent.summary}
              </ReactMarkdown>
            </div>
          </div>

          {/* Key Highlights */}
          {newsContent.highlights && newsContent.highlights.length > 0 && (
            <div className="news-highlights">
              <h3>Key Highlights</h3>
              <ul className="highlights-list">
                {newsContent.highlights.map((highlight, idx) => (
                  <li key={idx}>
                    <StarIcon size={16} color="#ffd700" />
                    <span>{highlight}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* News Sections */}
          {newsContent.sections && newsContent.sections.length > 0 && (
            <div className="news-sections">
              {newsContent.sections.map((section, idx) => (
                <div key={idx} className="news-section">
                  <div 
                    className="section-header"
                    onClick={() => toggleSection(idx)}
                  >
                    <h3>{section.title}</h3>
                    <button className="toggle-btn">
                      {expandedSections[idx] ? '−' : '+'}
                    </button>
                  </div>
                  
                  {expandedSections[idx] && (
                    <div className="section-content">
                      <div className="section-text">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {section.content}
                        </ReactMarkdown>
                      </div>
                      
                      {section.documents && section.documents.length > 0 && (
                        <div className="section-documents">
                          <h4>Related Documents</h4>
                          <div className="documents-list">
                            {section.documents.map((doc, docIdx) => (
                              <div key={docIdx} className="document-card">
                                <div className="document-header">
                                  <a 
                                    href={doc.url} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="document-title"
                                  >
                                    {doc.title}
                                  </a>
                                  {doc.importance && (
                                    <span 
                                      className="importance-badge"
                                      style={{ 
                                        backgroundColor: getImportanceColor(doc.importance),
                                        color: 'var(--background)'
                                      }}
                                    >
                                      {(doc.importance * 100).toFixed(0)}%
                                    </span>
                                  )}
                                </div>
                                <div className="document-meta">
                                  {doc.category && (
                                    <span className="category-badge">{doc.category}</span>
                                  )}
                                </div>
                                {doc.summary && (
                                  <p className="document-summary">{doc.summary}</p>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Empty State */}
          {(!newsContent.sections || newsContent.sections.length === 0) && (
            <div className="news-empty-state">
              <p>{newsContent.summary}</p>
              <p>Try adjusting your interests in your profile or expanding the time range.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default News;
