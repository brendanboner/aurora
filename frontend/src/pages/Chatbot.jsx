import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sendQuery } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import { ProfileIcon, ChatIcon, BookIcon, BuildingIcon, WarningIcon, HourglassIcon, SendIcon, CalendarIcon } from '../components/icons';
import ChevronLeftIcon from '../components/icons/ChevronLeftIcon';
import ChevronRightIcon from '../components/icons/ChevronRightIcon';
import Icon from '../components/Icon.jsx';
import './Chatbot.css';

const Chatbot = ({ backendStatus }) => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [currentDocumentIndex, setCurrentDocumentIndex] = useState({});
  const [conversationId, setConversationId] = useState(null);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    // Load chat history from localStorage when user changes
    if (!user) {
      // Show welcome message when no user is authenticated
      setMessages([
        {
          role: 'assistant',
          content: 'Hello! I\'m Aurora, your knowledge management assistant. Please log in to start chatting.',
          timestamp: new Date(),
        },
      ]);
      setConversationId(null);
      return;
    }

    // Load user-specific chat history and conversation ID
    const chatHistoryKey = `chatHistory_${user.user_id}`;
    const conversationIdKey = `conversationId_${user.user_id}`;
    const savedMessages = localStorage.getItem(chatHistoryKey);
    const savedConversationId = localStorage.getItem(conversationIdKey);
    
    // Restore conversation ID if it exists
    if (savedConversationId) {
      setConversationId(parseInt(savedConversationId, 10));
    }
    
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
            content: `Hello ${user.email}! I'm Aurora, your knowledge management assistant. Ask me anything about standards, events, and documents in our knowledge base.`,
            timestamp: new Date(),
          },
        ]);
      }
    } else {
      // Add welcome message for new user chat history
      setMessages([
        {
          role: 'assistant',
          content: `Hello ${user.email}! I'm Aurora, your knowledge management assistant. Ask me anything about standards, events, and documents in our knowledge base.`,
          timestamp: new Date(),
        },
      ]);
    }
  }, [user]);

  // Save messages to localStorage whenever they change (user-specific)
  useEffect(() => {
    if (user && messages.length > 0) {
      const chatHistoryKey = `chatHistory_${user.user_id}`;
      localStorage.setItem(chatHistoryKey, JSON.stringify(messages));
    }
  }, [messages, user]);

  // Save conversation ID to localStorage whenever it changes
  useEffect(() => {
    if (user && conversationId !== null) {
      const conversationIdKey = `conversationId_${user.user_id}`;
      localStorage.setItem(conversationIdKey, conversationId.toString());
    }
  }, [conversationId, user]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!inputValue.trim() || isLoading) return;

    if (!user) {
      setError('Please log in to start chatting.');
      return;
    }

    if (backendStatus !== 'connected') {
      setError('Backend is not connected. Please check your connection.');
      return;
    }

    const userMessage = {
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);
    setError(null);

    try {
      // Send query with conversation_id if we have one
      const response = await sendQuery(user.user_id, userMessage.content, conversationId);

      // Store the conversation_id from the response for subsequent messages
      setConversationId(response.conversation_id);

      const assistantMessage = {
        role: 'assistant',
        content: response.answer,
        timestamp: new Date(),
        filters: response.filters,
        documents: response.documents,
        messageId: response.message_id,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      console.error('Query error:', err);
      setError(err.response?.data?.detail || 'Failed to get response from backend');
      
      const errorMessage = {
        role: 'assistant',
        content: `Sorry, I encountered an error: ${err.response?.data?.detail || err.message}`,
        timestamp: new Date(),
        isError: true,
      };
      
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
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
      content: `Hello ${user.email}! I'm Aurora, your knowledge management assistant. Ask me anything about standards, events, and documents in our knowledge base.`,
      timestamp: new Date(),
    };
    
    setMessages([welcomeMessage]);
    setCurrentDocumentIndex({});
    setError(null);
    
    // Clear conversation_id to start a new conversation
    setConversationId(null);
    
    // Clear the saved chat history and conversation ID for this user
    const chatHistoryKey = `chatHistory_${user.user_id}`;
    const conversationIdKey = `conversationId_${user.user_id}`;
    localStorage.removeItem(chatHistoryKey);
    localStorage.removeItem(conversationIdKey);
  };

  return (
    <div className="chatbot-container">
      <div className="chat-header">
        <div className="chat-header-content">
          <div className="chat-header-text">
            <h1>Knowledge Assistant</h1>
            {user && (
              <p className="chat-subtitle">
                Chatting as <strong>{user.email}</strong>
              </p>
            )}
            {!user && (
              <p className="chat-warning">
                <Icon Component={WarningIcon} size={16} /> Please log in to start chatting
              </p>
            )}
          </div>
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
      </div>

      <div className="messages-container">
        {messages.map((message, index) => (
          <div key={index} className={`message message-${message.role}`}>
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
              <div className={`message-text ${message.isError ? 'error' : ''}`}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>

              {message.pipeline_debug && (
                <details className="pipeline-debug">
                  <summary>Pipeline Debug Info</summary>
                  <div className="debug-content">
                    <div className="debug-stage">
                      <strong>Stage 1: User Preferences</strong>
                      <div className="debug-info">
                        {message.pipeline_debug.stage_1_user_preferences.has_preferences ? (
                          <>
                            <div>Topics: {message.pipeline_debug.stage_1_user_preferences.topics_count}</div>
                            <div>Organizations: {message.pipeline_debug.stage_1_user_preferences.organisations_count}</div>
                            <div>People: {message.pipeline_debug.stage_1_user_preferences.people_count}</div>
                          </>
                        ) : (
                          <div>No user preferences set</div>
                        )}
                      </div>
                    </div>
                    
                    <div className="debug-stage">
                      <strong>Stage 2: LLM Filter Extraction</strong>
                      <div className="debug-info">
                        {message.pipeline_debug.stage_2_llm_extraction.topics?.length > 0 && (
                          <div>Topics: {message.pipeline_debug.stage_2_llm_extraction.topics.join(', ')}</div>
                        )}
                        {message.pipeline_debug.stage_2_llm_extraction.organisations?.length > 0 && (
                          <div>Organisations: {message.pipeline_debug.stage_2_llm_extraction.organisations.join(', ')}</div>
                        )}
                        {message.pipeline_debug.stage_2_llm_extraction.people?.length > 0 && (
                          <div>People: {message.pipeline_debug.stage_2_llm_extraction.people.join(', ')}</div>
                        )}
                        {message.pipeline_debug.stage_2_llm_extraction.category && (
                          <div>Category: {message.pipeline_debug.stage_2_llm_extraction.category}</div>
                        )}
                        {message.pipeline_debug.stage_2_llm_extraction.doc_type && (
                          <div>Doc Type: {message.pipeline_debug.stage_2_llm_extraction.doc_type}</div>
                        )}
                        <div>Date Range: {message.pipeline_debug.stage_2_llm_extraction.date_range}</div>
                        <div>Limit: {message.pipeline_debug.stage_2_llm_extraction.limit}</div>
                        {!message.pipeline_debug.stage_2_llm_extraction.topics?.length && 
                         !message.pipeline_debug.stage_2_llm_extraction.organisations?.length && 
                         !message.pipeline_debug.stage_2_llm_extraction.people?.length && (
                          <div className="no-filters">No filters extracted from query</div>
                        )}
                      </div>
                    </div>
                    
                    <div className="debug-stage">
                      <strong>Stage 3: Filter Merging</strong>
                      <div className="debug-info">
                        <div>Has Query Filters: {message.pipeline_debug.stage_3_filter_merging.has_query_filters ? 'Yes' : 'No'}</div>
                        <div>Applied User Prefs: {message.pipeline_debug.stage_3_filter_merging.applied_user_prefs ? 'Yes' : 'No'}</div>
                        <div>Final Topics: {message.pipeline_debug.stage_3_filter_merging.final_topics_count}</div>
                        <div>Final Organizations: {message.pipeline_debug.stage_3_filter_merging.final_orgs_count}</div>
                        <div>Final People: {message.pipeline_debug.stage_3_filter_merging.final_people_count}</div>
                      </div>
                    </div>
                    
                    <div className="debug-stage">
                      <strong>Stage 4: Document Retrieval</strong>
                      <div className="debug-info">
                        <div>Should Retrieve: {message.pipeline_debug.stage_4_document_retrieval.should_retrieve ? 'Yes' : 'No'}</div>
                        <div>Reason: {message.pipeline_debug.stage_4_document_retrieval.reason}</div>
                        <div>Documents Found: {message.pipeline_debug.stage_4_document_retrieval.documents_found}</div>
                      </div>
                    </div>
                  </div>
                </details>
              )}

              {message.documents && message.documents.length > 0 && (() => {
                const docIndex = currentDocumentIndex[index] || 0;
                const doc = message.documents[docIndex];
                
                // Format date to readable format
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
                const totalDocs = message.documents.length;
                
                return (
                  <div className="message-documents">
                    <div className="documents-header">
                      <strong>Referenced Documents ({totalDocs}):</strong>
                      {totalDocs > 1 && (
                        <div className="document-navigation">
                          <button
                            className="nav-button"
                            onClick={() => setCurrentDocumentIndex(prev => ({
                              ...prev,
                              [index]: Math.max(0, docIndex - 1)
                            }))}
                            disabled={docIndex === 0}
                            aria-label="Previous document"
                          >
                            <ChevronLeftIcon size={16} />
                          </button>
                          <span className="doc-counter">{docIndex + 1} / {totalDocs}</span>
                          <button
                            className="nav-button"
                            onClick={() => setCurrentDocumentIndex(prev => ({
                              ...prev,
                              [index]: Math.min(totalDocs - 1, docIndex + 1)
                            }))}
                            disabled={docIndex === totalDocs - 1}
                            aria-label="Next document"
                          >
                            <ChevronRightIcon size={16} />
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="document-carousel">
                      <div className="document-card">
                        <div className="document-title">
                          {doc.url ? (
                            <a href={doc.url} target="_blank" rel="noopener noreferrer">
                              {doc.title || 'Untitled Document'}
                            </a>
                          ) : (
                            doc.title || 'Untitled Document'
                          )}
                        </div>
                        {doc.publish_date && (
                          <div className="document-date"><CalendarIcon size={12} /> {formatDate(doc.publish_date)}</div>
                        )}
                        {doc.summary && (
                          <div className="document-summary">{doc.summary}</div>
                        )}
                        {(doc.topics?.length > 0 || doc.organisations?.length > 0) && (
                          <div className="document-meta">
                            {doc.topics?.slice(0, 5).map((topic, j) => (
                              <span key={j} className="badge">{topic}</span>
                            ))}
                            {doc.organisations?.slice(0, 3).map((org, j) => (
                              <span key={j} className="badge">{org}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}
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

      {error && (
        <div className="chat-error">
          <WarningIcon size={16} /> {error}
        </div>
      )}

      <form className="chat-input-form" onSubmit={handleSubmit}>
        <textarea
          className="chat-input"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder={user ? "Ask me anything..." : "Please log in first..."}
          rows="3"
          disabled={!user || isLoading || backendStatus !== 'connected'}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!user || !inputValue.trim() || isLoading || backendStatus !== 'connected'}
        >
          {isLoading ? (<><HourglassIcon size={16} /> Thinking...</>) : (<><SendIcon size={16} /> Send</>)}
        </button>
      </form>
    </div>
  );
};

export default Chatbot;
