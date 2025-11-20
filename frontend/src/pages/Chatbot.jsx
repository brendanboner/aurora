import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sendQuery } from '../services/api';
import { ProfileIcon, ChatIcon, BookIcon, BuildingIcon, WarningIcon, HourglassIcon, SendIcon, CalendarIcon } from '../components/icons';
import Icon from '../components/Icon.jsx';
import './Chatbot.css';

const Chatbot = ({ currentUser, backendStatus }) => {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    // Add welcome message
    if (messages.length === 0) {
      setMessages([
        {
          role: 'assistant',
          content: 'Hello! I\'m Aurora, your knowledge management assistant. Ask me anything about standards, events, and documents in our knowledge base.',
          timestamp: new Date(),
        },
      ]);
    }
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!inputValue.trim() || isLoading) return;

    if (!currentUser) {
      setError('Please select or create a user in the Admin page first.');
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
      const response = await sendQuery(currentUser.id, userMessage.content);

      const assistantMessage = {
        role: 'assistant',
        content: response.answer,
        timestamp: new Date(),
        filters: response.filters,
        documents: response.documents,
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

  return (
    <div className="chatbot-container">
      <div className="chat-header">
        <h1>Knowledge Assistant</h1>
        {currentUser && (
          <p className="chat-subtitle">
            Chatting as <strong>{currentUser.display_name || currentUser.email}</strong>
          </p>
        )}
        {!currentUser && (
          <p className="chat-warning">
            <Icon Component={WarningIcon} size={16} /> Please create or select a user in the Admin page to start chatting
          </p>
        )}
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

              {message.filters && (
                <div className="message-filters">
                  <strong>Applied Filters:</strong>
                  <div className="filter-tags">
                    {message.filters.start_date && (
                      <span className="tag">From: {message.filters.start_date}</span>
                    )}
                    {message.filters.end_date && (
                      <span className="tag">To: {message.filters.end_date}</span>
                    )}
                    {message.filters.topics?.map((topic, i) => (
                      <span key={i} className="tag"><BookIcon size={12} /> {topic}</span>
                    ))}
                    {message.filters.organisations?.map((org, i) => (
                      <span key={i} className="tag"><BuildingIcon size={12} /> {org}</span>
                    ))}
                    {message.filters.people?.map((person, i) => (
                      <span key={i} className="tag"><ProfileIcon size={12} /> {person}</span>
                    ))}
                  </div>
                </div>
              )}

              {message.documents && message.documents.length > 0 && (
                <div className="message-documents">
                  <strong>Referenced Documents ({message.documents.length}):</strong>
                  <div className="documents-list">
                    {message.documents.slice(0, 5).map((doc, i) => (
                      <div key={i} className="document-card">
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
                          <div className="document-date"><CalendarIcon size={12} /> {doc.publish_date}</div>
                        )}
                        {doc.summary && (
                          <div className="document-summary">{doc.summary}</div>
                        )}
                        {(doc.topics?.length > 0 || doc.organisations?.length > 0) && (
                          <div className="document-meta">
                            {doc.topics?.map((topic, j) => (
                              <span key={j} className="badge">{topic}</span>
                            ))}
                            {doc.organisations?.map((org, j) => (
                              <span key={j} className="badge">{org}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
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
          placeholder={currentUser ? "Ask me anything..." : "Please select a user first..."}
          rows="3"
          disabled={!currentUser || isLoading || backendStatus !== 'connected'}
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!currentUser || !inputValue.trim() || isLoading || backendStatus !== 'connected'}
        >
          {isLoading ? (<><HourglassIcon size={16} /> Thinking...</>) : (<><SendIcon size={16} /> Send</>)}
        </button>
      </form>
    </div>
  );
};

export default Chatbot;
