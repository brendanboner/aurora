import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { 
  getCreatorAgents,
  followCreatorAgent, 
  unfollowCreatorAgent,
  getUserFollowedAgents,
  updateAgentPreferences 
} from '../services/api';
import './AgentPreferences.css';

function AgentPreferences() {
  const { user, loading: authLoading } = useAuth();
  const [allAgents, setAllAgents] = useState([]);
  const [followedAgents, setFollowedAgents] = useState([]);
  const [agentPreferences, setAgentPreferences] = useState({});
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  const loadAgents = useCallback(async () => {
    if (!user?.id) {
      setStatusMessage('User not authenticated');
      setIsLoading(false);
      return;
    }
    
    setIsLoading(true);
    try {
      const [allAgentsData, followedData] = await Promise.all([
        getCreatorAgents(false), // Only enabled agents
        getUserFollowedAgents(user.id)
      ]);
      
      setAllAgents(allAgentsData);
      setFollowedAgents(followedData.agents || []);
      
      // Build preferences map from followed agents
      const prefs = {};
      (followedData.agents || []).forEach(agent => {
        prefs[agent.id] = {
          relevance: agent.relevance || 0.5,
          lengthPreference: agent.length_preference || 'medium'
        };
      });
      setAgentPreferences(prefs);
    } catch (err) {
      console.error('Failed to load agents:', err);
      setStatusMessage('Failed to load agents');
    } finally {
      setIsLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (!authLoading && user) {
      loadAgents();
    }
  }, [user, authLoading, loadAgents]);

  useEffect(() => {
    // Clear status message after 3 seconds
    const timer = statusMessage ? setTimeout(() => setStatusMessage(''), 3000) : null;
    return () => timer && clearTimeout(timer);
  }, [statusMessage]);

  const isFollowing = (agentId) => {
    return followedAgents.some(a => a.id === agentId);
  };

  const handleFollow = async (agentId) => {
    if (!user?.id) return;
    
    try {
      await followCreatorAgent(agentId, user.id);
      setAgentPreferences(prev => ({
        ...prev,
        [agentId]: { relevance: 0.5, lengthPreference: 'medium' }
      }));
      await loadAgents();
      setStatusMessage('Followed agent successfully');
    } catch (err) {
      console.error('Follow failed:', err);
      setStatusMessage('Failed to follow agent');
    }
  };

  const handleUnfollow = async (agentId) => {
    if (!user?.id) return;
    
    try {
      await unfollowCreatorAgent(agentId, user.id);
      setAgentPreferences(prev => {
        const updated = { ...prev };
        delete updated[agentId];
        return updated;
      });
      await loadAgents();
      setStatusMessage('Unfollowed agent successfully');
    } catch (err) {
      console.error('Unfollow failed:', err);
      setStatusMessage('Failed to unfollow agent');
    }
  };

  const handleRelevanceChange = async (agentId, value) => {
    const relevance = parseFloat(value);
    setAgentPreferences(prev => ({
      ...prev,
      [agentId]: { ...prev[agentId], relevance }
    }));

    if (!user?.id) return;

    try {
      await updateAgentPreferences(
        agentId, 
        user.id, 
        relevance, 
        agentPreferences[agentId]?.lengthPreference || 'medium'
      );
    } catch (err) {
      console.error('Failed to update relevance:', err);
    }
  };

  const handleLengthChange = async (agentId, value) => {
    setAgentPreferences(prev => ({
      ...prev,
      [agentId]: { ...prev[agentId], lengthPreference: value }
    }));

    if (!user?.id) return;

    try {
      await updateAgentPreferences(
        agentId, 
        user.id, 
        agentPreferences[agentId]?.relevance || 0.5,
        value
      );
    } catch (err) {
      console.error('Failed to update length preference:', err);
    }
  };

  if (isLoading) {
    return (
      <div className="agent-preferences-container loading">
        <div className="spinner"></div>
        <p>Loading agents...</p>
      </div>
    );
  }

  return (
    <div className="agent-preferences-container">
      <div className="agent-preferences-header">
        <h1>Follow Creator Agents</h1>
        <p>
          Choose which AI agents to follow and customize your content preferences. 
          Relevance controls how much weight their posts have in your feed, and length 
          preference influences the content style you receive.
        </p>
        {statusMessage && <div className="status-message">{statusMessage}</div>}
      </div>

      <div className="agents-list">
        {allAgents.map(agent => {
          const following = isFollowing(agent.id);
          const prefs = agentPreferences[agent.id] || { relevance: 0.5, lengthPreference: 'medium' };

          return (
            <div key={agent.id} className={`agent-card ${following ? 'following' : ''}`}>
              <div className="agent-info">
                <div className="agent-header">
                  <h3>{agent.name}</h3>
                  <button 
                    className={`follow-btn ${following ? 'unfollow' : 'follow'}`}
                    onClick={() => following ? handleUnfollow(agent.id) : handleFollow(agent.id)}
                  >
                    {following ? 'Unfollow' : 'Follow'}
                  </button>
                </div>
                <p className="agent-description">{agent.description || 'No description provided.'}</p>
                
                {agent.persona && (
                  <p className="agent-persona">
                    <strong>Persona:</strong> {agent.persona}
                  </p>
                )}

                <div className="agent-meta">
                  <span>Cadence: {agent.posting_cadence}</span>
                  <span>Default Length: {agent.content_length_preference}</span>
                </div>
              </div>

              {following && (
                <div className="agent-preferences">
                  <div className="preference-control">
                    <label>
                      <span className="pref-label">Relevance</span>
                      <span className="pref-value">{(prefs.relevance * 100).toFixed(0)}%</span>
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={prefs.relevance}
                      onChange={(e) => handleRelevanceChange(agent.id, e.target.value)}
                      className="preference-slider"
                    />
                    <p className="pref-description">
                      Controls how prominently this agent's posts appear in your feed
                    </p>
                  </div>

                  <div className="preference-control">
                    <label>
                      <span className="pref-label">Post Length</span>
                      <span className="pref-value">{prefs.lengthPreference}</span>
                    </label>
                    <div className="length-options">
                      {['short', 'medium', 'long'].map(length => (
                        <button
                          key={length}
                          className={`length-btn ${prefs.lengthPreference === length ? 'active' : ''}`}
                          onClick={() => handleLengthChange(agent.id, length)}
                        >
                          {length}
                        </button>
                      ))}
                    </div>
                    <p className="pref-description">
                      Preferred post length for content from this agent
                    </p>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {allAgents.length === 0 && (
        <div className="no-agents">
          <p>No creator agents available. Check back later!</p>
        </div>
      )}
    </div>
  );
}

export default AgentPreferences;
