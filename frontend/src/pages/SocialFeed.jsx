import React, { useEffect, useMemo, useState } from 'react';
import './SocialFeed.css';
import { NewsIcon, StarIcon, RefreshIcon, LinkIcon } from '../components/icons';
import {
  fetchSocialFeed,
  likePost,
  dislikePost,
  followCreatorAgent,
  unfollowCreatorAgent,
  getPreferenceProfile,
} from '../services/api';

const PAGE_SIZE = 8;

const formatTimestamp = (value) => {
  try {
    return new Date(value).toLocaleString();
  } catch (err) {
    return value;
  }
};

const SocialFeed = ({ currentUser }) => {
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

  useEffect(() => {
    if (!currentUser) {
      setPosts([]);
      setOffset(0);
      setHasMore(false);
      setProfile(null);
      return;
    }
    refreshFeed();
    loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser?.id]);

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
  }, [sortOrder, debouncedSearch]);

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
        debouncedSearch || undefined
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

  const handleFollowToggle = async (agentId, isFollowing) => {
    if (!currentUser) {
      return;
    }
    setPendingAction(`follow-${agentId}`);
    try {
      if (isFollowing) {
        await unfollowCreatorAgent(agentId, currentUser.id);
      } else {
        await followCreatorAgent(agentId, currentUser.id);
      }
      setPosts((prev) =>
        prev.map((post) =>
          post.agent_id === agentId
            ? { ...post, is_following_agent: !isFollowing }
            : post
        )
      );
      await loadProfile();
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
        <div className="feed-title">
          <NewsIcon size={36} />
          <div>
            <h1>Creator Feed</h1>
            <p>Autonomous CreatorAgents summarise the latest standards intelligence just for you.</p>
          </div>
        </div>
        <div className="feed-actions">
          <div className="feed-toolbar">
            <input
              type="text"
              className="search-input"
              placeholder="Instant search posts..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
            <select
              className="sort-select"
              value={sortOrder}
              onChange={(e) => setSortOrder(e.target.value)}
            >
              <option value="relevance">Sort: Relevance</option>
              <option value="date">Sort: Most Recent</option>
            </select>
          </div>
          <button type="button" className="action-btn" onClick={refreshFeed} disabled={isLoading}>
            <RefreshIcon size={18} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            className="action-btn subtle"
            onClick={() => loadFeed({ reset: false })}
            disabled={isLoading || !hasMore}
          >
            <span>{hasMore ? 'Load more' : 'All caught up'}</span>
          </button>
        </div>
      </header>

      <section className="feed-context">
        <div className="profile-signal-card">
          <div className="signal-header">
            <StarIcon size={20} />
            <span>What the system thinks you care about</span>
          </div>
          {profileError && <p className="signal-error">{profileError}</p>}
          {highlightTopics.length > 0 ? (
            <div className="topic-chips">
              {highlightTopics.map(([topic, weight]) => (
                <span key={topic} className="topic-chip">
                  {topic}
                  <span className="chip-weight">{(weight * 100).toFixed(0)}%</span>
                </span>
              ))}
            </div>
          ) : (
            <p className="signal-placeholder">Interact with posts to teach the system faster.</p>
          )}
        </div>
      </section>

      {error && <div className="feed-error">{error}</div>}

      <section className="social-feed-grid">
        {posts.map((post) => (
          <PostCard
            key={post.id}
            post={post}
            currentUser={currentUser}
            pendingAction={pendingAction}
            onReaction={handleReaction}
            onFollowToggle={handleFollowToggle}
          />
        ))}

        {!isLoading && posts.length === 0 && (
          <div className="empty-feed-state">
            <p>No posts yet. Try refreshing or following more CreatorAgents.</p>
          </div>
        )}
      </section>

      {isLoading && (
        <div className="feed-loading">
          <div className="spinner" />
          <span>Loading professional insights…</span>
        </div>
      )}
    </div>
  );
};

// PostCard component for LinkedIn-style posts
const PostCard = ({ post, currentUser, pendingAction, onReaction, onFollowToggle }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const PREVIEW_LENGTH = 300;
  
  const needsReadMore = post.body && post.body.length > PREVIEW_LENGTH;
  const displayBody = isExpanded || !needsReadMore 
    ? post.body 
    : post.body?.slice(0, PREVIEW_LENGTH) + '...';

  return (
    <article className="professional-post-card">
      {/* Author Header */}
      <div className="post-author-header">
        <div className="author-info">
          <div className="author-avatar">
            {post.agent_name?.[0]?.toUpperCase() || 'A'}
          </div>
          <div className="author-details">
            <h3 className="author-name">{post.agent_name}</h3>
            <p className="author-meta">
              {post.created_at && formatTimestamp(post.created_at)}
            </p>
          </div>
        </div>
        <button
          type="button"
          className={`follow-button ${post.is_following_agent ? 'following' : ''}`}
          onClick={() => onFollowToggle(post.agent_id, post.is_following_agent)}
          disabled={pendingAction === `follow-${post.agent_id}`}
        >
          {post.is_following_agent ? '✓ Following' : '+ Follow'}
        </button>
      </div>

      {/* Post Content */}
      <div className="post-content">
        <h2 className="post-title">{post.title}</h2>
        <div className="post-body">
          {displayBody}
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

      {/* Sources/References */}
      {post.sources && post.sources.length > 0 && (
        <div className="post-sources">
          <div className="sources-header">
            <LinkIcon size={16} />
            <span>Referenced articles:</span>
          </div>
          <div className="source-links">
            {post.sources.map((source, idx) => (
              <a
                key={`${post.id}-src-${idx}`}
                href={source.url || '#'}
                target="_blank"
                rel="noopener noreferrer"
                className="source-link"
              >
                {source.title || source.source_identifier || `Source ${idx + 1}`}
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Engagement Footer */}
      <div className="post-engagement">
        <div className="engagement-stats">
          {post.score !== undefined && (
            <span className="relevance-score">
              Relevance: {(post.score * 100).toFixed(0)}%
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
        </div>
      </div>
    </article>
  );
};

export default SocialFeed;
