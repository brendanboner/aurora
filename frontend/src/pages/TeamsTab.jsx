/**
 * Unified Teams Tab Page
 * Combines Chat (left) and Feed (right) in a Teams-native layout
 * Responsive design: stacks vertically on mobile
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import './TeamsTab.css';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { eventBus } from '../services/eventBus';
import { initializeTeamsSDK, notifyTeamsSuccess } from '../teams/teamsSdk';
import apiClient from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { fetchSocialFeed } from '../services/api';

export const TeamsTab = ({ backendStatus = 'connected' }) => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [feedItems, setFeedItems] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const messagesEndRef = useRef(null);
  const feedEndRef = useRef(null);

  // Subscribe to event bus
  useEffect(() => {
    const unsubFeed = eventBus.onFeedUpdate(() => {
      // Feed update triggers chat message injection via event bus handler
      setUnreadCount((prev) => prev + 1);
    });

    const unsubChat = eventBus.onChatMessage((message) => {
      // Auto-inject system messages from feed updates
      const newMessage = {
        id: message.id,
        type: message.type === 'system' ? 'system' : 'assistant',
        content: message.content,
        author: message.author,
        timestamp: message.timestamp,
        metadata: {
          isSystemGenerated: message.isSystemGenerated,
        },
      };
      setMessages((prev) => [...prev, newMessage]);
      scrollToBottom('messages');
    });

    const unsubConnection = eventBus.onConnectionStatus((status) => {
      setIsConnected(status);
    });

    return () => {
      unsubFeed();
      unsubChat();
      unsubConnection();
    };
  }, []);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    scrollToBottom('messages');
  }, [messages]);

  useEffect(() => {
    scrollToBottom('feed');
  }, [feedItems]);

  const loadChatHistory = useCallback(async () => {
    try {
      // TODO: Implement chat history endpoint in backend
      // For now, we'll just start with an empty chat
      // The /query endpoint creates conversations, so subsequent messages are stored
      console.log('[TeamsTab] Chat history not yet implemented - starting with empty chat');
    } catch (error) {
      console.error('[TeamsTab] Failed to load chat history:', error);
    }
  }, []);

  const loadFeed = useCallback(async () => {
    if (!user) {
      setFeedItems([]);
      setUnreadCount(0);
      return;
    }

    try {
      // Endpoint: GET /api/content_creator_service/feed
      // Returns personalized feed for authenticated user
      const data = await fetchSocialFeed(user.sub || user.id || user.user_id, 20, 0);
      
      const feedData = (data.posts || data.items || []).map((post) => ({
        id: post.id || `feed-${Date.now()}`,
        author: post.agent_name || post.author?.name || post.author || 'Unknown',
        authorId: post.agent_id || post.author?.id || post.authorId || '',
        content: post.body || post.content || post.text || '',
        title: post.title || '',
        timestamp: post.created_at || post.timestamp || new Date().toISOString(),
        likes: post.like_count || post.likes || 0,
        comments: post.comment_count || post.comments || 0,
        liked: post.liked_by_user || post.liked || false,
        isFollowing: post.is_following_agent || false,
      }));

      setFeedItems(feedData);
      setUnreadCount(0);
      console.log('[TeamsTab] Loaded', feedData.length, 'feed items');
    } catch (error) {
      console.error('[TeamsTab] Failed to load feed:', error);
      // Don't show error to user - just log it
    }
  }, [user]);

  // Initialize Teams SDK and load initial data
  useEffect(() => {
    const initialize = async () => {
      try {
        await initializeTeamsSDK();
        console.log('[TeamsTab] Teams SDK initialized');

        await loadChatHistory();
        await loadFeed();

        eventBus.connect();
        notifyTeamsSuccess();
        setLoading(false);
      } catch (error) {
        console.error('[TeamsTab] Initialization failed:', error);
        setLoading(false);
      }
    };

    initialize();

    return () => {
      eventBus.disconnect();
    };
  }, [loadChatHistory, loadFeed]);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    // Get user ID from auth context
    if (!user) {
      console.error('[TeamsTab] User not authenticated');
      return;
    }

    const userMessage = {
      id: `msg-${Date.now()}`,
      type: 'user',
      content: inputValue,
      author: 'You',
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');

    try {
      // Send to backend: POST /api/oracle/query
      // Uses the Oracle service for question-answering
      // Endpoint requires: user_id, question, optional conversation_id
      const response = await apiClient.post('/oracle/query', {
        user_id: user.sub || user.id || user.user_id,  // Cognito stores ID as 'sub'
        question: inputValue,
        conversation_id: null, // Will create new conversation
      });

      const assistantMessage = {
        id: `msg-${Date.now()}-response`,
        type: 'assistant',
        content: response.data.answer || response.data.response || 'No response',
        author: 'Assistant',
        timestamp: new Date().toISOString(),
        metadata: {
          sources: response.data.sources,
          relatedTopics: response.data.related_topics,
        },
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error('[TeamsTab] Failed to send message:', error);
      console.error('[TeamsTab] Error details:', error.response?.data);
      const errorMessage = {
        id: `msg-${Date.now()}-error`,
        type: 'system',
        content: `Failed to get response: ${error.response?.data?.detail || error.message}. Please try again.`,
        author: 'System',
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    }

    scrollToBottom('messages');
  };

  const scrollToBottom = (section) => {
    const ref = section === 'messages' ? messagesEndRef : feedEndRef;
    ref.current?.scrollIntoView({ behavior: 'smooth' });
  };

  if (loading) {
    return <div className="teams-tab loading">Loading...</div>;
  }

  return (
    <div className="teams-tab">
      {/* Connection Status Indicator */}
      <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
        <span className="status-dot"></span>
        <span>{isConnected ? 'Real-time updates' : 'Using polling mode'}</span>
      </div>

      <div className="teams-tab-container">
        {/* Chat Section */}
        <section className="chat-section">
          <div className="section-header">
            <h2>Chat</h2>
            <span className="backend-status" title={`Backend: ${backendStatus}`}>
              {backendStatus === 'connected' ? '✓' : '✗'}
            </span>
          </div>

          <div className="messages-list">
            {messages.length === 0 ? (
              <div className="empty-state">
                <p>Start a conversation by asking a question below.</p>
              </div>
            ) : (
              messages.map((msg) => (
                <div key={msg.id} className={`message message-${msg.type}`}>
                  <div className="message-header">
                    <strong className="message-author">{msg.author}</strong>
                    <time className="message-time">
                      {new Date(msg.timestamp).toLocaleTimeString()}
                    </time>
                  </div>
                  <div className="message-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                  {msg.metadata?.sources && (
                    <div className="message-sources">
                      Sources: {msg.metadata.sources.join(', ')}
                    </div>
                  )}
                </div>
              ))
            )}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={sendMessage} className="chat-input-form">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Ask a question..."
              disabled={!isConnected && backendStatus !== 'connected'}
              className="chat-input"
            />
            <button
              type="submit"
              disabled={!inputValue.trim() || (!isConnected && backendStatus !== 'connected')}
              className="send-button"
            >
              Send
            </button>
          </form>
        </section>

        {/* Feed Section */}
        <section className="feed-section">
          <div className="section-header">
            <h2>
              Feed
              {unreadCount > 0 && <span className="unread-badge">{unreadCount}</span>}
            </h2>
            <button className="refresh-button" onClick={loadFeed} title="Refresh feed">
              ↻
            </button>
          </div>

          <div className="feed-list">
            {feedItems.length === 0 ? (
              <div className="empty-state">
                <p>No feed items yet.</p>
              </div>
            ) : (
              feedItems.map((item) => (
                <article key={item.id} className="feed-item">
                  <div className="feed-item-header">
                    <div className="feed-author">{item.author}</div>
                    <time className="feed-time" title={new Date(item.timestamp).toLocaleString()}>
                      {new Date(item.timestamp).toLocaleDateString()}
                    </time>
                  </div>
                  {item.title && <div className="feed-title">{item.title}</div>}
                  <div className="feed-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {item.content}
                    </ReactMarkdown>
                  </div>
                  <div className="feed-actions">
                    <button
                      className={`feed-action ${item.liked ? 'liked' : ''}`}
                      title="Like"
                      onClick={() => console.log('Like:', item.id)}
                    >
                      👍 {item.likes}
                    </button>
                    <button 
                      className="feed-action" 
                      title="Comment"
                      onClick={() => console.log('Comment:', item.id)}
                    >
                      💬 {item.comments}
                    </button>
                  </div>
                </article>
              ))
            )}
            <div ref={feedEndRef} />
          </div>
        </section>
      </div>
    </div>
  );
};

export default TeamsTab;
