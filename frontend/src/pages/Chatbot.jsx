import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sendOracleQuery, sendOracleQueryStream, analyzeQuery, sendEnhanceQuery, getDatasources, submitOracleFeedback, getOracleSettings, clearOracleConversation } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { ProfileIcon, ChatIcon, WarningIcon, HourglassIcon, SendIcon, SearchIcon, BuildingIcon, CalendarIcon, DocumentIcon, LightbulbIcon, ChevronDownIcon } from '../components/icons';
import Icon from '../components/Icon';
import QueryResultDisplay from '../components/QueryResultDisplay';
import DatasourceMention from '../components/DatasourceMention';
import './Chatbot.css';

const MAX_STORED_MESSAGES = 24;
const MAX_STORED_DOCUMENTS = 10;
const MAX_STORED_CITATIONS = 10;
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
  // Personalisation is locked ON for the trial — selector hidden so users
  // don't accidentally turn it off and degrade their own answers.
  const personalizeMode = 'on';
  // Pipeline mode is locked to "system" (fast with baseline fallback) for the
  // trial — the only path actually validated end-to-end.
  const pipelineMode = 'system';
  // Persona lens replaced by the user-profile "About you" free-text field —
  // selection here was per-session noise; the profile field reads on every
  // query via the existing personalization context. No state needed.
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
  const getWelcomeMessage = (email) => `Hello ${email}! I'm Aurora, your assistant for wireless standards and industry knowledge.

**Commands** *(type exactly to trigger)*
— \`help\` · \`agents\` · \`my agents\` · \`feed\` · \`pipeline fast\` · \`personalize on/off\` · \`about\`

**Example queries**
- *"What's new with Wi-Fi 8 UHR in the last week?"*
- *"@wba show me the latest from all workgroups"*
- *"Compare Wi-Fi 7 and Wi-Fi 8 for dense deployments"*
- *"Which companies are contributing to 802.11bn?"*

What would you like to know?`;

  // Curated starter prompts shown on the welcome screen. Clicking a chip
  // submits the question immediately so first-time users have an obvious
  // on-ramp without having to invent a good query themselves.
  // TODO(#2 role-aware roadmap): filter by user.role once that field exists.
  // Chosen so each routes to the FAST pipeline and returns public-content
  // citations (no WBA Causeway login walls). The WBA AI/ML / press-release
  // variants were swapped after pre-trial probing — the previous wording
  // dropped to baseline or pulled login-required URLs.
  const STARTER_PROMPTS = [
    "What's new with Wi-Fi 8 UHR in the last 30 days?",
    "Compare Wi-Fi 7 and Wi-Fi 8 for dense enterprise deployments",
    "What are the latest press releases?",
    "What are the open security concerns in WPA3?",
    "What is OFDMA and how does it work?",
    "What's new in Wi-Fi 7?",
  ];

  // Welcome message JSX with icons
  const getWelcomeMessageJSX = (email) => (
    <div className="welcome-message">
      <p>{`Hello ${email}! I'm Aurora, your assistant for wireless standards and industry knowledge.`}</p>

      <p><strong>Commands</strong> <em>(type exactly to trigger)</em></p>
      <div className="welcome-tip">
        <SearchIcon size={16} style={{ marginRight: '8px', color: '#6b7280' }} />
        <code>help</code>&nbsp;·&nbsp;<code>agents</code>&nbsp;·&nbsp;<code>my agents</code>&nbsp;·&nbsp;
        <code>feed</code>&nbsp;·&nbsp;<code>about</code>&nbsp;·&nbsp;<code>clear</code>
      </div>

      <div className="welcome-enhance-info">
        <p>
          After an answer appears, click <strong>Enhance</strong> for a deeper document-search response. Use <strong>@datasource</strong> to scope a query to a specific workgroup or source.
        </p>
      </div>

      <div className="welcome-starters">
        <p className="welcome-starters-heading"><LightbulbIcon size={16} style={{ marginRight: '6px' }} /> Try one of these to get started:</p>
        <div className="welcome-starters-grid">
          {STARTER_PROMPTS.map((prompt, i) => (
            <button
              key={i}
              type="button"
              className="welcome-starter-chip"
              onClick={() => executeQuery(prompt, [])}
              disabled={isLoading || backendStatus !== 'connected'}
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]); // Depend on user ID only — object identity changes on every auth check

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compactMessageForStorage, messages, user?.id]); // user?.id avoids resets on auth-check object churn

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
      content: queryText,
      timestamp: new Date(),
      datasourceIds: datasourceIds,
      datasourceNames: datasourceNames,
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);
    setError(null);
    setSelectedDatasources([]);

    const streamOptions = {
      mode: 'answer',
      maxDocuments: 10,
      includeGraphContext: true,
      datasourceIds: datasourceIds.length > 0 ? datasourceIds : null,
      personalize: personalizeMode,
      pipelineOverride: pipelineMode === 'system' ? null : pipelineMode,
    };

    // Streaming placeholder — added once, then updated incrementally
    const placeholderMsg = {
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      queryId: null,
      responseMode: 'answer',
      personalizationApplied: false,
      pipeline: null,
      citations: [],
      documents: [],
      graphContext: null,
      metadata: null,
      suggestions: [],
      confidenceScore: null,
      originalQuery: queryText,
      isEnhanced: false,
      showingEnhanced: false,
      enhanceMetadata: null,
      isStreaming: true,
    };

    // Append placeholder so the user sees the typing indicator immediately
    setMessages((prev) => [...prev, placeholderMsg]);
    const msgIndexRef = { current: -1 }; // will be set on first state update

    // Accumulate tokens so we can apply the fallback check at the end
    let accumulated = '';
    let metaReceived = false;

    try {
      for await (const event of sendOracleQueryStream(user.id, queryText, streamOptions)) {
        if (event.type === 'token') {
          accumulated += event.token;
          // Once meta is received the authoritative answer is already set — don't
          // overwrite it with the newline-stripped token stream (fast pipeline sends
          // meta first, then word-chunk tokens that lose markdown structure).
          if (!metaReceived) {
            setMessages((prev) => {
              const idx = prev.length - 1;
              if (idx < 0 || prev[idx].role !== 'assistant') return prev;
              const updated = [...prev];
              updated[idx] = { ...updated[idx], content: accumulated };
              return updated;
            });
          }
        } else if (event.type === 'meta') {
          metaReceived = true;
          const mappedDocuments = (event.documents || []).map(doc => ({
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
          }));

          // Use the final answer from meta if provided (handles non-streaming fallback)
          const finalAnswer = event.answer || accumulated;
          const usableAnswer = hasUsableAnswer(finalAnswer)
            ? finalAnswer
            : mappedDocuments.length > 0
              ? buildDocumentFallbackAnswer(mappedDocuments)
              : 'No response was returned for this query.';

          setMessages((prev) => {
            const idx = prev.length - 1;
            if (idx < 0 || prev[idx].role !== 'assistant') return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              content: usableAnswer,
              queryId: event.query_id || null,
              pipeline: event.pipeline || null,
              citations: event.citations || [],
              documents: mappedDocuments,
              confidenceScore: event.confidence_score ?? null,
              personalizationApplied: event.personalization_applied ?? false,
              metadata: event.metadata || null,
              isStreaming: false,
            };
            return updated;
          });
        } else if (event.type === 'done') {
          // Streaming finished — if no meta was received, finalize with what we have
          if (!metaReceived) {
            const usableAnswer = hasUsableAnswer(accumulated)
              ? accumulated
              : 'No response was returned for this query.';
            setMessages((prev) => {
              const idx = prev.length - 1;
              if (idx < 0 || prev[idx].role !== 'assistant') return prev;
              const updated = [...prev];
              updated[idx] = { ...updated[idx], content: usableAnswer, isStreaming: false };
              return updated;
            });
          }
          break;
        } else if (event.type === 'error') {
          throw new Error(event.error || 'Streaming error');
        }
      }
    } catch (err) {
      console.error('Query error:', err);

      // Remove the streaming placeholder and show the error
      setMessages((prev) => prev.filter((m) => !m.isStreaming));

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

  // ---------------------------------------------------------------------------
  // Command router — intercepts short commands before they reach Oracle search.
  // Returns a response string if the input is a known command, or null to fall
  // through to the normal query path.
  // ---------------------------------------------------------------------------
  const handleChatCommand = useCallback((rawInput) => {
    const cmd = rawInput.trim().toLowerCase();

    // ── HELP ──────────────────────────────────────────────────────────────────
    if (/^(\?|help|show help|how does this work|what can (i|you) do)$/.test(cmd)) {
      return `## Aurora Commands & Tips

[**↩ Back to Aurora chat**](/) — bookmark this page if you keep losing it.

**Navigation shortcuts** *(type to jump)*
| Command | Action |
|---|---|
| \`agents\` | Browse all Aurora content agents |
| \`my agents\` | Your personal AI agents |
| \`feed\` | Your personalised content feed |
| \`clear\` | Start a new chat |
| \`about\` | About Aurora |

**Tailor answers to you**
Set your role, interests, and how you'd like answers framed once in [your profile](/profile/preferences) — Aurora reads it on every query.

**Example queries**
- *"What's new with Wi-Fi 8 UHR in the last week?"*
- *"@wba show me the latest from all workgroups"*
- *"Compare Wi-Fi 7 and Wi-Fi 8 for dense deployments"*
- *"What did WBA publish about Smart MDUs?"*
- *"What's the latest 802.11bn draft?"*
`;
    }

    // ── AGENTS ────────────────────────────────────────────────────────────────
    if (/^(agents|list agents|show agents|all agents|available agents)$/.test(cmd)) {
      window.location.href = '/profile/agents';
      return `**Navigating to Agents…**\n\nYou can also go directly: [View all Aurora agents](/profile/agents)`;
    }

    // ── MY AGENTS ─────────────────────────────────────────────────────────────
    if (/^(my agents?|myagents?|personal agents?|my personal agents?)$/.test(cmd)) {
      window.location.href = '/profile/my-agents';
      return `**Navigating to My Agents…**\n\nYou can also go directly: [My Agents](/profile/my-agents)`;
    }

    // ── FEED ──────────────────────────────────────────────────────────────────
    if (/^(feed|my feed|show feed|content feed)$/.test(cmd)) {
      window.location.href = '/feed';
      return `**Navigating to Feed…**\n\nYou can also go directly: [Content Feed](/feed)`;
    }

    // ── CLEAR CHAT ────────────────────────────────────────────────────────────
    if (/^(clear|new chat|reset|reset chat|start over)$/.test(cmd)) {
      return '**Starting a new chat…**\n\nClick the **New Chat** button in the toolbar above to clear this conversation.';
    }

    // ── ABOUT ─────────────────────────────────────────────────────────────────
    if (/^(about|info|about aurora|what is aurora)$/.test(cmd)) {
      return `## About Aurora

**Aurora** is a RAG (Retrieval-Augmented Generation) knowledge assistant built for wireless standards professionals.

- **Knowledge graph**: Neo4j storing Wi-Fi Alliance, WBA Extranet, IETF, IEEE, and partner content
- **Dual pipeline**: Fast graph-based answers + baseline vector-search answers
- **Personalisation**: Answers weighted by your organisation, workgroup memberships, and topic interests
- **Creator agents**: AI personas that monitor workgroup activity and publish curated updates
- **Teams integration**: Query Aurora directly from Microsoft Teams

*Built by Extreme Networks · Aurora uses Azure OpenAI*`;
    }

    // Not a command — return null to proceed with Oracle search
    return null;
  }, []);

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

    // ── COMMAND ROUTING ──────────────────────────────────────────────────────
    // Intercept short commands before they reach Oracle search.
    // Commands are exact/near-exact matches — long questions always pass through.
    if (queryText.split(' ').length <= 6) {
      const commandResponse = handleChatCommand(queryText);
      if (commandResponse !== null) {
        setInputValue('');
        setShowMentionDropdown(false);
        setSelectedDatasources([]);
        // Add the user's command as a message so conversation history is preserved
        const userMsg = { role: 'user', content: queryText, timestamp: new Date() };
        const assistantMsg = { role: 'assistant', content: commandResponse, timestamp: new Date(), isWelcomeMessage: false };
        setMessages(prev => [...prev, userMsg, assistantMsg]);
        return;
      }
    }

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

    // Wipe server-side conversation memory so follow-up context doesn't bleed
    // from the cleared session into the next query. Best-effort — if the
    // endpoint is unreachable, the memory still expires via its 2-hour TTL.
    clearOracleConversation().catch((err) => {
      console.warn('Failed to clear server-side conversation memory:', err);
    });
  };

  return (
    <div className="chatbot-container">
      {/* Minimal floating control — only renders when there's something
          to dismiss. No background strip, just a ghost pill that picks
          up the page's dark mood. Hidden when the welcome message is
          the only thing on screen. */}
      {user && messages.length > 1 && (
        <div className="chat-controls-bar">
          <button
            className="chat-new-btn"
            onClick={handleNewChat}
            title="Start a new conversation"
          >
            <ChatIcon size={14} /> New chat
          </button>
        </div>
      )}
      {!user && (
        <div className="chat-controls-bar">
          <span className="chat-warning-inline">
            <WarningIcon size={14} /> Please log in to start chatting
          </span>
        </div>
      )}

      <div className="messages-panel">
        <div className="messages-container" ref={messagesContainerRef}>
          {/* Centered column wrapper */}
          <div className="messages-column">
            {messages.map((message, index) => (
              message.role === 'user' ? (
                /* ── User message — centered pill ───────────────────────────── */
                <div
                  key={index}
                  className="message-user-wrap"
                  ref={(el) => { messageRefs.current[index] = el; }}
                >
                  <div className="message-user-bubble">
                    {message.datasourceIds?.length > 0 && (
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
                </div>
              ) : (
                /* ── Assistant message — full-width prose ───────────────────── */
                <div
                  key={index}
                  className={`message-assistant-wrap${message.isError ? ' message-error' : ''}`}
                  ref={(el) => { messageRefs.current[index] = el; }}
                >
                  <div className="message-assistant-meta">
                    <span className="message-sender-name">Aurora</span>
                    <span className="message-time">
                      {(message.timestamp instanceof Date
                        ? message.timestamp
                        : new Date(message.timestamp)
                      ).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className="message-assistant-body" onCopy={(e) => {
                    const sel = window.getSelection();
                    if (!sel || sel.isCollapsed) return;
                    const text = sel.toString().replace(/\n+$/, '').replace(/^\n+/, '');
                    e.clipboardData.setData('text/plain', text);
                    e.preventDefault();
                  }}>
                    {/* Show typing dots inside the streaming placeholder while waiting for first token */}
                    {message.isStreaming && !message.content?.trim() && !message.documents?.length && !message.citations?.length && (
                      <div className="typing-indicator">
                        <span></span>
                        <span></span>
                        <span></span>
                      </div>
                    )}

                    {message.isError && (
                      <div className="message-text error">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                      </div>
                    )}

                    {!message.isError && !message.documents?.length && !message.citations?.length && (message.content?.trim() || message.isWelcomeMessage) && (
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

                    {!message.isError && (message.documents?.length > 0 || message.citations?.length > 0) && (
                      <QueryResultDisplay
                        message={message}
                        isAdmin={user?.role === 'admin' || user?.role === 'superadmin'}
                        onEnhance={() => handleEnhanceMessage(index)}
                        onToggleEnhanced={() => handleToggleEnhanced(index)}
                        isEnhancing={enhancingMessageIndex === index}
                        onFeedback={handleFeedback}
                        onSuggestionClick={(text) => executeQuery(text, [])}
                        onDisplayModeChange={(mode) => {
                          setMessages((prev) => {
                            const updated = [...prev];
                            updated[index] = { ...updated[index], displayMode: mode };
                            return updated;
                          });
                        }}
                      />
                    )}
                  </div>
                </div>
              )
            ))}

            {/* Only show the global loading indicator when there is NO streaming placeholder in the messages array
                (e.g. YouTube/ingest loading). The streaming Oracle flow shows dots inside the placeholder above. */}
            {isLoading && !messages.some(m => m.isStreaming) && (
              <div className="message-assistant-wrap">
                <div className="message-assistant-meta">
                  <span className="message-sender-name">Aurora</span>
                </div>
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>{/* end .messages-column */}
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
                    <Icon Component={LightbulbIcon} size={16} style={{ marginRight: '4px' }} /> Tip: Include topics (Wi-Fi 7, HaLow, Matter), organizations (Wi-Fi Alliance), or time context (last month)
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
        <div className="chat-input-inner">
          {/* Selected datasources */}
          {selectedDatasources.length > 0 && (
            <div className="selected-mentions">
              {selectedDatasources.map(ds => (
                <span key={ds.datasource_id} className="selected-mention">
                  @{ds.primary_alias || ds.datasource_id}
                  <button
                    type="button"
                    className="remove-mention"
                    onClick={() => handleRemoveDatasource(ds.datasource_id)}
                    aria-label={`Remove ${ds.name || ds.datasource_id}`}
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
              placeholder={user ? "Ask anything about Standards or Alliances … (use @datasource to filter)" : "Please log in first…"}
              rows="2"
              disabled={!user || isLoading || querySuggestion || backendStatus !== 'connected'}
            />
            <button
              type="submit"
              className="chat-send-btn"
              disabled={!user || !inputValue.trim() || isLoading || querySuggestion || backendStatus !== 'connected'}
              title="Send"
              aria-label="Send message"
            >
              {isLoading
                ? <HourglassIcon size={18} />
                : <SendIcon size={18} />
              }
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

export default Chatbot;
