/**
 * Unified Teams Tab Page
 * Combines Chat (left) and Feed (right) in a Teams-native layout
 * Responsive design: stacks vertically on mobile
 */

import React, { useState, useEffect, useRef } from 'react';
import './TeamsTab.css';
import { eventBus, ChatMessageEvent } from '../services/eventBus';
import { initializeTeamsSDK, notifyTeamsSuccess } from '../teams/teamsSdk';
import apiClient from '../api/client';

interface Message {
  id: string;
  type: 'user' | 'system' | 'assistant';
  content: string;
  author: string;
  timestamp: string;
  metadata?: Record<string, any>;
}

interface FeedItem {
  id: string;
  author: string;
  authorId: string;
  content: string;
  timestamp: string;
  likes: number;
  comments: number;
  liked: boolean;
}

interface TeamsTabProps {
  backendStatus?: string;
}

export const TeamsTab: React.FC<TeamsTabProps> = ({ backendStatus = 'connected' }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [feedItems, setFeedItems] = useState<FeedItem[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const feedEndRef = useRef<HTMLDivElement>(null);

  // Initialize Teams SDK and load initial data
  useEffect(() => {
    const initialize = async () => {
      try {
        // Initialize Teams SDK
        await initializeTeamsSDK();
        console.log('[TeamsTab] Teams SDK initialized');

        // Load chat history
        await loadChatHistory();

        // Load feed
        await loadFeed();

        // Connect to event bus for real-time updates
        eventBus.connect();

        // Notify Teams that content loaded successfully
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
  }, []);

  // Subscribe to event bus
  useEffect(() => {
    const unsubFeed = eventBus.onFeedUpdate(() => {
      // Feed update triggers chat message injection via event bus handler
      setUnreadCount((prev) => prev + 1);
    });

    const unsubChat = eventBus.onChatMessage((message) => {
      // Auto-inject system messages from feed updates
      const newMessage: Message = {
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

  const loadChatHistory = async () => {
    try {
      // Endpoint: GET /api/chat/history?limit=50&offset=0
      const response = await apiClient.get('/chat/history', {
        params: { limit: 50, offset: 0 },
      });

      const chatMessages = (response.data.messages || []).map((msg: any) => ({
        id: msg.id || `msg-${Date.now()}`,
        type: msg.type || 'assistant',
        content: msg.content,
        author: msg.author || 'Assistant',
        timestamp: msg.timestamp || new Date().toISOString(),
      }));

      setMessages(chatMessages);
    } catch (error) {
      console.error('[TeamsTab] Failed to load chat history:', error);
    }
  };

  const loadFeed = async () => {
    try {
      // Endpoint: GET /api/feed/timeline
      // Returns personalized feed for authenticated user
      const response = await apiClient.get('/feed/timeline', {
        params: { limit: 20, offset: 0 },
      });

      const feedData = (response.data.items || []).map((item: any) => ({
        id: item.id || `feed-${Date.now()}`,
        author: item.author || 'Unknown',
        authorId: item.authorId || '',
        content: item.content || '',
        timestamp: item.timestamp || new Date().toISOString(),
        likes: item.likes || 0,
        comments: item.comments || 0,
        liked: item.liked || false,
      }));

      setFeedItems(feedData);
      setUnreadCount(0);
    } catch (error) {
      console.error('[TeamsTab] Failed to load feed:', error);
    }
  };

  const sendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim()) return;

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      type: 'user',
      content: inputValue,
      author: 'You',
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');

    try {
      // Send to backend: POST /api/chat/query
      const response = await apiClient.post('/chat/query', {
        query: inputValue,
        conversationId: 'default', // Could extract from Teams context
      });

      const assistantMessage: Message = {
        id: `msg-${Date.now()}-response`,
        type: 'assistant',
        content: response.data.response || 'No response',
        author: 'Assistant',
        timestamp: new Date().toISOString(),
        metadata: {
          sources: response.data.sources,
          relatedTopics: response.data.relatedTopics,
        },
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error('[TeamsTab] Failed to send message:', error);
      const errorMessage: Message = {
        id: `msg-${Date.now()}-error`,
        type: 'system',
        content: 'Failed to get response. Please try again.',
        author: 'System',
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    }

    scrollToBottom('messages');
  };

  const scrollToBottom = (section: 'messages' | 'feed') => {
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
                  <div className="message-content">{msg.content}</div>
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
                    <time className="feed-time">
                      {new Date(item.timestamp).toLocaleDateString()}
                    </time>
                  </div>
                  <div className="feed-content">{item.content}</div>
                  <div className="feed-actions">
                    <button
                      className={`feed-action ${item.liked ? 'liked' : ''}`}
                      title="Like"
                    >
                      👍 {item.likes}
                    </button>
                    <button className="feed-action" title="Comment">
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
