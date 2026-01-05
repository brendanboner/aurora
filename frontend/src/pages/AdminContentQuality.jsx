import React, { useState, useEffect } from 'react';
import './AdminContentQuality.css';

const AdminContentQuality = () => {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [editedConfig, setEditedConfig] = useState(null);

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/content-creator/admin/config/content-quality');
      if (!response.ok) {
        throw new Error(`Failed to fetch configuration: ${response.status}`);
      }
      const data = await response.json();
      setConfig(data);
      setEditedConfig(data);
      setError(null);
    } catch (err) {
      console.error('Error fetching configuration:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccessMessage(null);
      
      const response = await fetch('/api/content-creator/admin/config/content-quality', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editedConfig),
      });
      
      if (!response.ok) {
        throw new Error(`Failed to update configuration: ${response.status}`);
      }
      
      const updatedConfig = await response.json();
      setConfig(updatedConfig);
      setEditedConfig(updatedConfig);
      setSuccessMessage('Configuration updated successfully! Changes will affect new posts.');
    } catch (err) {
      console.error('Error updating configuration:', err);
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!window.confirm('Reset all settings to default values?')) {
      return;
    }
    
    try {
      setSaving(true);
      setError(null);
      setSuccessMessage(null);
      
      const response = await fetch('/api/content-creator/admin/config/content-quality/reset', {
        method: 'POST',
      });
      
      if (!response.ok) {
        throw new Error(`Failed to reset configuration: ${response.status}`);
      }
      
      const data = await response.json();
      setConfig(data.config);
      setEditedConfig(data.config);
      setSuccessMessage('Configuration reset to defaults!');
    } catch (err) {
      console.error('Error resetting configuration:', err);
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleFieldChange = (field, value) => {
    setEditedConfig(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const hasChanges = () => {
    if (!config || !editedConfig) return false;
    return JSON.stringify(config) !== JSON.stringify(editedConfig);
  };

  if (loading) {
    return (
      <div className="admin-content-quality">
        <div className="loading-state">Loading configuration...</div>
      </div>
    );
  }

  if (error && !config) {
    return (
      <div className="admin-content-quality">
        <div className="error-state">
          <h3>Error Loading Configuration</h3>
          <p>{error}</p>
          <button onClick={fetchConfig}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-content-quality">
      <div className="config-header">
        <h2>Content Quality & Diversity Settings</h2>
        <p className="config-description">
          Configure how articles are selected and filtered for AI-generated posts. 
          These settings control content quality, diversity, and relevance thresholds.
        </p>
      </div>

      {error && (
        <div className="alert alert-error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {successMessage && (
        <div className="alert alert-success">
          <strong>Success!</strong> {successMessage}
        </div>
      )}

      <div className="config-sections">
        {/* Similarity Threshold */}
        <div className="config-section">
          <div className="section-header">
            <h3>Article Similarity Threshold</h3>
            <span className="current-value">{editedConfig.diversity_similarity_threshold.toFixed(2)}</span>
          </div>
          
          <p className="section-description">
            Controls how aggressively similar articles are filtered using Jaccard similarity. 
            Higher values remove more similar articles, creating more diverse posts.
          </p>
          
          <div className="slider-control">
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={editedConfig.diversity_similarity_threshold}
              onChange={(e) => handleFieldChange('diversity_similarity_threshold', parseFloat(e.target.value))}
              className="config-slider"
            />
            <div className="slider-labels">
              <span>0.0 (Permissive)</span>
              <span>0.5 (Balanced)</span>
              <span>1.0 (Strict)</span>
            </div>
          </div>
          
          <div className="recommendation-box">
            <strong>Recommended:</strong> 0.60 - 0.80<br/>
            <em>Default: 0.70</em> - Filters articles with similar titles/content
          </div>
          
          <div className="example-box">
            <strong>Example:</strong> At 0.70, articles titled "Wi-Fi 6E Channel Rules" and 
            "Wi-Fi 6E Channel Regulations" would be considered duplicates (one removed).
            At 0.50, both would be kept.
          </div>
        </div>

        {/* Min Relevance Score */}
        <div className="config-section">
          <div className="section-header">
            <h3>Minimum Relevance Score</h3>
            <span className="current-value">{editedConfig.min_relevance_score_default.toFixed(2)}</span>
          </div>
          
          <p className="section-description">
            Minimum quality threshold for articles. Only articles scoring above this threshold 
            are included in posts. Higher values ensure more focused, relevant content.
          </p>
          
          <div className="slider-control">
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={editedConfig.min_relevance_score_default}
              onChange={(e) => handleFieldChange('min_relevance_score_default', parseFloat(e.target.value))}
              className="config-slider"
            />
            <div className="slider-labels">
              <span>0.0 (Permissive)</span>
              <span>0.5 (Balanced)</span>
              <span>1.0 (Strict)</span>
            </div>
          </div>
          
          <div className="recommendation-box">
            <strong>Recommended:</strong> 0.20 - 0.40<br/>
            <em>Default: 0.30</em> - Balanced quality threshold
          </div>
          
          <div className="info-box">
            <strong>Note:</strong> Agent discovery_tolerance setting can override this default. 
            Exploratory agents may use lower thresholds for broader content discovery.
          </div>
        </div>

        {/* Max Topics per Article */}
        <div className="config-section">
          <div className="section-header">
            <h3>Maximum Topics per Article</h3>
            <span className="current-value">{editedConfig.max_topics_per_article}</span>
          </div>
          
          <p className="section-description">
            Filter out generic aggregation articles with too many topics. Articles exceeding 
            this limit are considered unfocused and excluded from posts.
          </p>
          
          <div className="number-control">
            <button 
              onClick={() => handleFieldChange('max_topics_per_article', Math.max(1, editedConfig.max_topics_per_article - 5))}
              disabled={editedConfig.max_topics_per_article <= 1}
            >
              -5
            </button>
            <input
              type="number"
              min="1"
              max="100"
              value={editedConfig.max_topics_per_article}
              onChange={(e) => handleFieldChange('max_topics_per_article', parseInt(e.target.value) || 1)}
              className="number-input"
            />
            <button 
              onClick={() => handleFieldChange('max_topics_per_article', Math.min(100, editedConfig.max_topics_per_article + 5))}
              disabled={editedConfig.max_topics_per_article >= 100}
            >
              +5
            </button>
          </div>
          
          <div className="recommendation-box">
            <strong>Recommended:</strong> 15 - 25<br/>
            <em>Default: 20</em> - Filters overly broad content
          </div>
          
          <div className="example-box">
            <strong>Example:</strong> An article with 30+ topics like "Wi-Fi, 5G, IoT, Cloud, 
            Security, AI, Blockchain..." is likely a generic industry roundup rather than 
            focused content.
          </div>
        </div>

        {/* Max Articles per Domain */}
        <div className="config-section">
          <div className="section-header">
            <h3>Maximum Articles per Domain</h3>
            <span className="current-value">{editedConfig.max_articles_per_domain}</span>
          </div>
          
          <p className="section-description">
            Limit how many articles from the same domain (source) can appear in a single post. 
            This ensures source diversity and prevents single-source dominance.
          </p>
          
          <div className="number-control">
            <button 
              onClick={() => handleFieldChange('max_articles_per_domain', Math.max(1, editedConfig.max_articles_per_domain - 1))}
              disabled={editedConfig.max_articles_per_domain <= 1}
            >
              -1
            </button>
            <input
              type="number"
              min="1"
              max="10"
              value={editedConfig.max_articles_per_domain}
              onChange={(e) => handleFieldChange('max_articles_per_domain', parseInt(e.target.value) || 1)}
              className="number-input"
            />
            <button 
              onClick={() => handleFieldChange('max_articles_per_domain', Math.min(10, editedConfig.max_articles_per_domain + 1))}
              disabled={editedConfig.max_articles_per_domain >= 10}
            >
              +1
            </button>
          </div>
          
          <div className="recommendation-box">
            <strong>Recommended:</strong> 2 - 3<br/>
            <em>Default: 2</em> - Balanced source diversity
          </div>
        </div>

        {/* Temporal Window */}
        <div className="config-section">
          <div className="section-header">
            <h3>Default Temporal Window (Days)</h3>
            <span className="current-value">{editedConfig.temporal_window_days_default}</span>
          </div>
          
          <p className="section-description">
            How far back in time to search for articles (in days). Older articles beyond this 
            window are excluded unless agent-specific cadence overrides this setting.
          </p>
          
          <div className="number-control">
            <button 
              onClick={() => handleFieldChange('temporal_window_days_default', Math.max(1, editedConfig.temporal_window_days_default - 30))}
              disabled={editedConfig.temporal_window_days_default <= 1}
            >
              -30
            </button>
            <input
              type="number"
              min="1"
              max="365"
              value={editedConfig.temporal_window_days_default}
              onChange={(e) => handleFieldChange('temporal_window_days_default', parseInt(e.target.value) || 1)}
              className="number-input"
            />
            <button 
              onClick={() => handleFieldChange('temporal_window_days_default', Math.min(365, editedConfig.temporal_window_days_default + 30))}
              disabled={editedConfig.temporal_window_days_default >= 365}
            >
              +30
            </button>
          </div>
          
          <div className="recommendation-box">
            <strong>Recommended:</strong> 60 - 120 days<br/>
            <em>Default: 90 days</em> - Balanced recency
          </div>
          
          <div className="info-box">
            <strong>Note:</strong> Individual agents can override this with their 
            cadence_window_days setting for more or less recent content.
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="config-actions">
        <button 
          onClick={handleSave} 
          disabled={!hasChanges() || saving}
          className="btn btn-primary"
        >
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
        
        <button 
          onClick={handleReset} 
          disabled={saving}
          className="btn btn-secondary"
        >
          Reset to Defaults
        </button>
        
        <button 
          onClick={() => {
            setEditedConfig(config);
            setError(null);
            setSuccessMessage(null);
          }}
          disabled={!hasChanges() || saving}
          className="btn btn-tertiary"
        >
          Cancel Changes
        </button>
      </div>

      {/* Warning Box */}
      <div className="warning-box">
        <h4>⚠️ Important Notes</h4>
        <ul>
          <li>These settings apply to new posts only. Existing posts are not affected.</li>
          <li>Changes are runtime only and will reset on service restart unless persisted via environment variables.</li>
          <li>To persist changes across restarts, update environment variables or configuration files.</li>
          <li>Test changes with a small subset of agents before applying system-wide.</li>
        </ul>
      </div>
    </div>
  );
};

export default AdminContentQuality;
