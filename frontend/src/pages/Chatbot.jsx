import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sendOracleQuery, analyzeQuery, sendEnhanceQuery, getDatasources, submitOracleFeedback, getOracleSettings } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { ProfileIcon, ChatIcon, WarningIcon, HourglassIcon, SendIcon, SearchIcon, BuildingIcon, CalendarIcon, DocumentIcon, LightbulbIcon, ChevronDownIcon } from '../components/icons';
import Icon from '../components/Icon';
import QueryResultDisplay from '../components/QueryResultDisplay';
import DatasourceMention from '../components/DatasourceMention';
import './Chatbot.css';

const MAX_STORED_MESSAGES = 24;
const MAX_STORED_DOCUMENTS = 5;
const MAX_STORED_CITATIONS = 8;
const MAX_STORED_TEXT_LENGTH = 600;

const Chatbot = ({ backendStatus }) => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [queryMode, setQueryModeState] = useState(() => {
    const saved = localStorage.getItem('queryMode');
    return saved && ['answer', 'auto'].includes(saved) ? saved : 'answer';
  });
  const [personalizeMode, setPersonalizeModeState] = useState(() => {
    const saved = localStorage.getItem('personalizeMode');
    return saved && ['off', 'on', 'auto'].includes(saved) ? saved : 'auto';
  });
  const [pipelineMode, setPipelineModeState] = useState(() => {
    const saved = localStorage.getItem('pipelineMode');
    return saved && ['system', 'fast', 'baseline'].includes(saved) ? saved : 'system';
  });
  const [querySuggestion, setQuerySuggestion] = useState(null); // For pre-query suggestions
  const [pendingQuery, setPendingQuery] = useState(null); // Original query while showing suggestion
  const [pendingDatasourceIds, setPendingDatasourceIds] = useState([]); // Datasources for pending query
  const [youtubeConfirmation, setYoutubeConfirmation] = useState(null); // For duplicate video confirmation
  const [enhancingMessageIndex, setEnhancingMessageIndex] = useState(null); // Track which message is being enhanced
  const [datasources, setDatasources] = useState([]); // Available datasources for @mention
  const [showMentionDropdown, setShowMentionDropdown] = useState(false);
  const [mentionSearchText, setMentionSearchText] = useState('');
  const [selectedDatasources, setSelectedDatasources] = useState([]); // Selected @mentions
  const [fastPipelineEnabled, setFastPipelineEnabled] = useState(false); // Track if fast pipeline is enabled
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const messageRefs = useRef({}); // Refs for each message element
  const inputRef = useRef(null); // Ref for textarea input
  const previousMessageCountRef = useRef(0);
  const isPinnedToBottomRef = useRef(true);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const [hasUnreadContentBelow, setHasUnreadContentBelow] = useState(false);
  const scrollThreshold = 48;

  const truncateText = useCallback((value, maxLength = MAX_STORED_TEXT_LENGTH) => {
    if (typeof value !== 'string') {
      return '';
    }
    return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value;
  }, []);

  const compactMessageForStorage = useCallback((message) => ({
    role: message.role,
    content: truncateText(message.content, 2000),
    timestamp: message.timestamp,
    isError: Boolean(message.isError),
    isWelcomeMessage: Boolean(message.isWelcomeMessage),
    userEmail: message.userEmail || null,
    queryId: message.queryId || null,
    responseMode: message.responseMode || null,
    personalizationApplied: Boolean(message.personalizationApplied),
    pipeline: message.pipeline || null,
    confidenceScore: typeof message.confidenceScore === 'number' ? message.confidenceScore : null,
    originalQuery: message.originalQuery || null,
    isEnhanced: Boolean(message.isEnhanced),
    showingEnhanced: Boolean(message.showingEnhanced),
    documents: Array.isArray(message.documents)
      ? message.documents.slice(0, MAX_STORED_DOCUMENTS).map((doc) => ({
          title: truncateText(String(doc?.title || 'Untitled'), 240),
          url: typeof doc?.url === 'string' ? doc.url : '',
          publish_date: typeof doc?.publish_date === 'string' ? doc.publish_date : null,
          summary: truncateText(typeof doc?.summary === 'string' ? doc.summary : '', 280),
          topics: Array.isArray(doc?.topics) ? doc.topics.slice(0, 5).map((topic) => String(topic)) : [],
          organisations: Array.isArray(doc?.organisations) ? doc.organisations.slice(0, 3).map((org) => String(org)) : [],
          relevance_score: typeof doc?.relevance_score === 'number' ? doc.relevance_score : null,
          source: typeof doc?.source === 'string' ? doc.source : null,
          datasource_id: typeof doc?.datasource_id === 'string' ? doc.datasource_id : null,
        }))
      : [],
    citations: Array.isArray(message.citations)
      ? message.citations.slice(0, MAX_STORED_CITATIONS).map((citation) => ({
          index: citation?.index ?? null,
          document_url: typeof citation?.document_url === 'string' ? citation.document_url : '',
          title: truncateText(typeof citation?.title === 'string' ? citation.title : '', 240),
          excerpt: truncateText(typeof citation?.excerpt === 'string' ? citation.excerpt : '', 240),
        }))
      : [],
    metadata: message.metadata ? {
      processing_time_ms: message.metadata.processing_time_ms ?? null,
      intent: message.metadata.intent ?? null,
      intent_confidence: message.metadata.intent_confidence ?? null,
      strategies_used: Array.isArray(message.metadata.strategies_used) ? message.metadata.strategies_used : [],
      total_candidates: message.metadata.total_candidates ?? null,
      llm_tokens_used: message.metadata.llm_tokens_used ?? null,
    } : null,
  }), [truncateText]);

  // Wrapper to persist queryMode to localStorage
  const setQueryMode = (mode) => {
    const normalizedMode = 'answer';
    setQueryModeState(normalizedMode);
    localStorage.setItem('queryMode', normalizedMode);
  };

  // Wrapper to persist personalizeMode to localStorage
  const setPersonalizeMode = (mode) => {
    setPersonalizeModeState(mode);
    localStorage.setItem('personalizeMode', mode);
  };

  // Wrapper to persist pipelineMode to localStorage
  const setPipelineMode = (mode) => {
    setPipelineModeState(mode);
    localStorage.setItem('pipelineMode', mode);
  };

  const updateScrollState = useCallback(() => {
    const container = messagesContainerRef.current;
    if (!container) {
      return;
    }

    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    const hasContentBelow = distanceFromBottom > scrollThreshold;
    isPinnedToBottomRef.current = !hasContentBelow;
    setShowScrollToBottom(hasContentBelow);
    if (!hasContentBelow) {
      setHasUnreadContentBelow(false);
    }
  }, [scrollThreshold]);

  const scrollToBottom = useCallback(() => {
    isPinnedToBottomRef.current = true;
    const container = messagesContainerRef.current;
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
    setShowScrollToBottom(false);
    setHasUnreadContentBelow(false);
  }, []);

  // Load datasources and Oracle settings on mount
  useEffect(() => {
    setQueryModeState('answer');
    localStorage.setItem('queryMode', 'answer');
  }, []);

  useEffect(() => {
    const loadDatasources = async () => {
      try {
        const response = await getDatasources();
        setDatasources(response.datasources || []);
      } catch (err) {
        console.warn('Failed to load datasources:', err);
      }
    };
    
    const loadOracleSettings = async () => {
      try {
        const settings = await getOracleSettings();
        setFastPipelineEnabled(settings.fast_pipeline_enabled || false);
      } catch (err) {
        console.warn('Failed to load Oracle settings:', err);
        // Default to false if we can't fetch settings
        setFastPipelineEnabled(false);
      }
    };
    
    loadDatasources();
    loadOracleSettings();
  }, []);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) {
      previousMessageCountRef.current = messages.length;
      return;
    }

    const messageCountIncreased = messages.length > previousMessageCountRef.current;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    const hasContentBelow = distanceFromBottom > scrollThreshold;
    const shouldAutoScroll = messageCountIncreased && isPinnedToBottomRef.current;

    if (shouldAutoScroll) {
      scrollToBottom();
    } else {
      setShowScrollToBottom(hasContentBelow);
    }

    if (!shouldAutoScroll && messageCountIncreased && hasContentBelow) {
      setHasUnreadContentBelow(true);
    } else if (shouldAutoScroll || !hasContentBelow) {
      setHasUnreadContentBelow(false);
    }

    previousMessageCountRef.current = messages.length;
  }, [messages, scrollThreshold, scrollToBottom]);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) {
      return;
    }

    updateScrollState();
    container.addEventListener('scroll', updateScrollState, { passive: true });
    return () => container.removeEventListener('scroll', updateScrollState);
  }, [updateScrollState]);

  // Welcome message with tips for crafting good queries
  const getWelcomeMessage = (email) => `Hello ${email}! I'm Aurora, your knowledge assistant for wireless standards and industry news.

**Tips for effective queries:**

**Include specific topics** — Wi-Fi 6/6E/7/8, 802.11ax/be/bn, 6 GHz, MLO, Matter, Thread, Bluetooth, 5G/6G

**Mention organizations** — Wi-Fi Alliance, IEEE, 3GPP, Qualcomm, Broadcom, Intel, MediaTek

**Add time context** — "last week", "last month", "in 2025", or specific dates

**Specify document types** — press release, whitepaper, blog, meeting minutes

**Example queries:**
- "What's new with Wi-Fi 8 in the last month?"
- "Show me Wi-Fi Alliance press releases about Matter"
- "Which companies are working on 802.11bn?"
- "Compare Wi-Fi 6E and Wi-Fi 7 features"

What would you like to know?`;

  // Welcome message JSX with icons
  const getWelcomeMessageJSX = (email) => (
    <div className="welcome-message">
      <p>{`Hello ${email}! I'm Aurora, your knowledge assistant for wireless standards and industry news.`}</p>
      
      <p><strong>Tips for effective queries:</strong></p>
      
      <div className="welcome-tip">
        <SearchIcon size={16} style={{marginRight: '8px', color: '#6b7280'}} />
        <strong>Include specific topics</strong> — Wi-Fi 6/6E/7/8, 802.11ax/be/bn, 6 GHz, MLO, Matter, Thread, Bluetooth, 5G/6G
      </div>
      
      <div className="welcome-tip">
        <BuildingIcon size={16} style={{marginRight: '8px', color: '#6b7280'}} />
        <strong>Mention organizations</strong> — Wi-Fi Alliance, IEEE, 3GPP, Qualcomm, Broadcom, Intel, MediaTek
      </div>
      
      <div className="welcome-tip">
        <CalendarIcon size={16} style={{marginRight: '8px', color: '#6b7280'}} />
        <strong>Add time context</strong> — "last week", "last month", "in 2025", or specific dates
      </div>
      
      <div className="welcome-tip">
        <DocumentIcon size={16} style={{marginRight: '8px', color: '#6b7280'}} />
        <strong>Specify document types</strong> — press release, whitepaper, blog, meeting minutes
      </div>
      
      <div className="welcome-enhance-info">
        <p>
          If you need more detailed information or find the answer quality lacking, click the <strong>Enhance</strong> button to get a comprehensive response using document content.
        </p>
      </div>
      
      <div className="welcome-examples">
        <p><strong>Example queries:</strong></p>
        <ul>
          <li>"What's new with Wi-Fi 8 in the last month?"</li>
          <li>"Show me Wi-Fi Alliance press releases about Matter"</li>
          <li>"Which companies are working on 802.11bn?"</li>
          <li>"Compare Wi-Fi 6E and Wi-Fi 7 features"</li>
        </ul>
      </div>
      
      <p>What would you like to know?</p>
    </div>
  );

  const getSimpleWelcomeMessage = () => 'Hello! I\'m Aurora, your knowledge management assistant. Please log in to start chatting.';

  useEffect(() => {
    // Load chat history from localStorage when user changes
    if (!user) {
      // Show welcome message when no user is authenticated
      setMessages([
        {
          role: 'assistant',
          content: getSimpleWelcomeMessage(),
          timestamp: new Date(),
        },
      ]);
      return;
    }

    // Load user-specific chat history
    const chatHistoryKey = `chatHistory_${user.id}`;
    const savedMessages = localStorage.getItem(chatHistoryKey);
    
    if (savedMessages) {
      try {
        const parsed = JSON.parse(savedMessages);
        const recentMessages = Array.isArray(parsed) ? parsed.slice(-MAX_STORED_MESSAGES) : [];
        // Convert timestamp strings back to Date objects
        const messagesWithDates = recentMessages.map(msg => ({
          ...msg,
          timestamp: new Date(msg.timestamp),
          documents: Array.isArray(msg.documents) ? msg.documents : [],
          citations: Array.isArray(msg.citations) ? msg.citations : [],
        }));
        setMessages(messagesWithDates);
      } catch (err) {
        console.error('Failed to load chat history:', err);
        // Add welcome message if loading fails
        setMessages([
          {
            role: 'assistant',
            content: getWelcomeMessage(user.email),
            isWelcomeMessage: true,
            userEmail: user.email,
            timestamp: new Date(),
          },
        ]);
      }
    } else {
      // Add welcome message for new user chat history
      setMessages([
        {
          role: 'assistant',
          content: getWelcomeMessage(user.email),
          isWelcomeMessage: true,
          userEmail: user.email,
          timestamp: new Date(),
        },
      ]);
    }
  }, [user]);

  // Save messages to localStorage whenever they change (user-specific)
  useEffect(() => {
    if (user && messages.length > 0) {
      const chatHistoryKey = `chatHistory_${user.id}`;
      try {
        const compactMessages = messages
          .slice(-MAX_STORED_MESSAGES)
          .map(compactMessageForStorage);
        localStorage.setItem(chatHistoryKey, JSON.stringify(compactMessages));
      } catch (err) {
        console.warn('Failed to persist chat history:', err);
      }
    }
  }, [compactMessageForStorage, messages, user]);

  // Handle input change with @ detection for datasource mentions
  const handleInputChange = useCallback((e) => {
    const value = e.target.value;
    setInputValue(value);

    // Find @ symbol and text after it
    const cursorPos = e.target.selectionStart;
    const textBeforeCursor = value.substring(0, cursorPos);
    const atMatch = textBeforeCursor.match(/@(\w*)$/);

    if (atMatch) {
      setMentionSearchText(atMatch[1] || '');
      setShowMentionDropdown(true);
    } else {
      setShowMentionDropdown(false);
      setMentionSearchText('');
    }
  }, []);

  // Handle selecting a datasource from the mention dropdown
  const handleMentionSelect = useCallback((datasource) => {
    // Don't add if already selected
    if (selectedDatasources.find(ds => ds.datasource_id === datasource.datasource_id)) {
      setShowMentionDropdown(false);
      setMentionSearchText('');
      return;
    }

    // Add to selected datasources
    setSelectedDatasources(prev => [...prev, datasource]);

    // Remove the @text from input
    const cursorPos = inputRef.current?.selectionStart || inputValue.length;
    const textBeforeCursor = inputValue.substring(0, cursorPos);
    const atIndex = textBeforeCursor.lastIndexOf('@');
    if (atIndex !== -1) {
      const newValue = inputValue.substring(0, atIndex) + inputValue.substring(cursorPos);
      setInputValue(newValue);
    }

    setShowMentionDropdown(false);
    setMentionSearchText('');
    
    // Focus back on input
    inputRef.current?.focus();
  }, [inputValue, selectedDatasources]);

  // Remove a selected datasource
  const handleRemoveDatasource = useCallback((datasourceId) => {
    setSelectedDatasources(prev => prev.filter(ds => ds.datasource_id !== datasourceId));
  }, []);

  const hasUsableAnswer = useCallback((value) => {
    if (typeof value !== 'string') {
      return false;
    }

    const trimmed = value.trim();
    return Boolean(trimmed)
      && trimmed !== 'Here are the relevant documents:'
      && trimmed !== 'No answer was generated.';
  }, []);

  const buildDocumentFallbackAnswer = useCallback((documents) => {
    if (!documents.length) {
      return 'I could not generate a usable answer for this question.';
    }

    const topDocuments = documents.slice(0, 3)
      .map((doc) => {
        const dateSuffix = doc.publish_date ? ` (${doc.publish_date})` : '';
        return `- **${doc.title || 'Untitled'}**${dateSuffix}`;
      })
      .join('\n');

    return `I found relevant supporting documents but did not receive a complete narrative answer from the service. The strongest references are:\n\n${topDocuments}`;
  }, []);

  const autoEnhanceMessage = useCallback(async (queryId, queryText, documents) => {
    if (!queryId || !documents?.length) {
      return;
    }

    try {
      const enhanced = await sendEnhanceQuery(queryText, documents);
      if (!hasUsableAnswer(enhanced?.enhanced_answer)) {
        return;
      }

      setMessages((prev) => prev.map((message) => {
        if (message.queryId !== queryId) {
          return message;
        }

        const originalAnswer = message.originalAnswer || {
          content: message.content,
          citations: message.citations,
          confidenceScore: message.confidenceScore,
        };

        return {
          ...message,
          originalAnswer,
          content: enhanced.enhanced_answer,
          citations: enhanced.citations?.length > 0 ? enhanced.citations : message.citations,
          confidenceScore: enhanced.confidence_score ?? message.confidenceScore,
          directQuotes: enhanced.direct_quotes || [],
          enhanceMetadata: enhanced.metadata || null,
          isEnhanced: true,
          showingEnhanced: true,
          enhancedAnswer: {
            content: enhanced.enhanced_answer,
            citations: enhanced.citations?.length > 0 ? enhanced.citations : message.citations,
            confidenceScore: enhanced.confidence_score ?? message.confidenceScore,
            directQuotes: enhanced.direct_quotes || [],
            enhanceMetadata: enhanced.metadata || null,
          },
        };
      }));
    } catch (enhanceErr) {
      console.warn('Automatic answer enhancement failed:', enhanceErr);
    }
  }, [hasUsableAnswer]);

  // Execute the actual query (used after suggestion decision)
  const executeQuery = async (queryText, datasourceIds = []) => {
    // Get datasource names for display (if available)
    const datasourceNames = datasourceIds.map(id => {
      const ds = datasources.find(d => d.datasource_id === id);
      return ds ? ds.name : id;
    });
    
    const userMessage = {
      role: 'user',
      content: queryText,  // Clean query without @ mentions
      timestamp: new Date(),
      datasourceIds: datasourceIds, // Store IDs for reference
      datasourceNames: datasourceNames, // Store names for display
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
    setError(null);
    setSelectedDatasources([]); // Clear selected datasources after sending

    // Set up a 90s timeout for the oracle query
    const QUERY_TIMEOUT_MS = 90000;
    let timeoutId = null;

    try {
      // Send query to Oracle service with datasource filter
      const queryPromise = sendOracleQuery(user.id, queryText, {
        mode: 'answer',
        maxDocuments: 10,
        includeGraphContext: true,
        datasourceIds: datasourceIds.length > 0 ? datasourceIds : null,
        personalize: personalizeMode,
        pipelineOverride: pipelineMode === 'system' ? null : pipelineMode,
      });

      const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error('QUERY_TIMEOUT')), QUERY_TIMEOUT_MS);
      });

      const response = await Promise.race([queryPromise, timeoutPromise]);
      clearTimeout(timeoutId);

      const mappedDocuments = response.documents?.map(doc => ({
        title: doc.title,
        url: doc.url,
        publish_date: doc.publish_date,
        summary: doc.summary,
        topics: doc.topics || [],
        organisations: doc.organizations || [],
        relevance_score: doc.relevance_score,
        match_reasons: doc.match_reasons || [],
        source: doc.source || null,
        datasource_id: doc.datasource_id || null,
      })) || [];

      let answerContent = response.answer;
      let citations = response.citations || [];
      let confidenceScore = response.confidence_score;
      const shouldAutoEnhance = !hasUsableAnswer(answerContent) && mappedDocuments.length > 0;

      if (shouldAutoEnhance || !hasUsableAnswer(answerContent)) {
        answerContent = buildDocumentFallbackAnswer(mappedDocuments);
      }

      // Final safety net — ensure content is never empty/null (prevents silent no-op renders)
      if (!answerContent || typeof answerContent !== 'string' || !answerContent.trim()) {
        answerContent = mappedDocuments.length > 0
          ? buildDocumentFallbackAnswer(mappedDocuments)
          : 'No response was returned for this query.';
      }

      // Map Oracle response format to our message format
      // Oracle returns: { query_id, mode, answer, citations, documents, graph_context, metadata, suggestions, confidence_score, personalization_applied, pipeline }
      const assistantMessage = {
        role: 'assistant',
        content: answerContent,
        timestamp: new Date(),
        queryId: response.query_id, // Store for feedback
        responseMode: 'answer',
        personalizationApplied: response.personalization_applied || false,
        pipeline: response.pipeline || null, // 'fast' or 'baseline' - track which pipeline was used
        citations,
        documents: mappedDocuments,
        graphContext: response.graph_context,
        metadata: response.metadata,
        suggestions: response.suggestions || [],
        confidenceScore,
        originalQuery: queryText, // Store for enhance feature
        isEnhanced: false,
        showingEnhanced: false,
        enhanceMetadata: null,
      };

      setMessages((prev) => [...prev, assistantMessage]);

      if (shouldAutoEnhance) {
        void autoEnhanceMessage(response.query_id, queryText, mappedDocuments);
      }
    } catch (err) {
      clearTimeout(timeoutId);
      console.error('Query error:', err);

      let userFacingMessage;
      if (err.message === 'QUERY_TIMEOUT') {
        userFacingMessage = 'The query is taking longer than expected. Please try again — complex queries can occasionally time out.';
      } else if (err.response?.status === 504) {
        userFacingMessage = 'The server took too long to respond. Please try again.';
      } else if (err.response?.status === 401) {
        userFacingMessage = 'Your session may have expired. Please refresh the page and try again.';
      } else if (err.response?.status >= 500) {
        userFacingMessage = 'The service encountered an internal error. Please try again in a moment.';
      } else if (err.response?.data?.detail?.message) {
        userFacingMessage = err.response.data.detail.message;
      } else if (err.response?.data?.detail) {
        userFacingMessage = typeof err.response.data.detail === 'string'
          ? err.response.data.detail
          : 'An error occurred while processing your query.';
      } else if (!window.navigator.onLine) {
        userFacingMessage = 'You appear to be offline. Please check your connection and try again.';
      } else {
        userFacingMessage = 'Unable to get a response. Please try again.';
      }

      setError(userFacingMessage);

      const errorMessage = {
        role: 'assistant',
        content: userFacingMessage,
        timestamp: new Date(),
        isError: true,
      };

      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle enhance request for a specific message
  const handleEnhanceMessage = async (messageIndex) => {
    const message = messages[messageIndex];
    if (!message || !message.documents?.length || !message.originalQuery) {
      console.warn('Cannot enhance message - missing documents or query');
      return;
    }

    setEnhancingMessageIndex(messageIndex);

    try {
      const response = await sendEnhanceQuery(message.originalQuery, message.documents);
      
      // Update the message with enhanced content, preserving original answer for toggle
      setMessages((prev) => {
        const updated = [...prev];
        updated[messageIndex] = {
          ...updated[messageIndex],
          // Store original answer data if not already stored
          originalAnswer: updated[messageIndex].originalAnswer || {
            content: updated[messageIndex].content,
            citations: updated[messageIndex].citations,
            confidenceScore: updated[messageIndex].confidenceScore,
          },
          // Set enhanced answer as current
          content: response.enhanced_answer,
          directQuotes: response.direct_quotes || [],
          enhanceMetadata: response.metadata,
          confidenceScore: response.confidence_score,
          isEnhanced: true,
          showingEnhanced: true, // Track which version is currently displayed
          // Update citations from enhance response if available
          citations: response.citations?.length > 0 ? response.citations : updated[messageIndex].citations,
          // Store enhanced data separately for toggle
          enhancedAnswer: {
            content: response.enhanced_answer,
            citations: response.citations?.length > 0 ? response.citations : updated[messageIndex].citations,
            confidenceScore: response.confidence_score,
            directQuotes: response.direct_quotes || [],
            enhanceMetadata: response.metadata,
          },
        };
        return updated;
      });
    } catch (err) {
      console.error('Enhance error:', err);
      const errorCode = err.response?.data?.detail?.error;
      const errorMessage = err.response?.data?.detail?.message;
      const statusCode = err.response?.status;
      
      if (errorCode === 'LLM_TIMEOUT' || statusCode === 504) {
        setError('The enhanced answer is taking too long to generate. Please try again in a moment.');
      } else if (statusCode === 503) {
        setError('The service is temporarily unavailable. Please wait a moment and try again.');
      } else if (errorCode === 'FEATURE_DISABLED') {
        setError('Enhanced answers feature is currently disabled.');
      } else {
        setError(errorMessage || err.response?.data?.detail || 'Failed to enhance answer');
      }
    } finally {
      setEnhancingMessageIndex(null);
    }
  };

  // Handle toggling between original and enhanced answer
  const handleToggleEnhanced = (messageIndex) => {
    setMessages((prev) => {
      const updated = [...prev];
      const message = updated[messageIndex];
      
      if (!message.originalAnswer || !message.enhancedAnswer) return prev;
      
      const showEnhanced = !message.showingEnhanced;
      
      if (showEnhanced) {
        // Show enhanced version
        updated[messageIndex] = {
          ...message,
          content: message.enhancedAnswer.content,
          citations: message.enhancedAnswer.citations,
          confidenceScore: message.enhancedAnswer.confidenceScore,
          directQuotes: message.enhancedAnswer.directQuotes,
          enhanceMetadata: message.enhancedAnswer.enhanceMetadata,
          showingEnhanced: true,
        };
      } else {
        // Show original version
        updated[messageIndex] = {
          ...message,
          content: message.originalAnswer.content,
          citations: message.originalAnswer.citations,
          confidenceScore: message.originalAnswer.confidenceScore,
          directQuotes: [], // Original doesn't have direct quotes
          enhanceMetadata: null, // Original doesn't have enhance metadata
          showingEnhanced: false,
        };
      }
      
      return updated;
    });
    
    // Scroll to the message after state update
    setTimeout(() => {
      const messageEl = messageRefs.current[messageIndex];
      if (messageEl) {
        messageEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 50);
  };

  // Handle user feedback on Oracle responses
  const handleFeedback = async (queryId, feedbackType) => {
    try {
      await submitOracleFeedback(queryId, feedbackType, {
        mode: queryMode,
      });
      // Update message to mark feedback as given
      setMessages((prev) => 
        prev.map((msg) => 
          msg.queryId === queryId 
            ? { ...msg, feedbackGiven: feedbackType }
            : msg
        )
      );
    } catch (err) {
      console.error('Failed to submit feedback:', err);
      throw err; // Re-throw so the component can handle it
    }
  };

  // Handle user rejecting the suggestion (use original query)
  const handleRejectSuggestion = () => {
    const originalQuery = pendingQuery;
    const datasourceIds = pendingDatasourceIds;
    setQuerySuggestion(null);
    setPendingQuery(null);
    setPendingDatasourceIds([]);
    executeQuery(originalQuery, datasourceIds);
  };

  // Handle dismissing the suggestion dialog
  const handleDismissSuggestion = () => {
    setQuerySuggestion(null);
    setPendingQuery(null);
    setPendingDatasourceIds([]);
    setInputValue(pendingQuery || '');
  };

  // Helper function to ingest YouTube video
  const ingestYouTubeVideo = async (url, forceRedigest = false) => {
    // Check if user is admin
    if (user && user.role !== 'admin' && user.role !== 'superadmin') {
      // Add user message
      const userMessage = {
        role: 'user',
        content: url,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);
      
      // Add error message
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: '❌ YouTube video/playlist ingestion is restricted to admin users only. Please contact an administrator to add YouTube content.',
          timestamp: new Date(),
          isError: true,
        },
      ]);
      return;
    }
    
    // Add user message
    const userMessage = {
      role: 'user',
      content: url,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    
    // Add loading message
    const loadingMessage = {
      role: 'assistant',
      content: forceRedigest ? '🔄 Re-processing YouTube video...' : '🎥 Processing YouTube video/playlist...',
      timestamp: new Date(),
      isLoading: true,
    };
    setMessages((prev) => [...prev, loadingMessage]);
    setIsLoading(true);
    
    try {
      const response = await fetch('/api/oracle/ingest/youtube', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          url: url,
          user_id: user.id,
          force_redigest: forceRedigest,
        }),
      });
      
      if (response.status === 409) {
        // Video already exists
        const errorData = await response.json();
        
        // Remove loading message
        setMessages((prev) => prev.filter(msg => !msg.isLoading));
        setIsLoading(false);
        
        // Show confirmation dialog
        setYoutubeConfirmation({
          url: url,
          existingTitle: errorData.detail.existing_title,
          videoId: errorData.detail.video_id,
        });
        return;
      }
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail?.message || errorData.detail || 'Failed to process YouTube video');
      }
      
      const result = await response.json();
      
      // Remove loading message and add success message
      setMessages((prev) => {
        const withoutLoading = prev.filter(msg => !msg.isLoading);
        return [
          ...withoutLoading,
          {
            role: 'assistant',
            content: `✅ Successfully ${forceRedigest ? 're-processed' : 'added'} video: **${result.title}**\n\nDuration: ${Math.floor(result.duration_seconds / 60)}:${(result.duration_seconds % 60).toString().padStart(2, '0')}\nSegments created: ${result.segments_created}\n\nYou can now query this video content using @youtube mentions!`,
            timestamp: new Date(),
          },
        ];
      });
    } catch (err) {
      // Remove loading message and add error message
      setMessages((prev) => {
        const withoutLoading = prev.filter(msg => !msg.isLoading);
        return [
          ...withoutLoading,
          {
            role: 'assistant',
            content: `❌ Failed to process YouTube video: ${err.message}`,
            timestamp: new Date(),
            isError: true,
          },
        ];
      });
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!inputValue.trim() || isLoading) return;
    // querySuggestion blocks non-fast-mode submissions (fast mode skips analyzeQuery entirely)
    if (querySuggestion && pipelineMode !== 'fast' && !fastPipelineEnabled) return;

    if (!user) {
      setError('Please log in to start chatting.');
      return;
    }

    if (backendStatus !== 'connected') {
      setError('Backend is not connected. Please check your connection.');
      return;
    }

    const queryText = inputValue.trim();
    const datasourceIds = selectedDatasources.map(ds => ds.datasource_id);
    
    // Check if input is a YouTube URL (video or playlist)
    const youtubePattern = /(https?:\/\/)?(www\.)?(youtube\.com\/(watch\?v=|playlist\?list=)|youtu\.be\/)([a-zA-Z0-9_-]+)/;
    const youtubeMatch = queryText.match(youtubePattern);
    
    if (youtubeMatch) {
      // Handle YouTube URL submission (video or playlist)
      setInputValue('');
      setError(null);
      setShowMentionDropdown(false);
      
      await ingestYouTubeVideo(queryText, false);
      return;
    }
    
    setInputValue('');
    setError(null);
    setShowMentionDropdown(false);

    // Never interrupt explicit fast-mode queries with the pre-query analyzer dialog
    if (pipelineMode === 'fast' || fastPipelineEnabled) {
      executeQuery(queryText, datasourceIds);
      return;
    }

    try {
      // First, analyze the query for quality
      const analysis = await analyzeQuery(queryText);
      
      // If query has issues, show dialog (even without a suggested revision)
      if (!analysis.is_good_query && (analysis.suggested_query || analysis.issues?.length > 0)) {
        setPendingQuery(queryText);
        setPendingDatasourceIds(datasourceIds);
        setQuerySuggestion(analysis);
        return;
      }
      
      // Query is good, execute it directly
      executeQuery(queryText, datasourceIds);
    } catch (err) {
      // If analysis fails, just execute the query anyway
      console.warn('Query analysis failed, proceeding with original query:', err);
      executeQuery(queryText, datasourceIds);
    }
  };

  const handleKeyPress = (e) => {
    // Don't submit if mention dropdown is open (let it handle Enter/Tab)
    if (showMentionDropdown) return;
    
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleNewChat = () => {
    if (!user) return;
    
    // Clear current messages and start fresh with welcome message
    const welcomeMessage = {
      role: 'assistant',
      content: getWelcomeMessage(user.email),
      isWelcomeMessage: true,
      userEmail: user.email,
      timestamp: new Date(),
    };
    
    setMessages([welcomeMessage]);
    setError(null);
    
    // Clear the saved chat history for this user
    const chatHistoryKey = `chatHistory_${user.id}`;
    localStorage.removeItem(chatHistoryKey);
  };

  return (
    <div className="chatbot-container">
      <div className="chat-header">
        <div className="chat-header-content">
          <div className="chat-header-left">
            {user && (
              <select
                className="pipeline-mode-dropdown"
                value={pipelineMode}
                onChange={(e) => setPipelineMode(e.target.value)}
                disabled={isLoading}
                title="Engine: Fast uses instant templates, Baseline uses comprehensive LLM synthesis, System auto-selects"
              >
                <option value="system">Engine: System (A/B)</option>
                <option value="fast">Engine: Fast</option>
                <option value="baseline">Engine: Baseline</option>
              </select>
            )}
          </div>
          <div className="chat-header-actions">
            {user && (
              <select
                className="query-mode-dropdown"
                value={queryMode}
                onChange={(e) => setQueryMode(e.target.value)}
                disabled={isLoading}
                title="Chat always requests an answer and keeps documents as references"
              >
                <option value="answer">Query: Answer</option>
              </select>
            )}
            {user && (
              <select
                className="personalize-mode-dropdown"
                value={personalizeMode}
                onChange={(e) => setPersonalizeMode(e.target.value)}
                disabled={isLoading}
                title="Personalization: Tailor answers based on your preferences"
              >
                <option value="auto">Personalize: Auto</option>
                <option value="on">Personalize: On</option>
                <option value="off">Personalize: Off</option>
              </select>
            )}
            {user && messages.length > 1 && (
              <button 
                className="btn btn-secondary new-chat-btn" 
                onClick={handleNewChat}
                title="Start a new conversation"
              >
                <ChatIcon size={16} /> New Chat
              </button>
            )}
          </div>
          {!user && (
            <p className="chat-warning">
              <WarningIcon size={16} /> Please log in to start chatting
            </p>
          )}
        </div>
      </div>

      <div className="messages-panel">
        <div className="messages-container" ref={messagesContainerRef}>
          {messages.map((message, index) => (
            <div 
              key={index} 
              className={`message message-${message.role}`}
              ref={(el) => { messageRefs.current[index] = el; }}
            >
              <div className="message-avatar">
                {message.role === 'user' ? <ProfileIcon size={20} /> : <ChatIcon size={20} />}
              </div>
              <div className="message-content">
                <div className="message-header">
                  <span className="message-sender">
                    {message.role === 'user' ? 'You' : 'Aurora'}
                  </span>
                  <span className="message-time">
                    {message.timestamp.toLocaleTimeString()}
                  </span>
                </div>
                
                {/* User messages and error messages - render content directly */}
                {(message.role === 'user' || message.isError) && (
                  <div className={`message-text ${message.isError ? 'error' : ''}`}>
                    {/* Show datasource chips for user messages with filtered datasources */}
                    {message.role === 'user' && message.datasourceIds?.length > 0 && (
                      <div className="user-message-datasources">
                        {message.datasourceIds.map((id, idx) => (
                          <span key={id} className="datasource-chip">
                            @{message.datasourceNames?.[idx] || id}
                          </span>
                        ))}
                      </div>
                    )}
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {message.content}
                    </ReactMarkdown>
                  </div>
                )}

                {/* Assistant messages with Oracle data - use QueryResultDisplay */}
                {message.role === 'assistant' && !message.isError && (
                  <>
                    {/* For welcome messages or simple responses without documents */}
                    {!message.documents?.length && !message.citations?.length && (
                      <div className="message-text">
                        {message.isWelcomeMessage ? (
                          getWelcomeMessageJSX(message.userEmail)
                        ) : (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {message.content}
                          </ReactMarkdown>
                        )}
                      </div>
                    )}
                    
                    {/* For Oracle responses with documents/citations - use new display component */}
                    {(message.documents?.length > 0 || message.citations?.length > 0) && (
                      <QueryResultDisplay 
                        message={message} 
                        isAdmin={user?.role === 'admin' || user?.role === 'superadmin'}
                        onEnhance={() => handleEnhanceMessage(index)}
                        onToggleEnhanced={() => handleToggleEnhanced(index)}
                        isEnhancing={enhancingMessageIndex === index}
                        onFeedback={handleFeedback}
                        onDisplayModeChange={(mode) => {
                          setMessages((prev) => {
                            const updated = [...prev];
                            updated[index] = { ...updated[index], displayMode: mode };
                            return updated;
                          });
                        }}
                      />
                    )}
                  </>
                )}
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="message message-assistant">
              <div className="message-avatar"><ChatIcon size={20} /></div>
              <div className="message-content">
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {showScrollToBottom && (
          <button
            type="button"
            className={`chat-scroll-down-button ${hasUnreadContentBelow ? 'has-new-content' : ''}`}
            onClick={scrollToBottom}
            aria-label="Scroll to latest messages"
            title="Scroll to latest messages"
          >
            <Icon Component={ChevronDownIcon} size={18} />
          </button>
        )}
      </div>

      {/* Query Suggestion Dialog */}
      {querySuggestion && (
        <div className="query-suggestion-overlay">
          <div className="query-suggestion-dialog">
            <div className="suggestion-header">
              <span className="suggestion-icon">
                <Icon Component={LightbulbIcon} size={16} />
              </span>
              <h3>{querySuggestion.suggested_query ? 'Improve Your Query?' : 'Query Could Be Better'}</h3>
              <button 
                className="suggestion-close-btn"
                onClick={handleDismissSuggestion}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div className="suggestion-content">
              <div className="original-query">
                <label>Your query:</label>
                <p>"{pendingQuery}"</p>
              </div>
              {querySuggestion.issues?.length > 0 && (
                <div className="suggestion-issues">
                  <label>Issues detected:</label>
                  <ul>
                    {querySuggestion.issues.map((issue, idx) => (
                      <li key={idx}>{issue}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="suggested-query">
                <label>{querySuggestion.suggested_query ? 'Edit suggested query:' : 'Revise your query:'}</label>
                <textarea
                  className="query-edit-input"
                  defaultValue={querySuggestion.suggested_query || pendingQuery}
                  id="revised-query-input"
                  rows={2}
                  placeholder="Try adding specific topics, organizations, or time ranges..."
                />
                {querySuggestion.suggestion_reason ? (
                  <span className="suggestion-reason">{querySuggestion.suggestion_reason}</span>
                ) : (
                  <span className="suggestion-reason">
                    <Icon Component={LightbulbIcon} size={16} style={{marginRight: '4px'}} /> Tip: Include topics (Wi-Fi 7, HaLow, Matter), organizations (Wi-Fi Alliance), or time context (last month)
                  </span>
                )}
              </div>
            </div>
            <div className="suggestion-actions">
              <button 
                className="btn btn-secondary"
                onClick={handleRejectSuggestion}
              >
                Use Original
              </button>
              <button 
                className="btn btn-primary"
                onClick={() => {
                  const revisedInput = document.getElementById('revised-query-input');
                  const revisedQuery = revisedInput?.value?.trim() || pendingQuery;
                  const datasourceIds = pendingDatasourceIds;
                  setQuerySuggestion(null);
                  setPendingQuery(null);
                  setPendingDatasourceIds([]);
                  executeQuery(revisedQuery, datasourceIds);
                }}
              >
                ✓ Submit Query
              </button>
            </div>
          </div>
        </div>
      )}

      {/* YouTube Duplicate Confirmation Dialog */}
      {youtubeConfirmation && (
        <div className="query-suggestion-overlay">
          <div className="query-suggestion-dialog">
            <div className="suggestion-header">
              <span className="suggestion-icon">🎥</span>
              <h3>Video Already Processed</h3>
              <button 
                className="suggestion-close-btn"
                onClick={() => setYoutubeConfirmation(null)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div className="suggestion-content">
              <div className="original-query">
                <label>Existing video:</label>
                <p><strong>{youtubeConfirmation.existingTitle}</strong></p>
              </div>
              <div className="suggestion-issues">
                <p>This YouTube video has already been processed and is available in the knowledge base. Would you like to re-process it?</p>
                <p style={{ marginTop: '12px', fontSize: '0.9em', color: '#666' }}>
                  Re-processing will update the transcript and metadata, which may be useful if the video has been updated or if you want to refresh the content.
                </p>
              </div>
            </div>
            <div className="suggestion-actions">
              <button 
                className="btn btn-secondary"
                onClick={() => setYoutubeConfirmation(null)}
              >
                Cancel
              </button>
              <button 
                className="btn btn-primary"
                onClick={async () => {
                  const url = youtubeConfirmation.url;
                  setYoutubeConfirmation(null);
                  await ingestYouTubeVideo(url, true);
                }}
              >
                ✓ Re-process Video
              </button>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="chat-error">
          <span className="chat-error-message">
            <WarningIcon size={16} /> {error}
          </span>
          <button 
            className="chat-error-dismiss" 
            onClick={() => setError(null)}
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      )}

      <form className="chat-input-form" onSubmit={handleSubmit}>
        {/* Selected datasources */}
        {selectedDatasources.length > 0 && (
          <div className="selected-mentions">
            {selectedDatasources.map(ds => (
              <span key={ds.datasource_id} className="selected-mention">
                @{ds.datasource_id}
                <button 
                  type="button"
                  className="remove-mention"
                  onClick={() => handleRemoveDatasource(ds.datasource_id)}
                  aria-label={`Remove ${ds.datasource_id}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        
        {/* Mention dropdown */}
        <DatasourceMention
          datasources={datasources}
          searchText={mentionSearchText}
          onSelect={handleMentionSelect}
          onClose={() => setShowMentionDropdown(false)}
          isVisible={showMentionDropdown}
          inputRef={inputRef}
        />
        
        <div className="chat-input-row">
          <textarea
            ref={inputRef}
            className="chat-input"
            value={inputValue}
            onChange={handleInputChange}
            onKeyPress={handleKeyPress}
            placeholder={user ? "Ask me anything... (use @datasource to filter)" : "Please log in first..."}
            rows="2"
            disabled={!user || isLoading || querySuggestion || backendStatus !== 'connected'}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!user || !inputValue.trim() || isLoading || querySuggestion || backendStatus !== 'connected'}
          >
            {isLoading ? (<><HourglassIcon size={16} /> Thinking...</>) : (<><SendIcon size={16} /> Send</>)}
          </button>
        </div>
      </form>
    </div>
  );
};

export default Chatbot;
