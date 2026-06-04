import React, { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookIcon, CalendarIcon, BuildingIcon, SearchIcon, HourglassIcon, SparkleIcon, BarChartIcon, ThumbsUpIcon, ThumbsDownIcon, LightbulbIcon, ToolIcon } from './icons';
import ChevronLeftIcon from './icons/ChevronLeftIcon';
import ChevronRightIcon from './icons/ChevronRightIcon';
import ChevronDownIcon from './icons/ChevronDownIcon';
import Icon from './Icon';
import './QueryResultDisplay.css';

/**
 * Display modes for query results
 * - retrieval: Shows only the retrieved documents
 * - answer: Shows the LLM answer with citations and referenced documents
 * - debug: Shows technical details (admin only)
 */
const DISPLAY_MODES = {
  RETRIEVAL: 'retrieval',
  ANSWER: 'answer',
  DEBUG: 'debug',
};

const safeText = (value, fallback = '') => (typeof value === 'string' ? value : fallback);

/**
 * Transform match reason text to be more user-friendly
 */
const formatMatchReason = (reason) => {
  // Replace "Keyword match" with "Entity match"
  let formattedReason = reason
    .replace(/Keyword match/gi, 'Entity match')
    .replace(/keyword/gi, 'entity');
  
  // Remove common emojis and replace with descriptive text
  formattedReason = formattedReason
    .replace(/🔍/g, 'Search match: ')
    .replace(/📄/g, 'Document type: ')
    .replace(/🏢/g, 'Organization: ')
    .replace(/📅/g, 'Date relevance: ')
    .replace(/📊/g, 'Data match: ')
    .replace(/📈/g, 'Trending topic: ')
    .replace(/💡/g, 'Key insight: ')
    .replace(/⚠️/g, 'Note: ')
    .replace(/✨/g, 'Enhanced: ')
    .replace(/⭐/g, 'Important: ')
    .replace(/★/g, 'Featured: ')
    .replace(/🌟/g, 'Highlighted: ')
    .replace(/🔧/g, 'Technical: ')
    // Remove any remaining emojis (Unicode emoji range)
    .replace(/[\u{1F600}-\u{1F64F}]|[\u{1F300}-\u{1F5FF}]|[\u{1F680}-\u{1F6FF}]|[\u{1F1E0}-\u{1F1FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/gu, '')
    // Clean up any double spaces or leading/trailing spaces
    .replace(/\s+/g, ' ')
    .trim();
  
  return formattedReason;
};

/**
 * Get datasource display name - prefer source (friendly name) over datasource_id
 */
const getDatasourceName = (doc) => {
  // source field contains the friendly name from the graph
  // Check for non-empty string (not just truthy)
  if (doc.source && doc.source.trim()) return doc.source;
  // fallback to datasource_id if source not available
  if (doc.datasource_id && doc.datasource_id.trim()) return doc.datasource_id;
  return null;
};

/**
 * Extract YouTube video ID from URL
 */
const extractYouTubeVideoId = (url) => {
  if (!url) return null;
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/,
    /youtube\.com\/embed\/([a-zA-Z0-9_-]{11})/,
    /youtube\.com\/v\/([a-zA-Z0-9_-]{11})/,
  ];
  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
};

/**
 * Check if document is a YouTube video
 */
const isYouTubeVideo = (doc) => {
  return doc.url && (doc.url.includes('youtube.com') || doc.url.includes('youtu.be'));
};

/**
 * Show follow-up suggestion chips whenever the backend produced any.
 * Backend already filters via should_show_suggestions() (low confidence or
 * sparse documents), so trusting `message.suggestions` is sufficient here.
 */
const shouldShowSuggestions = (message) => {
  return Array.isArray(message.suggestions) && message.suggestions.length > 0;
};

/**
 * QueryResultDisplay - Unified component for displaying Oracle query results
 * 
 * Supports three views:
 * 1. Retrieval Mode: Just the found documents with relevance scores
 * 2. Answer Mode: Answer with citations + combined document references
 * 3. Debug Mode: Technical details (admin only) - KG context, metadata, suggestions
 * 
 * Props:
 * - message: The message object containing query results
 * - isAdmin: Whether to show admin-only features
 * - onEnhance: Callback to trigger enhance with document content
 * - onToggleEnhanced: Callback to toggle between original and enhanced answer
 * - isEnhancing: Whether enhance is currently in progress
 * - onFeedback: Callback for user feedback (queryId, feedbackType) => void
 */
const QueryResultDisplay = ({ message, isAdmin = false, onEnhance, onToggleEnhanced, isEnhancing = false, onDisplayModeChange, onFeedback, onSuggestionClick }) => {
  // Initialize display mode from message or default based on content
  const getInitialDisplayMode = () => {
    // If message has a saved display mode, use it
    if (message.displayMode && Object.values(DISPLAY_MODES).includes(message.displayMode)) {
      // If saved mode is ANSWER but there's no answer, fall back to RETRIEVAL
      if (message.displayMode === DISPLAY_MODES.ANSWER && (!message.content || message.content === 'Here are the relevant documents:')) {
        return DISPLAY_MODES.RETRIEVAL;
      }
      return message.displayMode;
    }
    // Default: show answer if available, otherwise retrieval
    return message.content && message.content !== 'Here are the relevant documents:' 
      ? DISPLAY_MODES.ANSWER 
      : DISPLAY_MODES.RETRIEVAL;
  };

  const [displayMode, setDisplayModeState] = useState(getInitialDisplayMode);
  const [feedbackGiven, setFeedbackGiven] = useState(message.feedbackGiven || null); // 'helpful' | 'not_helpful' | null
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false);
  // Open by default when the answer has citations — trust signal for legal/security/PM users.
  const [referencesOpen, setReferencesOpen] = useState(
    Array.isArray(message.citations) && message.citations.length > 0
  );
  
  // Wrapper to update both local state and persist to parent
  const setDisplayMode = useCallback((mode) => {
    setDisplayModeState(mode);
    if (onDisplayModeChange) {
      onDisplayModeChange(mode);
    }
  }, [onDisplayModeChange]);

  // Handle feedback submission
  const handleFeedback = async (feedbackType) => {
    if (!message.queryId || !onFeedback || feedbackGiven) return;
    
    setFeedbackSubmitting(true);
    try {
      await onFeedback(message.queryId, feedbackType);
      setFeedbackGiven(feedbackType);
    } catch (err) {
      console.error('Failed to submit feedback:', err);
    } finally {
      setFeedbackSubmitting(false);
    }
  };

  const [currentDocIndex, setCurrentDocIndex] = useState(0);
  const answerViewRef = useRef(null);
  const prevShowingEnhanced = useRef(message.showingEnhanced);
  const prevIsEnhanced = useRef(message.isEnhanced);

  // Scroll to top of answer when toggling between enhanced/original
  useEffect(() => {
    if (prevShowingEnhanced.current !== message.showingEnhanced && answerViewRef.current) {
      try {
        answerViewRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (err) {
        console.warn('Failed to scroll enhanced answer into view:', err);
      }
    }
    prevShowingEnhanced.current = message.showingEnhanced;
  }, [message.showingEnhanced]);

  // Switch to Answer tab when enhancement completes
  useEffect(() => {
    if (!prevIsEnhanced.current && message.isEnhanced) {
      setDisplayMode(DISPLAY_MODES.ANSWER);
    }
    prevIsEnhanced.current = message.isEnhanced;
  }, [message.isEnhanced, setDisplayMode]);

  const hasAnswer = message.content && message.content !== 'Here are the relevant documents:';
  const hasDocuments = message.documents && message.documents.length > 0;
  const hasCitations = message.citations && message.citations.length > 0;
  // Per-doc lookup so citation hover popovers can show publish_date alongside
  // title/excerpt (citation payload itself only has url/title/excerpt).
  const docByUrl = new Map((message.documents || []).map((d) => [d.url, d]));
  // Citation popover payload: index → {url, title, excerpt, publish_date}
  const citationMetaMap = new Map(
    (message.citations || []).map((citation) => [
      String(citation.index),
      {
        url: citation.document_url,
        title: citation.title,
        excerpt: citation.excerpt,
        publish_date: docByUrl.get(citation.document_url)?.publish_date || null,
      },
    ])
  );

  // Format date helper
  const formatDate = (dateStr) => {
    if (!dateStr) return 'Unknown date';
    try {
      const date = new Date(dateStr);
      if (isNaN(date.getTime())) return dateStr;
      return date.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'long', 
        day: 'numeric' 
      });
    } catch (e) {
      return dateStr;
    }
  };

  // Combine citations with documents for answer mode
  const getCombinedReferences = () => {
    if (!hasDocuments) return [];
    
    const docMap = new Map();
    
    // Add all documents
    message.documents.forEach(doc => {
      docMap.set(doc.url, { ...doc, isCited: false, citationIndex: null });
    });
    
    // Mark cited documents
    if (hasCitations) {
      message.citations.forEach(citation => {
        if (docMap.has(citation.document_url)) {
          const doc = docMap.get(citation.document_url);
          doc.isCited = true;
          doc.citationIndex = citation.index;
          doc.excerpt = citation.excerpt;
        }
      });
    }
    
    // Sort: cited documents first, then by relevance
    return Array.from(docMap.values()).sort((a, b) => {
      if (a.isCited && !b.isCited) return -1;
      if (!a.isCited && b.isCited) return 1;
      return (b.relevance_score || 0) - (a.relevance_score || 0);
    });
  };

  const renderCitationFragments = (value) => {
    if (typeof value !== 'string') return value;

    // Match both [1] and [Doc 1] citation formats
    return value.split(/(\[Doc \d+\]|\[\d+\])/g).map((part, idx) => {
      const match = part.match(/^\[(?:Doc )?(\d+)\]$/);
      if (!match) return part;

      const meta = citationMetaMap.get(match[1]);
      if (!meta?.url) return <span key={idx} className="citation-ref">[{match[1]}]</span>;

      const excerptSnippet = typeof meta.excerpt === 'string' && meta.excerpt.length > 180
        ? meta.excerpt.slice(0, 177).trimEnd() + '…'
        : meta.excerpt;

      return (
        <span key={idx} className="citation-popover-wrap">
          <a
            className="citation-ref citation-link"
            href={meta.url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={meta.title ? `Open citation: ${meta.title}` : 'Open referenced document'}
          >
            [{match[1]}]
          </a>
          <span className="citation-popover" role="tooltip">
            {meta.title && (
              <span className="citation-popover-title">{meta.title}</span>
            )}
            {meta.publish_date && (
              <span className="citation-popover-date">{formatDate(meta.publish_date)}</span>
            )}
            {excerptSnippet && (
              <span className="citation-popover-excerpt">“{excerptSnippet}”</span>
            )}
            <span className="citation-popover-link">Click to open document →</span>
          </span>
        </span>
      );
    });
  };

  const renderModeSelector = () => {
    if (!hasDocuments) return null;
    // Fast pipeline: no tab bar — enhance/toggle move into the stats row
    if (message.pipeline === 'fast') return null;

    return (
      <div className="display-mode-selector">
        <div className="mode-tabs">
          {hasAnswer && (
            <button
              className={`mode-tab ${displayMode === DISPLAY_MODES.ANSWER ? 'active' : ''}`}
              onClick={() => setDisplayMode(DISPLAY_MODES.ANSWER)}
            >
              Answer
            </button>
          )}
          <button
            className={`mode-tab ${displayMode === DISPLAY_MODES.RETRIEVAL ? 'active' : ''}`}
            onClick={() => setDisplayMode(DISPLAY_MODES.RETRIEVAL)}
          >
            Documents
          </button>
          {isAdmin && (
            <button
              className={`mode-tab ${displayMode === DISPLAY_MODES.DEBUG ? 'active' : ''}`}
              onClick={() => setDisplayMode(DISPLAY_MODES.DEBUG)}
            >
              <Icon Component={ToolIcon} size={14} /> Debug
            </button>
          )}
        </div>
        {/* Enhance button for baseline mode — shown next to tabs */}
        {(displayMode === DISPLAY_MODES.ANSWER || !hasAnswer) && (() => {
          const canEnhance = onEnhance && hasDocuments && !message.isEnhanced;
          const hasOriginalContent = message.originalAnswer?.content && message.originalAnswer.content !== 'Here are the relevant documents:';
          const canToggle = message.isEnhanced && onToggleEnhanced && (hasOriginalContent && message.enhancedAnswer);
          return (
            <>
              {canEnhance && (
                <button className="enhance-button" onClick={onEnhance} disabled={isEnhancing}
                  title={hasAnswer ? "Get a more detailed answer using document content" : "Generate an answer from these documents"}>
                  {isEnhancing
                    ? <><Icon Component={HourglassIcon} size={14} /> Enhancing...</>
                    : <><Icon Component={SparkleIcon} size={14} /> {hasAnswer ? 'Enhance' : 'Generate Answer'}</>}
                </button>
              )}
              {canToggle && (
                <button
                  className={`enhance-toggle-button ${message.showingEnhanced ? 'showing-enhanced' : 'showing-original'}`}
                  onClick={onToggleEnhanced}
                  title={message.showingEnhanced ? 'Switch to graph summary answer' : 'Switch to enhanced answer'}>
                  {message.showingEnhanced
                    ? <><Icon Component={BarChartIcon} size={14} /> Show Graph Summary</>
                    : <><Icon Component={SparkleIcon} size={14} /> Show Enhanced</>}
                </button>
              )}
            </>
          );
        })()}
      </div>
    );
  };

  const renderRetrievalMode = () => {
    if (!hasDocuments) {
      return (
        <div className="no-documents">
          <Icon Component={SearchIcon} size={24} />
          <p>No documents found for this query.</p>
        </div>
      );
    }

    const doc = message.documents[currentDocIndex];
    const totalDocs = message.documents.length;

    return (
      <>
        <div className="retrieval-view">
          <div className="documents-header">
            <strong>
              <Icon Component={BookIcon} size={14} /> Found Documents ({totalDocs})
            </strong>
            {totalDocs > 1 && (
              <div className="document-navigation">
                <button
                  className="nav-button"
                  onClick={() => setCurrentDocIndex(Math.max(0, currentDocIndex - 1))}
                  disabled={currentDocIndex === 0}
                  aria-label="Previous document"
                >
                  <ChevronLeftIcon size={16} />
                </button>
                <span className="doc-counter">{currentDocIndex + 1} / {totalDocs}</span>
                <button
                  className="nav-button"
                  onClick={() => setCurrentDocIndex(Math.min(totalDocs - 1, currentDocIndex + 1))}
                  disabled={currentDocIndex === totalDocs - 1}
                  aria-label="Next document"
                >
                  <ChevronRightIcon size={16} />
                </button>
              </div>
            )}
          </div>

          <div className="document-card-detailed">
            <div className="doc-header">
              <div className="doc-title">
                {doc.url ? (
                  <a href={doc.url} target="_blank" rel="noopener noreferrer">
                    {doc.title || 'Untitled Document'}
                  </a>
                ) : (
                  doc.title || 'Untitled Document'
                )}
              </div>
              <div className="relevance-badge">
                {Math.round((doc.relevance_score || 0) * 100)}% match
              </div>
            </div>

            {isYouTubeVideo(doc) && (() => {
              const videoId = extractYouTubeVideoId(doc.url);
              if (videoId) {
                return (
                  <div className="video-thumbnail">
                    <a href={doc.url} target="_blank" rel="noopener noreferrer">
                      <img 
                        src={`https://img.youtube.com/vi/${videoId}/mqdefault.jpg`}
                        alt={doc.title || 'YouTube Video'}
                        style={{ width: '100%', maxWidth: '320px', borderRadius: '8px', marginTop: '12px' }}
                      />
                    </a>
                  </div>
                );
              }
            })()}

            <div className="doc-meta">
              {getDatasourceName(doc) && (
                <span className="doc-datasource">
                  <Icon Component={BuildingIcon} size={12} /> {getDatasourceName(doc)}
                </span>
              )}
              {doc.publish_date && (
                <span className="doc-date">
                  <Icon Component={CalendarIcon} size={12} /> {formatDate(doc.publish_date)}
                </span>
              )}
            </div>

            {doc.summary && (
              <div className="doc-summary">{doc.summary}</div>
            )}

            {doc.match_reasons && doc.match_reasons.length > 0 && (
              <div className="match-reasons">
                <strong>Why this document:</strong>
                <ul>
                  {doc.match_reasons.map((reason, i) => (
                    <li key={i}>{formatMatchReason(reason)}</li>
                  ))}
                </ul>
              </div>
            )}

            {(doc.topics?.length > 0 || doc.organisations?.length > 0) && (
              <div className="doc-tags">
                {doc.topics?.slice(0, 5).map((topic, j) => (
                  <span key={`t-${j}`} className="badge badge-topic">{topic}</span>
                ))}
                {doc.organisations?.slice(0, 3).map((org, j) => (
                  <span key={`o-${j}`} className="badge badge-org">{org}</span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Query Suggestions — clickable follow-up chips */}
        {shouldShowSuggestions(message) && (
          <div className="query-suggestions-section">
            <div className="suggestions-header">
              <Icon Component={LightbulbIcon} size={16} className="suggestions-icon" />
              <strong>Try a follow-up</strong>
            </div>
            <div className="suggestions-list-inline">
              {message.suggestions.map((suggestion, i) => (
                <button
                  key={i}
                  type="button"
                  className="suggestion-item suggestion-clickable"
                  onClick={() => onSuggestionClick && onSuggestionClick(suggestion.suggestion)}
                  disabled={!onSuggestionClick}
                  title={suggestion.reason}
                >
                  <span className="suggestion-query">{suggestion.suggestion}</span>
                  {suggestion.reason && (
                    <span className="suggestion-reason">{suggestion.reason}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
      </>
    );
  };

  const renderAnswerMode = () => {
    const isShowingEnhanced = message.showingEnhanced;
    
    // Build a map of document URLs to datasource names for lookup
    const docDatasourceMap = new Map();
    if (message.documents) {
      message.documents.forEach(doc => {
        // Store the friendly source name, falling back to datasource_id
        docDatasourceMap.set(doc.url, doc.source || doc.datasource_id);
      });
    }
    
    // For enhanced answers, use citations directly from enhance response
    // For original answers, use the combined references approach
    let referencesToShow = [];
    
    if (isShowingEnhanced && message.citations?.length > 0) {
      // Enhanced mode: citations come from enhance response and already
      // only include documents whose chunks were actually used
      referencesToShow = message.citations.map(citation => ({
        url: citation.document_url,
        title: citation.title,
        excerpt: citation.excerpt,
        citationIndex: citation.index,
        source: docDatasourceMap.get(citation.document_url),
        isCited: true,
      }));
    } else {
      // Original mode: use combined references
      const combinedRefs = getCombinedReferences();
      referencesToShow = combinedRefs.filter(d => d.isCited);
    }

    // Format time in seconds
    const formatTimeSeconds = (ms) => {
      if (!ms) return null;
      return (ms / 1000).toFixed(1) + 's';
    };

    // Get stats for display
    const getStatsDisplay = () => {
      if (isShowingEnhanced && message.enhanceMetadata) {
        // Enhanced answer stats
        const meta = message.enhanceMetadata;
        const parts = [];
        if (meta.documents_fetched) parts.push(`${meta.documents_fetched} docs`);
        if (meta.chunks_used) parts.push(`${meta.chunks_used} chunks`);
        if (meta.processing_time_ms) parts.push(formatTimeSeconds(meta.processing_time_ms));
        return parts.join(' · ');
      } else {
        // Graph answer stats
        const parts = [];
        if (message.documents?.length > 0) parts.push(`${message.documents.length} docs`);
        if (message.metadata?.processing_time_ms) parts.push(formatTimeSeconds(message.metadata.processing_time_ms));
        return parts.join(' · ');
      }
    };

    const statsDisplay = getStatsDisplay();

    const combinedReferences = isShowingEnhanced
      ? referencesToShow
      : getCombinedReferences();

    return (
      <div className="answer-view" ref={answerViewRef}>
        {/* Confidence and Stats Row - Above Answer */}
        {hasAnswer && (((message.confidenceScore !== null && message.confidenceScore !== undefined) || statsDisplay || message.personalizationApplied)) && (
          <div className="answer-stats-row">
            {/* Confidence on the left */}
            {message.confidenceScore !== null && message.confidenceScore !== undefined && (
              <div className="confidence-indicator">
                <span className="confidence-label">
                  {message.pipeline === 'fast' ? 'Confidence:' : 'Answer confidence:'}
                </span>
                <div className="confidence-bar">
                  <div
                    className="confidence-fill"
                    style={{ width: `${message.confidenceScore * 100}%` }}
                  />
                </div>
                <span className="confidence-value">{Math.round(message.confidenceScore * 100)}%</span>
              </div>
            )}

            {/* Stats, personalization, and enhance controls on the right */}
            <div className="answer-stats-right">
              {message.personalizationApplied && (
                <span className="personalization-tag" title="Answer tailored to your preferences">
                  Personalized
                </span>
              )}
              {statsDisplay && (
                <div className="answer-stats">
                  <Icon Component={isShowingEnhanced ? SparkleIcon : BarChartIcon} size={14} /> {statsDisplay}
                </div>
              )}
              {/* Enhance / toggle buttons — shown inline in stats row for fast pipeline */}
              {message.pipeline === 'fast' && (() => {
                const canEnhance = onEnhance && hasDocuments && !message.isEnhanced;
                const hasOriginalContent = message.originalAnswer?.content && message.originalAnswer.content !== 'Here are the relevant documents:';
                const canToggle = message.isEnhanced && onToggleEnhanced && (hasOriginalContent && message.enhancedAnswer);
                return (
                  <>
                    {canEnhance && (
                      <button
                        className="enhance-btn-inline"
                        onClick={onEnhance}
                        disabled={isEnhancing}
                        title="Get a more detailed answer with additional sources"
                      >
                        {isEnhancing
                          ? <><Icon Component={HourglassIcon} size={13} /> Enhancing…</>
                          : <><Icon Component={SparkleIcon} size={13} /> Enhance</>}
                      </button>
                    )}
                    {canToggle && (
                      <button
                        className={`enhance-btn-inline toggle ${message.showingEnhanced ? 'active' : ''}`}
                        onClick={onToggleEnhanced}
                        title={message.showingEnhanced ? 'Switch to graph summary' : 'Switch to enhanced answer'}
                      >
                        {message.showingEnhanced
                          ? <><Icon Component={BarChartIcon} size={13} /> Summary</>
                          : <><Icon Component={SparkleIcon} size={13} /> Enhanced</>}
                      </button>
                    )}
                  </>
                );
              })()}
            </div>
          </div>
        )}

        {/* Always-visible answer mode toggle — shown whenever both original and enhanced are available.
             This is independent of the stats row so it can't be hidden by missing confidence/stats. */}
        {message.isEnhanced && message.originalAnswer && message.enhancedAnswer && onToggleEnhanced && (
          <div className="answer-mode-banner">
            {isShowingEnhanced ? (
              <>
                <span className="answer-mode-label enhanced-label">✦ Enhanced</span>
                <button
                  type="button"
                  className="answer-mode-toggle-btn"
                  onClick={onToggleEnhanced}
                  title="Switch to graph summary answer"
                >
                  ← Back to summary
                </button>
              </>
            ) : (
              <>
                <span className="answer-mode-label summary-label">Graph summary</span>
                <button
                  type="button"
                  className="answer-mode-toggle-btn enhanced"
                  onClick={onToggleEnhanced}
                  title="Switch to enhanced answer"
                >
                  View enhanced →
                </button>
              </>
            )}
          </div>
        )}

        {/* The Answer */}
        {hasAnswer && (
          <div className={`answer-content ${isShowingEnhanced ? 'enhanced' : ''}`}>
            <ReactMarkdown 
              remarkPlugins={[remarkGfm]}
              components={{
                // Custom paragraph rendering with citation styling
                p: ({children}) => {
                  const styledChildren = React.Children.map(children, (child) => {
                    return typeof child === 'string' ? renderCitationFragments(child) : child;
                  });
                  return <p>{styledChildren}</p>;
                },
                li: ({children}) => {
                  const styledChildren = React.Children.map(children, (child) => {
                    return typeof child === 'string' ? renderCitationFragments(child) : child;
                  });
                  return <li>{styledChildren}</li>;
                }
              }}
            >
              {message.content}
            </ReactMarkdown>
            {message.isStreaming && (
              <span className="streaming-cursor" aria-label="Generating response…" />
            )}
          </div>
        )}

        {/* References Section */}
        {combinedReferences.length > 0 && (
          <div className="references-section">
            <button
              type="button"
              className="references-toggle"
              onClick={() => setReferencesOpen((prev) => !prev)}
              aria-expanded={referencesOpen}
            >
              <span className="references-toggle-left">
                <span className={`references-chevron${referencesOpen ? ' open' : ''}`}>
                  <ChevronDownIcon size={14} />
                </span>
                <strong>Reference Documents</strong>
              </span>
              <span className="references-toggle-meta">
                {combinedReferences.length} item{combinedReferences.length === 1 ? '' : 's'}
              </span>
            </button>

            {referencesOpen && (
              <div className="references-scroll-list">
                {combinedReferences.map((doc, i) => (
                  <div key={`${doc.url || doc.title}-${i}`} className={`reference-item ${doc.isCited ? 'cited' : 'additional'}`}>
                    <span className="citation-marker">
                      {doc.isCited && doc.citationIndex ? `[${doc.citationIndex}]` : 'More'}
                    </span>
                    <div className="reference-content">
                      <div className="reference-title-row">
                        <a href={doc.url} target="_blank" rel="noopener noreferrer">
                          {doc.title || 'Untitled'}
                        </a>
                        {doc.publish_date && (
                          <span className="reference-publish-date">
                            {formatDate(doc.publish_date)}
                          </span>
                        )}
                        {getDatasourceName(doc) && (
                          <span className="reference-datasource">
                            {getDatasourceName(doc)}
                          </span>
                        )}
                      </div>
                      {isYouTubeVideo(doc) && (() => {
                        const videoId = extractYouTubeVideoId(doc.url);
                        if (videoId) {
                          return (
                            <div className="video-thumbnail-small">
                              <a href={doc.url} target="_blank" rel="noopener noreferrer">
                                <img 
                                  src={`https://img.youtube.com/vi/${videoId}/default.jpg`}
                                  alt={doc.title || 'YouTube Video'}
                                  style={{ width: '120px', borderRadius: '4px', marginTop: '8px' }}
                                />
                              </a>
                            </div>
                          );
                        }
                        return null;
                      })()}
                      {doc.excerpt && (
                        <div className="reference-excerpt">"{doc.excerpt}"</div>
                      )}
                      {!doc.excerpt && safeText(doc.summary) && (
                        <div className="reference-summary">
                          {safeText(doc.summary).slice(0, 150)}...
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Feedback Buttons - Bottom Right */}
        {hasAnswer && message.queryId && onFeedback && (
          <div className="feedback-section">
            {feedbackGiven && (
              <span className="feedback-thanks">Thanks for your feedback!</span>
            )}
            <span className="feedback-label">Was this helpful?</span>
            <div className="feedback-buttons">
              <button
                className={`feedback-btn ${feedbackGiven === 'helpful' ? 'active positive' : ''}`}
                onClick={() => handleFeedback('helpful')}
                disabled={feedbackSubmitting || feedbackGiven !== null}
                title="Yes, this was helpful"
              >
                <Icon Component={ThumbsUpIcon} size={16} />
              </button>
              <button
                className={`feedback-btn ${feedbackGiven === 'not_helpful' ? 'active negative' : ''}`}
                onClick={() => handleFeedback('not_helpful')}
                disabled={feedbackSubmitting || feedbackGiven !== null}
                title="No, this wasn't helpful"
              >
                <Icon Component={ThumbsDownIcon} size={16} />
              </button>
            </div>
          </div>
        )}

        {/* Query Suggestions — clickable follow-up chips */}
        {shouldShowSuggestions(message) && (
          <div className="query-suggestions-section">
            <div className="suggestions-header">
              <Icon Component={LightbulbIcon} size={16} className="suggestions-icon" />
              <strong>Try a follow-up</strong>
            </div>
            <div className="suggestions-list-inline">
              {message.suggestions.map((suggestion, i) => (
                <button
                  key={i}
                  type="button"
                  className="suggestion-item suggestion-clickable"
                  onClick={() => onSuggestionClick && onSuggestionClick(suggestion.suggestion)}
                  disabled={!onSuggestionClick}
                  title={suggestion.reason}
                >
                  <span className="suggestion-query">{suggestion.suggestion}</span>
                  {suggestion.reason && (
                    <span className="suggestion-reason">{suggestion.reason}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderDebugMode = () => {
    return (
      <div className="debug-view">
        {/* Query Metadata */}
        {message.metadata && (
          <div className="admin-section">
            <div className="admin-section-title">Query Metadata</div>
            <div className="admin-grid">
              <div className="admin-item">
                <span className="admin-label">Intent:</span>
                <span className="admin-value">
                  {message.metadata.intent} 
                  ({Math.round(message.metadata.intent_confidence * 100)}%)
                </span>
              </div>
              <div className="admin-item">
                <span className="admin-label">Strategies:</span>
                <span className="admin-value">
                  {message.metadata.strategies_used?.join(', ') || 'N/A'}
                </span>
              </div>
              <div className="admin-item">
                <span className="admin-label">Candidates:</span>
                <span className="admin-value">{message.metadata.total_candidates}</span>
              </div>
              <div className="admin-item">
                <span className="admin-label">Processing:</span>
                <span className="admin-value">{message.metadata.processing_time_ms}ms</span>
              </div>
              {message.metadata.llm_tokens_used && (
                <div className="admin-item">
                  <span className="admin-label">Tokens:</span>
                  <span className="admin-value">{message.metadata.llm_tokens_used}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Knowledge Graph Context */}
        {message.graphContext && (
          <div className="admin-section">
            <div className="admin-section-title">Knowledge Graph Context</div>
            
            {message.graphContext.central_topics?.length > 0 && (
              <div className="admin-subsection">
                <span className="admin-label">Central Topics:</span>
                <div className="admin-tags">
                  {message.graphContext.central_topics.map((topic, i) => (
                    <span key={i} className="badge badge-topic">{topic}</span>
                  ))}
                </div>
              </div>
            )}

            {message.graphContext.key_organizations?.length > 0 && (
              <div className="admin-subsection">
                <span className="admin-label">Key Organizations:</span>
                <div className="admin-tags">
                  {message.graphContext.key_organizations.map((org, i) => (
                    <span key={i} className="badge badge-org">{org}</span>
                  ))}
                </div>
              </div>
            )}

            {message.graphContext.key_people?.length > 0 && (
              <div className="admin-subsection">
                <span className="admin-label">Key People:</span>
                <div className="admin-tags">
                  {message.graphContext.key_people.map((person, i) => (
                    <span key={i} className="badge badge-person">{person}</span>
                  ))}
                </div>
              </div>
            )}

            {message.graphContext.related_entities?.length > 0 && (
              <div className="admin-subsection">
                <span className="admin-label">Related Entities:</span>
                <div className="admin-tags">
                  {message.graphContext.related_entities.map((entity, i) => (
                    <span 
                      key={i} 
                      className={`badge badge-${entity.type}`}
                      title={`Relevance: ${Math.round(entity.relevance * 100)}%`}
                    >
                      {entity.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {message.graphContext.temporal_patterns && (
              <div className="admin-subsection">
                <span className="admin-label">Temporal Patterns:</span>
                <p className="admin-text">{message.graphContext.temporal_patterns}</p>
              </div>
            )}
          </div>
        )}

        {/* Query Suggestions */}
        {message.suggestions && message.suggestions.length > 0 && (
          <div className="admin-section">
            <div className="admin-section-title">Query Suggestions</div>
            <ul className="suggestions-list">
              {message.suggestions.map((suggestion, i) => (
                <li key={i}>
                  <span className="suggestion-text">"{suggestion.suggestion}"</span>
                  <span className="suggestion-reason">— {suggestion.reason}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Document Details for Admin */}
        {hasDocuments && (
          <div className="admin-section">
            <div className="admin-section-title">All Documents ({message.documents.length})</div>
            <div className="admin-documents-table">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Title</th>
                    <th>Datasource</th>
                    <th>Score</th>
                    <th>Topics</th>
                    <th>Match Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {message.documents.map((doc, i) => (
                    <tr key={i}>
                      <td>{i + 1}</td>
                      <td>
                        <a href={doc.url} target="_blank" rel="noopener noreferrer">
                          {doc.title?.substring(0, 40) || 'Untitled'}...
                        </a>
                      </td>
                      <td>{getDatasourceName(doc) || '-'}</td>
                      <td>{Math.round((doc.relevance_score || 0) * 100)}%</td>
                      <td>{doc.topics?.slice(0, 2).join(', ') || '-'}</td>
                      <td>{doc.match_reasons?.slice(0, 2).map(r => formatMatchReason(r)).join('; ') || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Confidence Breakdown */}
        {message.confidenceScore !== null && message.confidenceScore !== undefined && (
          <div className="admin-section">
            <div className="admin-section-title">Confidence Details</div>
            <div className="admin-item">
              <span className="admin-label">Overall Score:</span>
              <span className="admin-value">{Math.round(message.confidenceScore * 100)}%</span>
            </div>
            <div className="confidence-interpretation">
              {message.confidenceScore >= 0.8 && (
                <span className="confidence-high">High confidence - well-supported answer</span>
              )}
              {message.confidenceScore >= 0.5 && message.confidenceScore < 0.8 && (
                <span className="confidence-medium">Medium confidence - some supporting evidence</span>
              )}
              {message.confidenceScore < 0.5 && (
                <span className="confidence-low">Low confidence - limited evidence</span>
              )}
            </div>
          </div>
        )}
      </div>
    );
  };

  // Main render - for non-answer messages (user messages, errors), just render content
  if (message.role === 'user' || message.isError || (!hasAnswer && !hasDocuments)) {
    return null; // Let parent component handle these
  }

  return (
    <div className="query-result-display">
      {renderModeSelector()}
      
      <div className="display-content">
        {displayMode === DISPLAY_MODES.RETRIEVAL && renderRetrievalMode()}
        {displayMode === DISPLAY_MODES.ANSWER && renderAnswerMode()}
        {displayMode === DISPLAY_MODES.DEBUG && renderDebugMode()}
      </div>
    </div>
  );
};

export default QueryResultDisplay;
