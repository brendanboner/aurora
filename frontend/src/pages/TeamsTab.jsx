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
import { initializeTeamsSDK, notifyTeamsSuccess, getTeamsSSOToken, getTeamsContext } from '../teams/teamsSdk';
import apiClient from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { fetchSocialFeed, likePost, fetchPostComments, addPostComment } from '../services/api';

// ─── Helpers ─────────────────────────────────────────────────────────────────

const AVATAR_PALETTE = [
  '#6264a7', '#0078d4', '#107c10', '#d83b01',
  '#881798', '#008272', '#ca5010', '#00b294',
];

const getAvatarColor = (name = '') => {
  const hash = [...name].reduce((acc, c) => acc + c.charCodeAt(0), 0);
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
};

const getAvatarInitials = (name = '') => {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

const timeAgo = (ts) => {
  if (!ts) return '';
  const diff = Math.floor((Date.now() - new Date(ts)) / 1000);
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(ts).toLocaleDateString();
};

const TtAvatar = ({ name = '', size = 'md', icon, style = {} }) => (
  <div
    className={`tt-avatar tt-avatar-${size}`}
    style={{ background: icon ? undefined : getAvatarColor(name), ...style }}
  >
    {icon ?? getAvatarInitials(name)}
  </div>
);

// ─── Component ────────────────────────────────────────────────────────────────

export const TeamsTab = ({ backendStatus = 'connected' }) => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [feedItems, setFeedItems] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  // Per-post comment state: { [postId]: { open: bool, comments: [], newComment: string, submitting: bool } }
  const [commentState, setCommentState] = useState({});
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef(null);
  const feedEndRef = useRef(null);

  const scrollToBottom = (section) => {
    const ref = section === 'messages' ? messagesEndRef : feedEndRef;
    ref.current?.scrollIntoView({ behavior: 'smooth' });
  };

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

        // Attempt silent SSO via Teams token exchange if we don't have a user yet.
        // This lets users inside Teams skip the Cognito redirect login flow.
        if (!user) {
          let ssoSucceeded = false;
          try {
            const ssoToken = await getTeamsSSOToken();
            if (ssoToken) {
              console.log('[TeamsTab] Exchanging Teams SSO token for Aurora session...');
              await apiClient.post('/auth/teams-sso', { token: ssoToken });
              ssoSucceeded = true;
              // Auth context will pick up the new session cookie on next status check
            }
          } catch (ssoError) {
            console.warn('[TeamsTab] Teams SSO exchange failed, trying email fallback:', ssoError?.message);
          }

          // Email fallback: if Azure SSO is not yet configured, try matching the
          // Teams userPrincipalName (corporate email) against Cognito-registered users.
          if (!ssoSucceeded) {
            try {
              const ctx = getTeamsContext();
              const upn = ctx.userPrincipalName || ctx.userId;
              if (upn) {
                console.log('[TeamsTab] Attempting email fallback for UPN:', upn);
                await apiClient.post('/auth/teams-email-fallback', { email: upn, upn });
                console.log('[TeamsTab] Email fallback auth succeeded for:', upn);
                // Auth context will pick up the new teams_session cookie
              }
            } catch (fallbackError) {
              const status = fallbackError?.response?.status;
              if (status === 404) {
                console.warn('[TeamsTab] Email fallback: no Aurora account for this Teams user. Ask an admin to add you.');
              } else if (status === 403) {
                console.warn('[TeamsTab] Email fallback disabled — Azure SSO credentials required.');
              } else {
                console.warn('[TeamsTab] Email fallback failed:', fallbackError?.message);
              }
            }
          }
        }

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
      setMessages((prev) => [...prev, {
        id: `msg-${Date.now()}-auth`,
        type: 'system',
        content: 'You need to be logged in to send messages. Please sign in to Aurora.',
        author: 'System',
        timestamp: new Date().toISOString(),
      }]);
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
    setIsTyping(true);

    try {
      const response = await apiClient.post('/oracle/query', {
        user_id: user.sub || user.id || user.user_id,
        question: inputValue,
        conversation_id: null,
      });

      const assistantMessage = {
        id: `msg-${Date.now()}-response`,
        type: 'assistant',
        content: response.data.answer || response.data.response || 'No response',
        author: 'Aurora',
        timestamp: new Date().toISOString(),
        metadata: {
          sources: response.data.sources,
          relatedTopics: response.data.related_topics,
        },
      };

      setIsTyping(false);
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error('[TeamsTab] Failed to send message:', error);
      setIsTyping(false);
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

  const handleLike = useCallback(async (itemId) => {
    if (!user) return;
    const userId = user.sub || user.id || user.user_id;
    try {
      await likePost(itemId, userId);
      setFeedItems((prev) =>
        prev.map((item) =>
          item.id === itemId
            ? { ...item, liked: !item.liked, likes: item.liked ? item.likes - 1 : item.likes + 1 }
            : item
        )
      );
    } catch (error) {
      console.error('[TeamsTab] Failed to like post:', error);
    }
  }, [user]);

  const toggleComments = useCallback(async (postId) => {
    setCommentState((prev) => {
      const current = prev[postId] || { open: false, comments: [], newComment: '', submitting: false };
      const nowOpen = !current.open;
      // Fetch comments when opening for the first time
      if (nowOpen && current.comments.length === 0) {
        fetchPostComments(postId)
          .then((comments) =>
            setCommentState((s) => ({
              ...s,
              [postId]: { ...s[postId], comments, open: true },
            }))
          )
          .catch((err) => console.error('[TeamsTab] Failed to load comments:', err));
        return { ...prev, [postId]: { ...current, open: true } };
      }
      return { ...prev, [postId]: { ...current, open: nowOpen } };
    });
  }, []);

  const handleCommentChange = useCallback((postId, value) => {
    setCommentState((prev) => ({
      ...prev,
      [postId]: { ...(prev[postId] || {}), newComment: value },
    }));
  }, []);

  const submitComment = useCallback(async (postId) => {
    if (!user) return;
    const userId = user.sub || user.id || user.user_id;
    const cs = commentState[postId] || {};
    const body = (cs.newComment || '').trim();
    if (!body) return;

    setCommentState((prev) => ({ ...prev, [postId]: { ...prev[postId], submitting: true } }));
    try {
      const newComment = await addPostComment(postId, userId, body, user.email);
      setCommentState((prev) => ({
        ...prev,
        [postId]: {
          ...prev[postId],
          comments: [...(prev[postId]?.comments || []), newComment],
          newComment: '',
          submitting: false,
        },
      }));
      setFeedItems((prev) =>
        prev.map((item) =>
          item.id === postId ? { ...item, comments: (item.comments || 0) + 1 } : item
        )
      );
    } catch (error) {
      console.error('[TeamsTab] Failed to submit comment:', error);
      setCommentState((prev) => ({ ...prev, [postId]: { ...prev[postId], submitting: false } }));
    }
  }, [user, commentState]);

  if (loading) {
    return (
      <div className="teams-tab loading">
        <div className="tt-spinner">
          <div className="tt-spinner-ring" />
        </div>
        <p>Loading Aurora…</p>
      </div>
    );
  }

  const userDisplayName = user?.name || user?.email || 'You';

  return (
    <div className="teams-tab">
      {/* ── App Header ── */}
      <header className="teams-tab-header">
        <div className="teams-header-brand">
          <span className="teams-header-icon">⚡</span>
          <span className="teams-header-title">Aurora</span>
          <span className="teams-header-subtitle">Wi-Fi Intelligence</span>
        </div>
        <div className="teams-header-right">
          <div className={`teams-header-status ${isConnected ? 'connected' : ''}`}>
            <span className="status-dot" />
            <span>{isConnected ? 'Live' : 'Polling'}</span>
          </div>
          {user && (
            <div className="teams-header-user">
              <TtAvatar name={userDisplayName} size="sm" />
              <span className="teams-header-username">{userDisplayName}</span>
            </div>
          )}
        </div>
      </header>

      <div className="teams-tab-container">
        {/* ── Chat Section ── */}
        <section className="chat-section">
          <div className="section-header">
            <h2>💬 Chat</h2>
            <span className={`backend-pill ${backendStatus === 'connected' ? 'ok' : 'err'}`}>
              {backendStatus === 'connected' ? 'Connected' : 'Offline'}
            </span>
          </div>

          <div className="messages-list">
            {messages.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">🔍</div>
                <p className="empty-title">Ask Aurora anything</p>
                <p className="empty-hint">
                  Wi-Fi standards, meetings, specifications — ask as if you were in the room.
                </p>
              </div>
            ) : (
              messages.map((msg) => (
                <div key={msg.id} className={`tt-message tt-message-${msg.type}`}>
                  {msg.type !== 'user' && (
                    <TtAvatar
                      name={msg.author}
                      size="sm"
                      icon={msg.type === 'assistant' ? '⚡' : '⚙'}
                      style={{ background: msg.type === 'assistant' ? '#6264a7' : '#ffb900' }}
                    />
                  )}
                  <div className="tt-msg-body">
                    <div className="tt-msg-meta">
                      <strong>{msg.author}</strong>
                      <time>{timeAgo(msg.timestamp)}</time>
                    </div>
                    <div className="message-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                    {msg.metadata?.sources?.length > 0 && (
                      <div className="message-sources">
                        📎 {msg.metadata.sources.join(' · ')}
                      </div>
                    )}
                  </div>
                  {msg.type === 'user' && (
                    <TtAvatar name={userDisplayName} size="sm" />
                  )}
                </div>
              ))
            )}

            {isTyping && (
              <div className="tt-message tt-message-assistant">
                <TtAvatar name="Aurora" size="sm" icon="⚡" style={{ background: '#6264a7' }} />
                <div className="tt-msg-body">
                  <div className="typing-indicator">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={sendMessage} className="chat-input-form">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Ask a question about Wi-Fi standards…"
              disabled={isTyping || (!isConnected && backendStatus !== 'connected')}
              className="chat-input"
            />
            <button
              type="submit"
              disabled={!inputValue.trim() || isTyping || (!isConnected && backendStatus !== 'connected')}
              className="send-button"
            >
              {isTyping ? '…' : 'Send'}
            </button>
          </form>
        </section>

        {/* ── Feed Section ── */}
        <section className="feed-section">
          <div className="section-header">
            <h2>
              📡 Agent Feed
              {unreadCount > 0 && <span className="unread-badge">{unreadCount}</span>}
            </h2>
            <button className="refresh-button" onClick={loadFeed} title="Refresh feed">↻</button>
          </div>

          <div className="feed-list">
            {feedItems.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon">📡</div>
                <p className="empty-title">No posts yet</p>
                <p className="empty-hint">
                  Agent posts will appear here once content is published.
                </p>
              </div>
            ) : (
              feedItems.map((item) => (
                <article key={item.id} className="feed-item">
                  <div className="feed-item-header">
                    <TtAvatar name={item.author} size="md" />
                    <div className="feed-author-meta">
                      <div className="feed-author">{item.author}</div>
                      <time className="feed-time">{timeAgo(item.timestamp)}</time>
                    </div>
                  </div>

                  {item.title && <div className="feed-title">{item.title}</div>}

                  <div className="feed-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown>
                  </div>

                  <div className="feed-actions">
                    <button
                      className={`feed-action ${item.liked ? 'liked' : ''}`}
                      onClick={() => handleLike(item.id)}
                    >
                      👍 <span>{item.likes}</span>
                    </button>
                    <button
                      className={`feed-action ${commentState[item.id]?.open ? 'active' : ''}`}
                      onClick={() => toggleComments(item.id)}
                    >
                      💬 <span>{item.comments}</span>
                    </button>
                  </div>

                  {commentState[item.id]?.open && (
                    <div className="feed-comments">
                      {(commentState[item.id]?.comments || []).map((c) => (
                        <div key={c.id} className="feed-comment">
                          <TtAvatar name={c.user_display_name || c.user_id || '?'} size="xs" />
                          <div className="comment-content">
                            <strong className="comment-author">
                              {c.user_display_name || c.user_id}
                            </strong>
                            <span className="comment-body">{c.body}</span>
                          </div>
                          <time className="comment-time">{timeAgo(c.created_at)}</time>
                        </div>
                      ))}
                      <div className="comment-input-row">
                        <TtAvatar name={userDisplayName} size="xs" />
                        <input
                          type="text"
                          className="comment-input"
                          placeholder="Add a comment…"
                          value={commentState[item.id]?.newComment || ''}
                          onChange={(e) => handleCommentChange(item.id, e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && submitComment(item.id)}
                          disabled={commentState[item.id]?.submitting}
                        />
                        <button
                          className="comment-submit"
                          onClick={() => submitComment(item.id)}
                          disabled={
                            !commentState[item.id]?.newComment?.trim() ||
                            commentState[item.id]?.submitting
                          }
                        >
                          Post
                        </button>
                      </div>
                    </div>
                  )}
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

