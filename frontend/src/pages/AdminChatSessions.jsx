import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getAllConversations, getConversationDetailAdmin } from '../services/api';
import './Admin.css';
import { ChatIcon, ProfileIcon, CalendarIcon, RefreshIcon } from '../components/icons';

const AdminChatSessions = () => {
  const [conversations, setConversations] = useState([]);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [conversationDetail, setConversationDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statistics, setStatistics] = useState(null);

  useEffect(() => {
    loadConversations();
  }, []);

  const loadConversations = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAllConversations(100);
      setConversations(data);
      
      // Calculate simple statistics
      const totalMessages = data.reduce((sum, conv) => sum + conv.message_count, 0);
      const uniqueUsers = new Set(data.map(conv => conv.user_id)).size;
      setStatistics({
        totalConversations: data.length,
        uniqueUsers: uniqueUsers,
        totalMessages: totalMessages,
        avgMessagesPerConversation: data.length > 0 ? (totalMessages / data.length).toFixed(1) : 0
      });
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadConversationDetail = async (conversationId) => {
    setDetailLoading(true);
    try {
      const data = await getConversationDetailAdmin(conversationId);
      setConversationDetail(data);
      setSelectedConversation(conversationId);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load conversation');
    } finally {
      setDetailLoading(false);
    }
  };

  const filteredConversations = conversations.filter(conv => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (
      conv.title?.toLowerCase().includes(term) ||
      conv.email?.toLowerCase().includes(term) ||
      conv.display_name?.toLowerCase().includes(term)
    );
  });

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString();
  };

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Chat Sessions</h1>
        <p>View and analyze user conversations with Aurora</p>
        <button className="btn btn-primary" onClick={loadConversations}>
          <RefreshIcon size={16} /> Refresh
        </button>
      </div>

      {error && <div className="admin-error">{error}</div>}

      {/* Statistics Cards */}
      {statistics && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Total Conversations</div>
            <div className="stat-value">{statistics.totalConversations}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Unique Users</div>
            <div className="stat-value">{statistics.uniqueUsers}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Total Messages</div>
            <div className="stat-value">{statistics.totalMessages}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Avg Messages/Conv</div>
            <div className="stat-value">{statistics.avgMessagesPerConversation}</div>
          </div>
        </div>
      )}

      {loading && <div className="spinner" />}

      {!loading && (
        <div className="chat-sessions-layout">
          {/* Left Panel - Conversations List */}
          <div className="conversations-panel">
            <div className="panel-header">
              <h2>Conversations ({filteredConversations.length})</h2>
              <input
                type="text"
                placeholder="Search by title, user..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="search-input"
              />
            </div>

            <div className="conversations-list">
              {filteredConversations.length === 0 ? (
                <div className="empty-state">
                  <ChatIcon size={48} />
                  <p>No conversations found</p>
                </div>
              ) : (
                filteredConversations.map(conv => (
                  <div
                    key={conv.id}
                    className={`conversation-item ${selectedConversation === conv.id ? 'selected' : ''}`}
                    onClick={() => loadConversationDetail(conv.id)}
                  >
                    <div className="conversation-header">
                      <div className="conversation-title">
                        <ChatIcon size={16} />
                        {conv.title || 'Untitled Conversation'}
                      </div>
                      <div className="message-count">{conv.message_count} msgs</div>
                    </div>
                    <div className="conversation-user">
                      <ProfileIcon size={14} />
                      {conv.display_name || conv.email}
                    </div>
                    <div className="conversation-date">
                      <CalendarIcon size={12} />
                      {formatDate(conv.updated_at)}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Right Panel - Conversation Detail */}
          <div className="conversation-detail-panel">
            {!selectedConversation && (
              <div className="empty-state">
                <ChatIcon size={64} />
                <p>Select a conversation to view messages</p>
              </div>
            )}

            {detailLoading && (
              <div className="spinner" />
            )}

            {selectedConversation && conversationDetail && !detailLoading && (
              <div className="conversation-detail">
                <div className="detail-header">
                  <div>
                    <h2>{conversationDetail.conversation.title || 'Untitled Conversation'}</h2>
                    <div className="detail-meta">
                      <span className="meta-item">
                        <ProfileIcon size={14} />
                        {conversationDetail.conversation.display_name || conversationDetail.conversation.email}
                      </span>
                      <span className="meta-item">
                        <CalendarIcon size={14} />
                        {formatDate(conversationDetail.conversation.created_at)}
                      </span>
                      <span className="meta-item">
                        {conversationDetail.messages.length} messages
                      </span>
                    </div>
                  </div>
                </div>

                <div className="messages-container">
                  {conversationDetail.messages.map((message, index) => (
                    <div key={message.id} className={`message message-${message.role}`}>
                      <div className="message-header">
                        <span className="message-role">
                          {message.role === 'user' ? <ProfileIcon size={16} /> : <ChatIcon size={16} />}
                          {message.role === 'user' ? 'User' : 'Assistant'}
                        </span>
                        <span className="message-time">
                          {new Date(message.created_at).toLocaleTimeString()}
                        </span>
                      </div>
                      <div className="message-content">
                        {message.role === 'assistant' ? (
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {message.content}
                          </ReactMarkdown>
                        ) : (
                          <p>{message.content}</p>
                        )}
                      </div>
                      {message.metadata && message.metadata.documents && message.metadata.documents.length > 0 && (
                        <div className="message-metadata">
                          <div className="metadata-label">Referenced Documents:</div>
                          <ul className="document-list">
                            {message.metadata.documents.slice(0, 3).map((doc, idx) => (
                              <li key={idx}>
                                <a href={doc.url} target="_blank" rel="noopener noreferrer">
                                  {doc.title || doc.url}
                                </a>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminChatSessions;
