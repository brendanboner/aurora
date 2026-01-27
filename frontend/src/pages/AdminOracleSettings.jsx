import React, { useState, useEffect } from 'react';
import './Admin.css';

const AdminOracleSettings = () => {
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
      const response = await fetch('/api/oracle/admin/config/query-settings');
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
      
      const response = await fetch('/api/oracle/admin/config/query-settings', {
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
      setSuccessMessage('Configuration updated successfully! Changes are applied immediately.');
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
      
      const response = await fetch('/api/oracle/admin/config/query-settings/reset', {
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
      <div className="admin-container">
        <div className="spinner" />
      </div>
    );
  }

  if (error && !config) {
    return (
      <div className="admin-container">
        <div className="error-state">
          <h3>Error Loading Configuration</h3>
          <p>{error}</p>
          <button onClick={fetchConfig}>Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-container">
      <div className="config-header">
        <div>
          <h2>Oracle Query Settings</h2>
          <p className="config-description">
            Configure the Oracle service query pipeline, including A/B testing for the new fast retrieval pipeline.
            Changes are applied immediately and affect all users.
          </p>
        </div>
      </div>

      {error && (
        <div className="alert alert-error">
          <strong>Error:</strong> {error}
        </div>
      )}

      {successMessage && (
        <div className="alert alert-success">
          {successMessage}
        </div>
      )}

      {editedConfig && (
        <div className="config-sections">
          {/* Fast Pipeline Toggle */}
          <div className="config-setting">
            <div className="setting-header">
              <h3>Fast Retrieval Pipeline</h3>
              <span className="setting-value">
                {editedConfig.fast_pipeline_enabled ? '✅ Enabled' : '❌ Disabled'}
              </span>
            </div>
            
            <p className="setting-description">
              Enable the new fast retrieval pipeline with deterministic routing, Cypher templates, 
              and multi-layer caching. This achieves ≥2x latency improvements for common queries.
            </p>
            
            <div className="toggle-control">
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={editedConfig.fast_pipeline_enabled}
                  onChange={(e) => handleFieldChange('fast_pipeline_enabled', e.target.checked)}
                />
                <span className="toggle-slider"></span>
              </label>
              <span className="toggle-label">
                {editedConfig.fast_pipeline_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
          </div>

          {/* Rollout Percentage */}
          {editedConfig.fast_pipeline_enabled && (
            <div className="config-setting">
              <div className="setting-header">
                <h3>Fast Pipeline Rollout</h3>
                <span className="setting-value">{editedConfig.fast_pipeline_rollout_percentage}%</span>
              </div>
              
              <p className="setting-description">
                Percentage of users (0-100) that will use the fast pipeline. Uses hash-based bucketing 
                for consistent assignment. Start with low percentage and gradually increase.
              </p>
              
              <div className="slider-control">
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={editedConfig.fast_pipeline_rollout_percentage}
                  onChange={(e) => handleFieldChange('fast_pipeline_rollout_percentage', parseInt(e.target.value))}
                  className="config-slider"
                />
                <div className="slider-labels">
                  <span>0% (None)</span>
                  <span>50% (Half)</span>
                  <span>100% (All)</span>
                </div>
              </div>
            </div>
          )}

          {/* Shadow Mode */}
          {editedConfig.fast_pipeline_enabled && (
            <div className="config-setting">
              <div className="setting-header">
                <h3>Shadow Mode</h3>
                <span className="setting-value">
                  {editedConfig.fast_pipeline_shadow_mode ? '👁️ Active' : '🚀 Live'}
                </span>
              </div>
              
              <p className="setting-description">
                When enabled, fast pipeline runs in parallel but doesn't return results (logs only). 
                Use this to compare performance without affecting users.
              </p>
              
              <div className="toggle-control">
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={editedConfig.fast_pipeline_shadow_mode}
                    onChange={(e) => handleFieldChange('fast_pipeline_shadow_mode', e.target.checked)}
                  />
                  <span className="toggle-slider"></span>
                </label>
                <span className="toggle-label">
                  {editedConfig.fast_pipeline_shadow_mode ? 'Shadow Mode (Testing)' : 'Live Mode (Production)'}
                </span>
              </div>
            </div>
          )}

          {/* Confidence Threshold */}
          <div className="config-setting">
            <div className="setting-header">
              <h3>Confidence Threshold</h3>
              <span className="setting-value">{editedConfig.fast_confidence_threshold.toFixed(2)}</span>
            </div>
            
            <p className="setting-description">
              Minimum confidence score (0.0-1.0) required for fast pipeline to return results. 
              Lower values may return more results but with lower quality.
            </p>
            
            <div className="slider-control">
              <input
                type="range"
                min="0.3"
                max="0.9"
                step="0.05"
                value={editedConfig.fast_confidence_threshold}
                onChange={(e) => handleFieldChange('fast_confidence_threshold', parseFloat(e.target.value))}
                className="config-slider"
              />
              <div className="slider-labels">
                <span>0.30 (Permissive)</span>
                <span>0.60 (Balanced)</span>
                <span>0.90 (Strict)</span>
              </div>
            </div>
          </div>

          {/* Cache Settings */}
          <div className="config-setting">
            <div className="setting-header">
              <h3>Cache TTL (Time-to-Live)</h3>
            </div>
            
            <p className="setting-description">
              Configure how long cached results are stored. Longer TTLs improve performance but 
              may serve stale data.
            </p>
            
            <div className="number-controls-grid">
              <div className="number-control-item">
                <label>Plan Cache (hours)</label>
                <div className="number-control">
                  <button 
                    onClick={() => handleFieldChange('fast_cache_plan_ttl_hours', Math.max(1, editedConfig.fast_cache_plan_ttl_hours - 1))}
                    disabled={editedConfig.fast_cache_plan_ttl_hours <= 1}
                  >
                    -1
                  </button>
                  <input
                    type="number"
                    min="1"
                    max="48"
                    value={editedConfig.fast_cache_plan_ttl_hours}
                    onChange={(e) => handleFieldChange('fast_cache_plan_ttl_hours', parseInt(e.target.value) || 1)}
                    className="number-input"
                  />
                  <button 
                    onClick={() => handleFieldChange('fast_cache_plan_ttl_hours', Math.min(48, editedConfig.fast_cache_plan_ttl_hours + 1))}
                    disabled={editedConfig.fast_cache_plan_ttl_hours >= 48}
                  >
                    +1
                  </button>
                </div>
              </div>

              <div className="number-control-item">
                <label>Result Cache (minutes)</label>
                <div className="number-control">
                  <button 
                    onClick={() => handleFieldChange('fast_cache_result_ttl_minutes', Math.max(5, editedConfig.fast_cache_result_ttl_minutes - 5))}
                    disabled={editedConfig.fast_cache_result_ttl_minutes <= 5}
                  >
                    -5
                  </button>
                  <input
                    type="number"
                    min="5"
                    max="120"
                    value={editedConfig.fast_cache_result_ttl_minutes}
                    onChange={(e) => handleFieldChange('fast_cache_result_ttl_minutes', parseInt(e.target.value) || 5)}
                    className="number-input"
                  />
                  <button 
                    onClick={() => handleFieldChange('fast_cache_result_ttl_minutes', Math.min(120, editedConfig.fast_cache_result_ttl_minutes + 5))}
                    disabled={editedConfig.fast_cache_result_ttl_minutes >= 120}
                  >
                    +5
                  </button>
                </div>
              </div>

              <div className="number-control-item">
                <label>Answer Cache (minutes)</label>
                <div className="number-control">
                  <button 
                    onClick={() => handleFieldChange('fast_cache_answer_ttl_minutes', Math.max(5, editedConfig.fast_cache_answer_ttl_minutes - 5))}
                    disabled={editedConfig.fast_cache_answer_ttl_minutes <= 5}
                  >
                    -5
                  </button>
                  <input
                    type="number"
                    min="5"
                    max="120"
                    value={editedConfig.fast_cache_answer_ttl_minutes}
                    onChange={(e) => handleFieldChange('fast_cache_answer_ttl_minutes', parseInt(e.target.value) || 5)}
                    className="number-input"
                  />
                  <button 
                    onClick={() => handleFieldChange('fast_cache_answer_ttl_minutes', Math.min(120, editedConfig.fast_cache_answer_ttl_minutes + 5))}
                    disabled={editedConfig.fast_cache_answer_ttl_minutes >= 120}
                  >
                    +5
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Deep Dive Settings */}
          <div className="config-setting">
            <div className="setting-header">
              <h3>Deep Dive Retrieval</h3>
              <span className="setting-value">
                {editedConfig.fast_deep_dive_enabled ? '✅ Enabled' : '❌ Disabled'}
              </span>
            </div>
            
            <p className="setting-description">
              Enable fallback to full document retrieval when fast pipeline confidence is low. 
              Increases latency but improves answer quality for complex queries.
            </p>
            
            <div className="toggle-control">
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={editedConfig.fast_deep_dive_enabled}
                  onChange={(e) => handleFieldChange('fast_deep_dive_enabled', e.target.checked)}
                />
                <span className="toggle-slider"></span>
              </label>
              <span className="toggle-label">
                {editedConfig.fast_deep_dive_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="config-actions">
            <button 
              onClick={handleSave}
              disabled={!hasChanges() || saving}
              className="btn-save"
            >
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
            <button 
              onClick={handleReset}
              disabled={saving}
              className="btn-reset"
            >
              Reset to Defaults
            </button>
            <button 
              onClick={() => setEditedConfig(config)}
              disabled={!hasChanges() || saving}
              className="btn-cancel"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminOracleSettings;
