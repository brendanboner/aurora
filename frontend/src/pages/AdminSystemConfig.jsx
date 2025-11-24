import React, { useState, useEffect } from 'react';
import './AdminSystemConfig.css';

const AdminSystemConfig = () => {
  const [configurations, setConfigurations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingConfig, setEditingConfig] = useState(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  useEffect(() => {
    fetchConfigurations();
  }, []);

  const fetchConfigurations = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/admin/system-configuration');
      if (!response.ok) throw new Error('Failed to fetch configurations');
      const data = await response.json();
      setConfigurations(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (formData) => {
    try {
      const response = await fetch('/api/admin/system-configuration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      if (!response.ok) throw new Error('Failed to create configuration');
      await fetchConfigurations();
      setShowCreateForm(false);
    } catch (err) {
      alert('Error creating configuration: ' + err.message);
    }
  };

  const handleUpdate = async (datasourceId, formData) => {
    try {
      const response = await fetch(`/api/admin/system-configuration/${datasourceId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });
      if (!response.ok) throw new Error('Failed to update configuration');
      await fetchConfigurations();
      setEditingConfig(null);
    } catch (err) {
      alert('Error updating configuration: ' + err.message);
    }
  };

  const handleDelete = async (datasourceId) => {
    if (!window.confirm(`Delete configuration for ${datasourceId}?`)) return;
    
    try {
      const response = await fetch(`/api/admin/system-configuration/${datasourceId}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to delete configuration');
      await fetchConfigurations();
    } catch (err) {
      alert('Error deleting configuration: ' + err.message);
    }
  };

  if (loading) return <div className="loading">Loading configurations...</div>;
  if (error) return <div className="error">Error: {error}</div>;

  return (
    <div className="admin-system-config">
      <div className="config-header">
        <h2>System Configuration</h2>
        <button className="btn-create" onClick={() => setShowCreateForm(true)}>
          + New Configuration
        </button>
      </div>

      {showCreateForm && (
        <ConfigForm
          onSubmit={handleCreate}
          onCancel={() => setShowCreateForm(false)}
        />
      )}

      <div className="config-list">
        {configurations.length === 0 ? (
          <p className="no-configs">No configurations found. Create your first configuration above.</p>
        ) : (
          configurations.map((config) => (
            <div key={config.datasource_id} className="config-card">
              {editingConfig === config.datasource_id ? (
                <ConfigForm
                  config={config}
                  onSubmit={(data) => handleUpdate(config.datasource_id, data)}
                  onCancel={() => setEditingConfig(null)}
                />
              ) : (
                <ConfigDisplay
                  config={config}
                  onEdit={() => setEditingConfig(config.datasource_id)}
                  onDelete={() => handleDelete(config.datasource_id)}
                />
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

const ConfigDisplay = ({ config, onEdit, onDelete }) => {
  return (
    <div className="config-display">
      <div className="config-header-row">
        <h3>{config.datasource_id}</h3>
        <div className="config-actions">
          <button className="btn-edit" onClick={onEdit}>Edit</button>
          <button className="btn-delete" onClick={onDelete}>Delete</button>
        </div>
      </div>
      
      <div className="config-details">
        <div className="config-row">
          <span className="label">Scrape Frequency:</span>
          <span className="value">{config.scrape_frequency}</span>
        </div>
        <div className="config-row">
          <span className="label">Check Content Hash:</span>
          <span className="value">{config.check_content_hash ? 'Yes' : 'No'}</span>
        </div>
        <div className="config-row">
          <span className="label">Publish Weight:</span>
          <span className="value">{config.publish_weight.toFixed(2)}</span>
        </div>
        <div className="config-row">
          <span className="label">Update Weight:</span>
          <span className="value">{config.update_weight.toFixed(2)}</span>
        </div>
        <div className="config-row">
          <span className="label">Event Weight:</span>
          <span className="value">{config.event_weight.toFixed(2)}</span>
        </div>
        {config.last_scraped_at && (
          <div className="config-row">
            <span className="label">Last Scraped:</span>
            <span className="value">{new Date(config.last_scraped_at).toLocaleString()}</span>
          </div>
        )}
      </div>
    </div>
  );
};

const ConfigForm = ({ config, onSubmit, onCancel }) => {
  const [formData, setFormData] = useState({
    datasource_id: config?.datasource_id || '',
    scrape_frequency: config?.scrape_frequency || 'daily',
    check_content_hash: config?.check_content_hash ?? true,
    publish_weight: config?.publish_weight ?? 1.0,
    update_weight: config?.update_weight ?? 0.8,
    event_weight: config?.event_weight ?? 0.9,
  });

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData({
      ...formData,
      [name]: type === 'checkbox' ? checked : type === 'number' ? parseFloat(value) : value,
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(formData);
  };

  return (
    <form className="config-form" onSubmit={handleSubmit}>
      <div className="form-group">
        <label htmlFor="datasource_id">Datasource ID:</label>
        <input
          type="text"
          id="datasource_id"
          name="datasource_id"
          value={formData.datasource_id}
          onChange={handleChange}
          required
          disabled={!!config}
          placeholder="e.g., wfa_resource_page"
        />
      </div>

      <div className="form-group">
        <label htmlFor="scrape_frequency">Scrape Frequency:</label>
        <select
          id="scrape_frequency"
          name="scrape_frequency"
          value={formData.scrape_frequency}
          onChange={handleChange}
          required
        >
          <option value="hourly">Hourly</option>
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="manual">Manual</option>
        </select>
      </div>

      <div className="form-group checkbox-group">
        <label htmlFor="check_content_hash">
          <input
            type="checkbox"
            id="check_content_hash"
            name="check_content_hash"
            checked={formData.check_content_hash}
            onChange={handleChange}
          />
          Check Content Hash
        </label>
      </div>

      <div className="form-group">
        <label htmlFor="publish_weight">Publish Weight (0.0 - 1.0):</label>
        <input
          type="number"
          id="publish_weight"
          name="publish_weight"
          value={formData.publish_weight}
          onChange={handleChange}
          min="0"
          max="1"
          step="0.1"
          required
        />
      </div>

      <div className="form-group">
        <label htmlFor="update_weight">Update Weight (0.0 - 1.0):</label>
        <input
          type="number"
          id="update_weight"
          name="update_weight"
          value={formData.update_weight}
          onChange={handleChange}
          min="0"
          max="1"
          step="0.1"
          required
        />
      </div>

      <div className="form-group">
        <label htmlFor="event_weight">Event Weight (0.0 - 1.0):</label>
        <input
          type="number"
          id="event_weight"
          name="event_weight"
          value={formData.event_weight}
          onChange={handleChange}
          min="0"
          max="1"
          step="0.1"
          required
        />
      </div>

      <div className="form-actions">
        <button type="submit" className="btn-submit">
          {config ? 'Update' : 'Create'}
        </button>
        <button type="button" className="btn-cancel" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
};

export default AdminSystemConfig;
