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
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to fetch configurations: ${response.status} ${response.statusText} - ${errorText}`);
      }
      const data = await response.json();
      setConfigurations(data);
      setError(null);
    } catch (err) {
      console.error('Error fetching configurations:', err);
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

  const handlePurgeQueue = async () => {
    if (!window.confirm('⚠️ WARNING: This will delete ALL pending documents in the queue!\n\nAre you sure you want to purge the queue?')) return;
    
    try {
      const response = await fetch('/api/admin/purge-queue', {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to purge queue');
      const data = await response.json();
      alert(`✅ Successfully purged ${data.messages_purged} messages from the queue`);
    } catch (err) {
      alert('❌ Error purging queue: ' + err.message);
    }
  };

  const handleTriggerScraper = async (datasourceId, datasourceName) => {
    try {
      const response = await fetch(`/api/retriever/scrape/datasource/${datasourceId}`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to trigger scraper');
      const data = await response.json();
      if (data.status === 'started') {
        alert(`✅ Scraper started for ${datasourceName || datasourceId}`);
      } else {
        alert(`⚠️ ${data.message}`);
      }
    } catch (err) {
      alert('❌ Error triggering scraper: ' + err.message);
    }
  };

  const handleScrapeAllSources = async () => {
    if (!window.confirm('This will trigger scraping for all configured datasources.\n\nDatasources are grouped by scraper type to share authentication sessions.\n\nContinue?')) return;
    
    try {
      const response = await fetch('/api/retriever/scrape/all', {
        method: 'POST',
      });
      
      if (!response.ok) throw new Error('Failed to trigger scrape');
      
      const data = await response.json();
      
      if (data.status === 'no_datasources') {
        alert('⚠️ No datasources with scraper types configured');
        return;
      }
      
      let message = `✅ ${data.message}`;
      
      // Show details of what was started
      if (data.started && data.started.length > 0) {
        message += '\n\nStarted:';
        for (const group of data.started) {
          const names = group.datasources.map(ds => ds.name).join(', ');
          message += `\n• ${group.scraper_type}: ${names}`;
        }
      }
      
      // Show any skipped
      if (data.skipped && data.skipped.length > 0) {
        message += '\n\n⚠️ Skipped:';
        for (const skip of data.skipped) {
          message += `\n• ${skip.scraper_type}: ${skip.reason}`;
        }
      }
      
      alert(message);
    } catch (err) {
      alert('❌ Error triggering scrapers: ' + err.message);
    }
  };

  if (loading) return <div className="loading">Loading configurations...</div>;
  if (error) return <div className="error">Error: {error}</div>;

  return (
    <div className="admin-system-config">
      <div className="config-header">
        <h2>System Configuration</h2>
        <div className="header-actions">
          <button className="btn-scrape-all" onClick={handleScrapeAllSources}>
            🔄 Scrape All Sources
          </button>
          <button className="btn-purge" onClick={handlePurgeQueue}>
            🗑️ Purge Queue
          </button>
          <button className="btn-create" onClick={() => setShowCreateForm(true)}>
            + New Configuration
          </button>
        </div>
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
                  onTriggerScraper={() => handleTriggerScraper(config.datasource_id, config.name)}
                />
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};

const ConfigDisplay = ({ config, onEdit, onDelete, onTriggerScraper }) => {
  // Check if this is a Causeway datasource
  const isCausewayDatasource = config.scraper_type === 'wfa_causeway';
  const hasScraperType = !!config.scraper_type;
  
  return (
    <div className="config-display">
      <div className="config-header-row">
        <h3>{config.datasource_id}</h3>
        <div className="config-actions">
          {hasScraperType && (
            <button className="btn-run" onClick={onTriggerScraper} title="Run scraper now">
              ▶️ Run
            </button>
          )}
          <button className="btn-edit" onClick={onEdit}>Edit</button>
          <button className="btn-delete" onClick={onDelete}>Delete</button>
        </div>
      </div>
      
      <div className="config-details">
        <div className="config-row">
          <span className="label">Name:</span>
          <span className="value">{config.name}</span>
        </div>
        <div className="config-row">
          <span className="label">Scraper Type:</span>
          <span className="value">{config.scraper_type || <em>None (manual only)</em>}</span>
        </div>
        {config.resource_url && (
          <div className="config-row">
            <span className="label">Resource URL:</span>
            <span className="value">{config.resource_url}</span>
          </div>
        )}
        <div className="config-row">
          <span className="label">Schedule:</span>
          <span className="value">
            {config.scrape_schedule ? (
              <code>{config.scrape_schedule}</code>
            ) : (
              <em>Manual only</em>
            )}
          </span>
        </div>
        <div className="config-row">
          <span className="label">Run on Startup:</span>
          <span className="value">{config.run_on_startup ? 'Yes' : 'No'}</span>
        </div>
        <div className="config-row">
          <span className="label">Check Content Hash:</span>
          <span className="value">{config.check_content_hash ? 'Yes' : 'No'}</span>
        </div>
        <div className="config-row">
          <span className="label">Publish Weight:</span>
          <span className="value">{config.publish_weight?.toFixed(2) ?? '1.00'}</span>
        </div>
        <div className="config-row">
          <span className="label">Update Weight:</span>
          <span className="value">{config.update_weight?.toFixed(2) ?? '0.80'}</span>
        </div>
        <div className="config-row">
          <span className="label">Event Weight:</span>
          <span className="value">{config.event_weight?.toFixed(2) ?? '0.90'}</span>
        </div>
        <div className="config-row">
          <span className="label">Scraper Delay:</span>
          <span className="value">{config.scraper_delay?.toFixed(2) ?? '0.50'}s</span>
        </div>
        <div className="config-row">
          <span className="label">Max Resources:</span>
          <span className="value">{config.max_resources ?? 150}</span>
        </div>
        <div className="config-row">
          <span className="label">Max Redirects:</span>
          <span className="value">{config.max_redirects ?? 10}</span>
        </div>
        <div className="config-row">
          <span className="label">Discovery Mode:</span>
          <span className="value">
            {config.discovery_mode === 'date_based' ? 'Date-based (Causeway)' : 'Incremental (URL check)'}
          </span>
        </div>
        {config.discovery_mode === 'incremental' && (
          <div className="config-row">
            <span className="label">Consecutive Duplicates Limit:</span>
            <span className="value">
              {config.consecutive_duplicates_limit === 0 ? <em>Disabled</em> : config.consecutive_duplicates_limit ?? 5}
            </span>
          </div>
        )}
        {config.discovery_mode === 'incremental' && config.full_refresh_schedule && (
          <div className="config-row">
            <span className="label">Full Refresh Schedule:</span>
            <span className="value"><code>{config.full_refresh_schedule}</code></span>
          </div>
        )}
        {isCausewayDatasource && config.folders && config.folders.length > 0 && (
          <div className="config-row">
            <span className="label">Allowed Folders:</span>
            <span className="value">
              <ul className="folder-list">
                {config.folders.map((folder, idx) => (
                  <li key={idx}>{folder}</li>
                ))}
              </ul>
            </span>
          </div>
        )}
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
    name: config?.name || '',
    scraper_type: config?.scraper_type || '',
    resource_url: config?.resource_url || '',
    scrape_schedule: config?.scrape_schedule || '',
    run_on_startup: config?.run_on_startup ?? false,
    check_content_hash: config?.check_content_hash ?? true,
    publish_weight: config?.publish_weight ?? 1.0,
    update_weight: config?.update_weight ?? 0.8,
    event_weight: config?.event_weight ?? 0.9,
    scraper_delay: config?.scraper_delay ?? 0.5,
    max_resources: config?.max_resources ?? 150,
    max_redirects: config?.max_redirects ?? 10,
    discovery_mode: config?.discovery_mode || 'incremental',
    consecutive_duplicates_limit: config?.consecutive_duplicates_limit ?? 5,
    full_refresh_schedule: config?.full_refresh_schedule || '',
    folders: config?.folders || [],
  });
  
  const [folderInput, setFolderInput] = useState('');
  
  // Check if this is a Causeway datasource
  const isCausewayDatasource = formData.scraper_type === 'wfa_causeway';

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    const newValue = type === 'checkbox' ? checked : type === 'number' ? parseFloat(value) : value;
    
    // Auto-set discovery_mode based on scraper_type
    if (name === 'scraper_type') {
      const defaultDiscoveryMode = value === 'wfa_causeway' ? 'date_based' : 'incremental';
      setFormData({
        ...formData,
        [name]: newValue,
        discovery_mode: defaultDiscoveryMode,
      });
    } else {
      setFormData({
        ...formData,
        [name]: newValue,
      });
    }
  };
  
  const handleAddFolder = () => {
    if (folderInput.trim()) {
      setFormData({
        ...formData,
        folders: [...formData.folders, folderInput.trim()]
      });
      setFolderInput('');
    }
  };
  
  const handleRemoveFolder = (index) => {
    setFormData({
      ...formData,
      folders: formData.folders.filter((_, idx) => idx !== index)
    });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    // Build submit data, converting empty strings to null for optional fields
    const submitData = { ...formData };
    
    // Convert empty strings to null for optional fields
    if (!submitData.scraper_type) submitData.scraper_type = null;
    if (!submitData.resource_url) submitData.resource_url = null;
    if (!submitData.scrape_schedule) submitData.scrape_schedule = null;
    if (!submitData.full_refresh_schedule) submitData.full_refresh_schedule = null;
    
    // Only send folders if it's a Causeway datasource and folders exist
    if (!isCausewayDatasource || submitData.folders.length === 0) {
      delete submitData.folders;
    }
    onSubmit(submitData);
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
          placeholder="e.g., wfa_causeway_wifi7mtg"
        />
        <small className="form-hint">Unique identifier for this datasource configuration</small>
      </div>

      <div className="form-group">
        <label htmlFor="name">Display Name:</label>
        <input
          type="text"
          id="name"
          name="name"
          value={formData.name}
          onChange={handleChange}
          required
          placeholder="e.g., Wi-Fi 7 MTG"
        />
      </div>

      <div className="form-group">
        <label htmlFor="scraper_type">Scraper Type:</label>
        <select
          id="scraper_type"
          name="scraper_type"
          value={formData.scraper_type}
          onChange={handleChange}
        >
          <option value="">None (manual only)</option>
          <option value="wfa">WFA Public (wi-fi.org)</option>
          <option value="wfa_causeway">WFA Causeway (authenticated)</option>
        </select>
        <small className="form-hint">Select the scraper to use for this datasource</small>
      </div>

      {formData.scraper_type && (
        <div className="form-group">
          <label htmlFor="resource_url">Resource URL Path:</label>
          <input
            type="text"
            id="resource_url"
            name="resource_url"
            value={formData.resource_url}
            onChange={handleChange}
            placeholder={formData.scraper_type === 'wfa_causeway' ? 'e.g., /wg/WiFi7MTG/document' : 'e.g., /resource-center'}
          />
          <small className="form-hint">URL path to scrape (appended to base URL)</small>
        </div>
      )}

      <div className="form-group">
        <label htmlFor="scrape_schedule">Scrape Schedule (Cron):</label>
        <input
          type="text"
          id="scrape_schedule"
          name="scrape_schedule"
          value={formData.scrape_schedule}
          onChange={handleChange}
          placeholder="e.g., 0 2 * * *"
        />
        <small className="form-hint">
          Cron expression: minute hour day month weekday. Examples: "0 2 * * *" (2 AM daily), "0 */6 * * *" (every 6 hours). Leave empty for manual only.
        </small>
      </div>

      <div className="form-group checkbox-group">
        <label htmlFor="run_on_startup">
          <input
            type="checkbox"
            id="run_on_startup"
            name="run_on_startup"
            checked={formData.run_on_startup}
            onChange={handleChange}
          />
          Run on Startup
        </label>
        <small className="form-hint">Run immediately when retriever service starts</small>
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

      <div className="form-group">
        <label htmlFor="scraper_delay">Scraper Delay (seconds):</label>
        <input
          type="number"
          id="scraper_delay"
          name="scraper_delay"
          value={formData.scraper_delay}
          onChange={handleChange}
          min="0"
          max="10"
          step="0.1"
          required
        />
        <small className="form-hint">Time to wait between requests (e.g., 0.5 for public sites, 1.0 for authenticated)</small>
      </div>

      <div className="form-group">
        <label htmlFor="max_resources">Max Resources per Scrape:</label>
        <input
          type="number"
          id="max_resources"
          name="max_resources"
          value={formData.max_resources}
          onChange={handleChange}
          min="-1"
          step="1"
          required
        />
        <small className="form-hint">Maximum resources to scrape per run (-1 for unlimited)</small>
      </div>

      <div className="form-group">
        <label htmlFor="max_redirects">Max Redirects:</label>
        <input
          type="number"
          id="max_redirects"
          name="max_redirects"
          value={formData.max_redirects}
          onChange={handleChange}
          min="1"
          max="50"
          step="1"
          required
        />
        <small className="form-hint">Maximum number of redirects to follow when resolving URLs</small>
      </div>

      <div className="form-group">
        <label htmlFor="discovery_mode">Discovery Mode:</label>
        <select
          id="discovery_mode"
          name="discovery_mode"
          value={formData.discovery_mode}
          onChange={handleChange}
        >
          <option value="incremental">Incremental (URL check)</option>
          <option value="date_based">Date-based (modification dates)</option>
        </select>
        <small className="form-hint">
          Incremental: stops after consecutive duplicate URLs. Date-based: uses folder/document mod dates (for Causeway).
        </small>
      </div>

      {formData.discovery_mode === 'incremental' && (
        <div className="form-group">
          <label htmlFor="consecutive_duplicates_limit">Consecutive Duplicates Limit:</label>
          <input
            type="number"
            id="consecutive_duplicates_limit"
            name="consecutive_duplicates_limit"
            value={formData.consecutive_duplicates_limit}
            onChange={handleChange}
            min="0"
            step="1"
          />
          <small className="form-hint">
            Stop pagination after this many consecutive duplicate URLs (0 = disabled, scrape all pages)
          </small>
        </div>
      )}

      {formData.discovery_mode === 'incremental' && (
        <div className="form-group">
          <label htmlFor="full_refresh_schedule">Full Refresh Schedule (Cron):</label>
          <input
            type="text"
            id="full_refresh_schedule"
            name="full_refresh_schedule"
            value={formData.full_refresh_schedule}
            onChange={handleChange}
            placeholder="e.g., 0 2 * * 0"
          />
          <small className="form-hint">
            Cron expression for periodic full refresh (ignores optimization, scrapes everything). Example: "0 2 * * 0" (Sunday 2 AM). Leave empty to disable.
          </small>
        </div>
      )}
      
      {isCausewayDatasource && (
        <div className="form-group">
          <label>Allowed Folders:</label>
          <small className="form-hint">
            Leave empty to scrape all folders. Add folder paths to restrict scraping.
          </small>
          <div className="folder-input-group">
            <input
              type="text"
              value={folderInput}
              onChange={(e) => setFolderInput(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), handleAddFolder())}
              placeholder="e.g., Meeting Notes or Specs/Draft"
            />
            <button type="button" onClick={handleAddFolder} className="btn-add-folder">
              Add
            </button>
          </div>
          {formData.folders.length > 0 && (
            <ul className="folder-list-edit">
              {formData.folders.map((folder, idx) => (
                <li key={idx}>
                  {folder}
                  <button
                    type="button"
                    onClick={() => handleRemoveFolder(idx)}
                    className="btn-remove-folder"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

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
