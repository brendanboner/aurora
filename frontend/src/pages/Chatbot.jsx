import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sendOracleQuery, analyzeQuery, sendEnhanceQuery, getDatasources, submitOracleFeedback, getOracleSettings } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { ProfileIcon, ChatIcon, WarningIcon, HourglassIcon, SendIcon, SearchIcon, BuildingIcon, CalendarIcon, DocumentIcon, LightbulbIcon, SparkleIcon } from '../components/icons';
import Icon from '../components/Icon';
import QueryResultDisplay from '../components/QueryResultDisplay';
import DatasourceMention from '../components/DatasourceMention';
import './Chatbot.css';

const Chatbot = ({ backendStatus }) => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [queryMode, setQueryModeState] = useState(() => {
    const saved = localStorage.getItem('queryMode');
    return saved && ['retrieval', 'answer', 'auto'].includes(saved) ? saved : 'answer';
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
  const messageRefs = useRef({}); // Refs for each message element
  const skipNextScroll = useRef(false); // Flag to skip auto-scroll on toggle
  const inputRef = useRef(null); // Ref for textarea input

  // Wrapper to persist queryMode to localStorage
  const setQueryMode = (mode) => {
    setQueryModeState(mode);
    localStorage.setItem('queryMode', mode);
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

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  // Load datasources and Oracle settings on mount
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
    // Skip scroll if we just toggled enhanced/original
    if (skipNextScroll.current) {
      skipNextScroll.current = false;
      return;
    }
    scrollToBottom();
  }, [messages]);

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
        // Convert timestamp strings back to Date objects
        const messagesWithDates = parsed.map(msg => ({
          ...msg,
          timestamp: new Date(msg.timestamp)
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
      localStorage.setItem(chatHistoryKey, JSON.stringify(messages));
    }
  }, [messages, user]);

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

    try {
      // Send query to Oracle service with datasource filter
      const response = await sendOracleQuery(user.id, queryText, {
        mode: queryMode,
        maxDocuments: 10,
        includeGraphContext: true,
        datasourceIds: datasourceIds.length > 0 ? datasourceIds : null,
        personalize: personalizeMode,
        pipelineOverride: pipelineMode === 'system' ? null : pipelineMode,
      });

      // Map Oracle response format to our message format
      // Oracle returns: { query_id, mode, answer, citations, documents, graph_context, metadata, suggestions, confidence_score, personalization_applied, pipeline }
      const assistantMessage = {
        role: 'assistant',
        content: response.answer || (queryMode === 'retrieval' ? 'Here are the relevant documents:' : 'No answer was generated.'),
        timestamp: new Date(),
        queryId: response.query_id, // Store for feedback
        responseMode: response.mode, // 'retrieval' or 'answer'
        personalizationApplied: response.personalization_applied || false,
        pipeline: response.pipeline || null, // 'fast' or 'baseline' - track which pipeline was used
        citations: response.citations || [],
        documents: response.documents?.map(doc => ({
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
        })) || [],
        graphContext: response.graph_context,
        metadata: response.metadata,
        suggestions: response.suggestions || [],
        confidenceScore: response.confidence_score,
        originalQuery: queryText, // Store for enhance feature
        isEnhanced: false, // Track if this has been enhanced
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      console.error('Query error:', err);
      setError(err.response?.data?.detail?.message || err.response?.data?.detail || 'Failed to get response from Oracle service');
      
      const errorMessage = {
        role: 'assistant',
        content: `Sorry, I encountered an error: ${err.response?.data?.detail?.message || err.response?.data?.detail || err.message}`,
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
    // Prevent auto-scroll to bottom when toggling
    skipNextScroll.current = true;
    
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

  // Handle user accepting the suggested query
  const handleAcceptSuggestion = () => {
    const suggestedQuery = querySuggestion.suggested_query;
    const datasourceIds = pendingDatasourceIds;
    setQuerySuggestion(null);
    setPendingQuery(null);
    setPendingDatasourceIds([]);
    executeQuery(suggestedQuery, datasourceIds);
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
      content: forceRedigest ? '🔄 Re-processing YouTube video...' : '🎥 Processing YouTube video...',
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
    if (!inputValue.trim() || isLoading || querySuggestion) return;

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
    
    // Check if input is a YouTube URL
    const youtubePattern = /(https?:\/\/)?(www\.)?(youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
    const youtubeMatch = queryText.match(youtubePattern);
    
    if (youtubeMatch) {
      // Handle YouTube URL submission
      setInputValue('');
      setError(null);
      setShowMentionDropdown(false);
      
      await ingestYouTubeVideo(queryText, false);
      return;
    }
    
    setInputValue('');
    setError(null);
    setShowMentionDropdown(false);

    // Skip query analysis if fast pipeline is enabled
    if (fastPipelineEnabled) {
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
                title="Query mode"
              >
                <option value="answer">Query: Answer</option>
                <option value="retrieval">Query: Retrieval</option>
                <option value="auto">Query: Auto</option>
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

      <div className="messages-container">
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
