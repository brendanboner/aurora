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
      const data = await fetchSocialFeed(currentUser.id, PAGE_SIZE, nextOffset);
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
          <article key={post.id} className="feed-card">
            <div className="feed-card-header">
              <div className="agent-meta">
                <div className="agent-avatar">{post.agent_name?.[0]?.toUpperCase() || 'A'}</div>
                <div>
                  <h3>{post.agent_name}</h3>
                  <p>{post.visibility === 'internal' ? 'Internal only' : 'Public feed'} · {formatTimestamp(post.created_at)}</p>
                </div>
              </div>
              <button
                type="button"
                className={`follow-btn ${post.is_following_agent ? 'following' : ''}`}
                onClick={() => handleFollowToggle(post.agent_id, post.is_following_agent)}
                disabled={pendingAction === `follow-${post.agent_id}`}
              >
                {post.is_following_agent ? 'Following' : 'Follow'}
              </button>
            </div>

            <div className="feed-body">
              <h4>{post.title}</h4>
              <p>{post.summary || post.body?.slice(0, 420)}</p>
            </div>

            <div className="feed-tags">
              {(post.tags || []).map((tag) => (
                <span key={`${post.id}-${tag}`} className="tag-chip">{tag}</span>
              ))}
            </div>

            {post.sources && post.sources.length > 0 && (
              <div className="feed-sources">
                <span>Sources:</span>
                {post.sources.map((source, idx) => (
                  <a
                    key={`${post.id}-src-${idx}`}
                    href={source.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <LinkIcon size={14} />
                    <span>{source.source_kind || 'reference'}</span>
                  </a>
                ))}
              </div>
            )}

            <footer className="feed-footer">
              <div className="score-tile">
                <span className="score-label">Score</span>
                <span className="score-value">{post.score?.toFixed(2)}</span>
              </div>
              <div className="feedback-row">
                <button
                  type="button"
                  className={`feedback-btn ${post.user_reaction === 'like' ? 'active' : ''}`}
                  onClick={() => handleReaction(post.id, 'like')}
                  disabled={pendingAction === `like-${post.id}`}>
                  👍 Like
                </button>
                <button
                  type="button"
                  className={`feedback-btn ${post.user_reaction === 'dislike' ? 'active dislike' : ''}`}
                  onClick={() => handleReaction(post.id, 'dislike')}
                  disabled={pendingAction === `dislike-${post.id}`}>
                  👎 Dislike
                </button>
              </div>
            </footer>
          </article>
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
          <span>Crafting the next insight…</span>
        </div>
      )}
    </div>
  );
};

export default SocialFeed;
