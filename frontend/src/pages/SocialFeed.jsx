import React, { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useAuth } from '../contexts/AuthContext';
import './SocialFeed.css';
import { NewsIcon, RefreshIcon, LinkIcon } from '../components/icons';
import {
  fetchSocialFeed,
  likePost,
  dislikePost,
  followCreatorAgent,
  unfollowCreatorAgent,
  getPreferenceProfile,
  getMyAgents,
  submitMyAgentPostFeedback,
  updateMyAgent,
} from '../services/api';

const PAGE_SIZE = 8;

const formatTimestamp = (value) => {
  try {
    return new Date(value).toLocaleString();
  } catch (err) {
    return value;
  }
};

const SocialFeed = () => {
  const { user: currentUser, loading: authLoading } = useAuth();
  const [posts, setPosts] = useState([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [profile, setProfile] = useState(null);
  const [profileError, setProfileError] = useState(null);
  const [pendingAction, setPendingAction] = useState(null);
  const [sortOrder, setSortOrder] = useState('relevance');
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [myAgents, setMyAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [agentFeedbackPendingId, setAgentFeedbackPendingId] = useState(null);

  useEffect(() => {
    if (authLoading) return;
    
    if (!currentUser) {
      setPosts([]);
      setOffset(0);
      setHasMore(false);
      setProfile(null);
      return;
    }
    refreshFeed();
    loadProfile();
    loadMyAgents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser?.id, authLoading]);

  // Debounce search input for instant search
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(searchTerm.trim()), 300);
    return () => clearTimeout(handle);
  }, [searchTerm]);

  // Refresh feed when sort or search changes
  useEffect(() => {
    if (!currentUser) return;
    setPosts([]);
    setOffset(0);
    setHasMore(true);
    loadFeed({ reset: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortOrder, debouncedSearch, selectedAgentId]);

  const loadProfile = async () => {
    if (!currentUser) {
      return;
    }
    try {
      const data = await getPreferenceProfile(currentUser.id);
      setProfile(data);
      setProfileError(null);
    } catch (err) {
      console.error('Preference profile error', err);
      setProfileError('Could not load personalised signals');
    }
  };

  const loadMyAgents = async () => {
    if (!currentUser) {
      setMyAgents([]);
      return;
    }
    try {
      const data = await getMyAgents();
      setMyAgents(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('MyAgents load failed', err);
    }
  };

  const loadFeed = async ({ reset = false } = {}) => {
    if (!currentUser || isLoading) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const nextOffset = reset ? 0 : offset;
      const data = await fetchSocialFeed(
        currentUser.id,
        PAGE_SIZE,
        nextOffset,
        sortOrder,
        debouncedSearch || undefined,
        selectedAgentId || undefined
      );
      const newPosts = reset ? data.posts : [...posts, ...(data.posts || [])];
      setPosts(newPosts);
      setOffset(data.next_offset ?? nextOffset + (data.posts?.length || 0));
      setHasMore(Boolean(data.next_offset));
    } catch (err) {
      console.error('Feed load failed', err);
      setError('Unable to load your feed right now.');
    } finally {
      setIsLoading(false);
    }
  };

  const refreshFeed = () => {
    setPosts([]);
    setOffset(0);
    setHasMore(true);
    loadFeed({ reset: true });
  };

  const handleAgentFilterChange = (e) => {
    setSelectedAgentId(e.target.value);
  };

  const handleReaction = async (postId, type) => {
    if (!currentUser) {
      return;
    }
    setPendingAction(`${type}-${postId}`);
    try {
      if (type === 'like') {
        await likePost(postId, currentUser.id);
      } else {
        await dislikePost(postId, currentUser.id);
      }
      setPosts((prev) =>
        prev.map((post) =>
          post.id === postId ? { ...post, user_reaction: type } : post
        )
      );
    } catch (err) {
      console.error('Reaction failed', err);
      setError('Unable to record your feedback.');
    } finally {
      setPendingAction(null);
    }
  };

  const handleFollowToggle = async (post) => {
    if (!currentUser) {
      return;
    }
    const pendingKey = `follow-${post.agent_type}-${post.agent_id}`;
    setPendingAction(pendingKey);
    try {
      if (post.agent_type === 'personal') {
        const nextFollowState = !post.is_following_agent;
        await updateMyAgent(post.agent_id, { show_in_feed: nextFollowState });
        setMyAgents((prev) =>
          prev.map((agent) =>
            String(agent.id) === String(post.agent_id)
              ? { ...agent, show_in_feed: nextFollowState }
              : agent
          )
        );
        setPosts((prev) =>
          prev.map((candidate) =>
            candidate.agent_type === 'personal' && String(candidate.agent_id) === String(post.agent_id)
              ? { ...candidate, is_following_agent: nextFollowState }
              : candidate
          )
        );
        await loadMyAgents();

        if (post.is_following_agent && selectedAgentId === String(post.agent_id)) {
          setPosts([]);
          setOffset(0);
          setHasMore(true);
          setSelectedAgentId('');
        }
      } else {
        if (post.is_following_agent) {
          await unfollowCreatorAgent(post.agent_id, currentUser.id);
        } else {
          await followCreatorAgent(post.agent_id, currentUser.id);
        }
        setPosts((prev) =>
          prev.map((candidate) =>
            candidate.agent_id === post.agent_id && candidate.agent_type === 'shared'
              ? { ...candidate, is_following_agent: !post.is_following_agent }
              : candidate
          )
        );
        await loadProfile();
      }
    } catch (err) {
      console.error('Follow toggle failed', err);
      setError('Unable to update follow state.');
    } finally {
      setPendingAction(null);
    }
  };

  const highlightTopics = useMemo(() => {
    if (!profile) {
      return [];
    }
    return Object.entries(profile.topic_weights || {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);
  }, [profile]);

  const visibleMyAgents = useMemo(
    () => myAgents.filter((agent) => agent.enabled !== false && agent.show_in_feed !== false),
    [myAgents]
  );

  const selectedAgent = useMemo(
    () => visibleMyAgents.find((agent) => String(agent.id) === String(selectedAgentId)),
    [visibleMyAgents, selectedAgentId]
  );

  const postsWithFollowState = useMemo(() => {
    const personalAgentFollowState = new Map(
      myAgents.map((agent) => [String(agent.id), agent.show_in_feed !== false])
    );

    return posts.map((post) => {
      if (post.agent_type !== 'personal') {
        return post;
      }

      const followState = personalAgentFollowState.get(String(post.agent_id));
      if (followState === undefined) {
        return post;
      }

      return { ...post, is_following_agent: followState };
    });
  }, [myAgents, posts]);

  const displayedPosts = useMemo(() => {
    if (!selectedAgentId) {
      return postsWithFollowState;
    }
    return postsWithFollowState.filter(
      (post) => post.agent_type === 'personal' && String(post.agent_id) === String(selectedAgentId)
    );
  }, [postsWithFollowState, selectedAgentId]);

  const handleAgentFeedback = async (postId, personalAgentId, feedbackType, comment) => {
    if (!currentUser || !personalAgentId || !feedbackType) return;
    setAgentFeedbackPendingId(postId);
    try {
      await submitMyAgentPostFeedback({
        agent_id: personalAgentId,
        post_id: postId,
        feedback_type: feedbackType,
        comment: comment || null,
      });
    } catch (err) {
      console.error('Agent feedback failed', err);
      setError('Unable to record feedback for this agent.');
    } finally {
      setAgentFeedbackPendingId(null);
    }
  };

  if (!currentUser) {
    return (
      <div className="social-feed-shell">
        <div className="social-feed-empty">
          <NewsIcon size={40} />
          <h2>Pick a user to unlock the feed</h2>
          <p>The personalised feed learns from each user&apos;s interests and feedback.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="social-feed-shell">
      <header className="social-feed-header">
        <div className="feed-title-row">
          <h1 className="feed-title-text">Creator Feed</h1>
        </div>
        <div className="feed-toolbar">
          <input
            type="text"
            className="feed-search"
            placeholder="Search posts…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          <select
            className="feed-select"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
          >
            <option value="relevance">Relevance</option>
            <option value="date">Most Recent</option>
          </select>
          {visibleMyAgents.length > 0 && (
            <select
              className="feed-select"
              value={selectedAgentId}
              onChange={handleAgentFilterChange}
            >
              <option value="">All agents</option>
              {visibleMyAgents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          )}
          <button type="button" className="feed-btn" onClick={refreshFeed} disabled={isLoading} title="Refresh feed">
            <RefreshIcon size={14} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            className="feed-btn"
            onClick={() => loadFeed({ reset: false })}
            disabled={isLoading || !hasMore}
          >
            <span>{hasMore ? 'Load more' : 'All caught up'}</span>
          </button>
        </div>
      </header>

      {selectedAgent && (
        <div className="feed-agent-banner">
          Showing only: <strong>{selectedAgent.name}</strong>
        </div>
      )}

      {error && <div className="feed-error">{error}</div>}

      <section className="social-feed-grid">
        {displayedPosts.map((post) => (
          <PostCard
            key={post.id}
            post={post}
            currentUser={currentUser}
            pendingAction={pendingAction}
            onReaction={handleReaction}
            onFollowToggle={handleFollowToggle}
            onAgentFeedback={handleAgentFeedback}
            agentFeedbackPendingId={agentFeedbackPendingId}
          />
        ))}

        {!isLoading && displayedPosts.length === 0 && (
          <div className="empty-feed-state">
            <p>
              {selectedAgent
                ? `No posts yet for ${selectedAgent.name}.`
                : 'No posts yet. Try refreshing or following more CreatorAgents.'}
            </p>
          </div>
        )}
      </section>

      {isLoading && (
        <div className="feed-loading">
          <div className="spinner" />
          <span>Loading…</span>
        </div>
      )}
    </div>
  );
};

// PostCard component for LinkedIn-style posts
const PostCard = ({ post, currentUser, pendingAction, onReaction, onFollowToggle, onAgentFeedback, agentFeedbackPendingId }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [showAgentFeedback, setShowAgentFeedback] = useState(false);
  const [agentFeedbackType, setAgentFeedbackType] = useState('');
  const [agentFeedbackComment, setAgentFeedbackComment] = useState('');
  const [agentFeedbackSubmitted, setAgentFeedbackSubmitted] = useState(false);
  const PREVIEW_LENGTH = 300;
  
  const needsReadMore = post.body && post.body.length > PREVIEW_LENGTH;
  const displayBody = isExpanded || !needsReadMore 
    ? post.body 
    : post.body?.slice(0, PREVIEW_LENGTH) + '...';

  const isMyAgentPost = post.agent_type === 'personal';
  const followButtonLabel = isMyAgentPost
    ? (post.is_following_agent ? 'Unfollow' : 'Follow')
    : (post.is_following_agent ? '✓ Following' : '+ Follow');

  const handleSubmitAgentFeedback = () => {
    if (!isMyAgentPost || !agentFeedbackType || !onAgentFeedback) return;
    onAgentFeedback(post.id, post.agent_id, agentFeedbackType, agentFeedbackComment);
    setAgentFeedbackSubmitted(true);
    setShowAgentFeedback(false);
    setAgentFeedbackType('');
    setAgentFeedbackComment('');
  };

  return (
    <article className={`professional-post-card ${isMyAgentPost ? 'my-agent-post-card' : ''}`}>
      {isMyAgentPost && (
        <div className="personal-agent-banner">
          <strong>My Agent</strong>
        </div>
      )}
      {/* Author Header */}
      <div className="post-author-header">
        <div className="author-info">
          <div className="author-avatar">
            {post.agent_name?.[0]?.toUpperCase() || 'A'}
          </div>
          <div className="author-details">
            <h3 className="author-name">
              {post.agent_name}
            </h3>
            <p className="author-meta">
              {post.created_at && formatTimestamp(post.created_at)}
            </p>
          </div>
        </div>
        <button
          type="button"
          className={`follow-button ${post.is_following_agent ? 'following' : ''}`}
          onClick={() => onFollowToggle(post)}
          disabled={pendingAction === `follow-${post.agent_type}-${post.agent_id}`}
          title={
            isMyAgentPost
              ? (post.is_following_agent
                  ? 'You are following this personal agent. Click to unfollow it from your feed.'
                  : 'Follow this personal agent in your feed.')
              : undefined
          }
        >
          {followButtonLabel}
        </button>
      </div>

      {/* Post Content */}
      <div className="post-content">
        <h2 className="post-title">{post.title}</h2>
        <div className="post-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {displayBody}
          </ReactMarkdown>
          {needsReadMore && (
            <button 
              className="read-more-btn"
              onClick={() => setIsExpanded(!isExpanded)}
            >
              {isExpanded ? '...see less' : '...see more'}
            </button>
          )}
        </div>
      </div>

      {/* Tags */}
      {post.tags && post.tags.length > 0 && (
        <div className="post-tags">
          {post.tags.slice(0, 5).map((tag) => (
            <span key={`${post.id}-${tag}`} className="post-tag">
              #{tag.replace(/\s+/g, '')}
            </span>
          ))}
        </div>
      )}

      {/* Sources/References — collapsed by default */}
      {post.sources && post.sources.length > 0 && (
        <div className="post-sources">
          <button
            type="button"
            className="sources-toggle"
            onClick={() => setShowSources((s) => !s)}
          >
            <LinkIcon size={13} />
            <span>{showSources ? 'Hide' : 'Show'} {post.sources.length} source{post.sources.length !== 1 ? 's' : ''}</span>
            <span className="sources-chevron">{showSources ? '▲' : '▼'}</span>
          </button>
          {showSources && (
            <div className="source-links">
              {post.sources.map((source, idx) => {
                const computeLabel = () => {
                  const id = (source.source_identifier || '').toString().trim();
                  const title = (source.title || '').toString().trim();
                  const url = (source.url || '').toString().trim();
                  if (title && title.toLowerCase() !== 'url') return title;
                  if (url) {
                    try {
                      const u = new URL(url);
                      return u.hostname.replace(/^www\./, '');
                    } catch {
                      return url.length > 60 ? url.slice(0, 57) + '…' : url;
                    }
                  }
                  if (id) {
                    if (id.toLowerCase() === 'url') return `Source ${idx + 1}`;
                    if (/^https?:\/\//i.test(id)) {
                      try {
                        const u = new URL(id);
                        return u.hostname.replace(/^www\./, '');
                      } catch {
                        return id.length > 60 ? id.slice(0, 57) + '…' : id;
                      }
                    }
                    return id;
                  }
                  return `Source ${idx + 1}`;
                };
                const label = computeLabel();
                const href = source.url || (/^https?:\/\//i.test(source.source_identifier || '') ? source.source_identifier : '#');
                return (
                  <a
                    key={`${post.id}-src-${idx}`}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="source-link"
                  >
                    {label}
                  </a>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Engagement Footer */}
      <div className="post-engagement">
        <div className="engagement-stats">
          {(post.normalized_score !== undefined && post.normalized_score !== null) && (
            <span className="relevance-score">
              {(() => {
                const base = post.normalized_score || 0;
                const pct = Math.max(0, Math.min(100, Math.round(base * 100)));
                return `Relevance: ${pct}%`;
              })()}
            </span>
          )}
        </div>
        <div className="engagement-actions">
          <button
            type="button"
            className={`engagement-btn ${post.user_reaction === 'like' ? 'active-like' : ''}`}
            onClick={() => onReaction(post.id, 'like')}
            disabled={pendingAction === `like-${post.id}`}
          >
            <span className="emoji">👍</span>
            <span>Helpful</span>
          </button>
          <button
            type="button"
            className={`engagement-btn ${post.user_reaction === 'dislike' ? 'active-dislike' : ''}`}
            onClick={() => onReaction(post.id, 'dislike')}
            disabled={pendingAction === `dislike-${post.id}`}
          >
            <span className="emoji">👎</span>
            <span>Not relevant</span>
          </button>
          {isMyAgentPost && (
            <button
              type="button"
              className="engagement-btn subtle-agent-feedback"
              onClick={() => setShowAgentFeedback((prev) => !prev)}
              disabled={agentFeedbackSubmitted}
            >
              <span>Provide feedback to this agent</span>
            </button>
          )}
        </div>
      </div>

      {isMyAgentPost && showAgentFeedback && !agentFeedbackSubmitted && (
        <div className="agent-feedback-panel">
          <div className="agent-feedback-row">
            <label className="agent-feedback-choice">
              <input
                type="radio"
                name={`agent-feedback-${post.id}`}
                value="on_topic"
                checked={agentFeedbackType === 'on_topic'}
                onChange={(e) => setAgentFeedbackType(e.target.value)}
              />
              <span>On-topic and useful</span>
            </label>
            <label className="agent-feedback-choice">
              <input
                type="radio"
                name={`agent-feedback-${post.id}`}
                value="off_topic"
                checked={agentFeedbackType === 'off_topic'}
                onChange={(e) => setAgentFeedbackType(e.target.value)}
              />
              <span>Off-topic for this project</span>
            </label>
          </div>
          <textarea
            className="agent-feedback-textarea"
            rows={2}
            placeholder="Optional: add a note so the agent can adjust next time."
            value={agentFeedbackComment}
            onChange={(e) => setAgentFeedbackComment(e.target.value)}
          />
          <div className="agent-feedback-actions">
            <button
              type="button"
              className="engagement-btn primary-feedback"
              onClick={handleSubmitAgentFeedback}
              disabled={!agentFeedbackType || agentFeedbackPendingId === post.id}
            >
              <span>Send feedback</span>
            </button>
            <button
              type="button"
              className="engagement-btn subtle"
              onClick={() => setShowAgentFeedback(false)}
            >
              <span>Cancel</span>
            </button>
          </div>
        </div>
      )}
    </article>
  );
};

export default SocialFeed;
