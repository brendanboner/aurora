import React, { useState, useEffect } from 'react';
import './AdminSystemConfig.css';
import IETFGroupsModal from '../components/IETFGroupsModal';

const DEFAULT_LOOKBACK_VALUES = [1, 2, 4, 8, 12, 26, 52];
const LOOKBACK_UNITS = ['days', 'weeks', 'months', 'years'];

// Ordered groups — anything not matched falls into the last catch-all
const TYPE_GROUPS = [
  { key: 'wfa_causeway',      label: 'WFA Causeway',      color: '#a855f7' },
  { key: 'wfa',               label: 'WFA Public',         color: '#3b82f6' },
  { key: 'wba_extranet',      label: 'WBA Extranet',       color: '#f43f5e' },
  { key: 'wba',               label: 'WBA',                color: '#ec4899' },
  { key: 'ietf_datatracker',  label: 'IETF Datatracker',   color: '#f97316' },
  { key: 'ietf_blog',         label: 'IETF Blog',          color: '#fb923c' },
  { key: '__manual__',        label: 'Manual / No Scraper', color: '#94a3b8' },
];

function groupByType(configs) {
  const buckets = {};
  TYPE_GROUPS.forEach(g => { buckets[g.key] = []; });
  configs.forEach(c => {
    const type = c.scraper_type || '__manual__';
    if (buckets[type] !== undefined) {
      buckets[type].push(c);
    } else {
      // Unknown type — add a dynamic bucket
      if (!buckets[type]) buckets[type] = [];
      buckets[type].push(c);
    }
  });
  return TYPE_GROUPS
    .filter(g => buckets[g.key]?.length > 0)
    .map(g => ({ ...g, configs: buckets[g.key] }));
}

function friendlySchedule(cron) {
  if (!cron) return null;
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [min, hour, dom, month, dow] = parts;
  if (dom === '*' && month === '*') {
    if (dow === '*') {
      if (hour.startsWith('*/')) return `Every ${hour.slice(2)}h`;
      return `Daily ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    }
    const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    if (/^\d$/.test(dow)) return `Weekly ${days[+dow]} ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
  }
  return cron;
}

function timeAgoShort(iso) {
  if (!iso) return null;
  const secs = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (secs < 60)   return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
const DEFAULT_GLOBAL_CONFIG = {
  datasource_id: 'default',
  name: 'System Defaults',
  ingestion_lookback_value: 12,
  ingestion_lookback_unit: 'months',
};

const AdminSystemConfig = () => {
  const [configurations, setConfigurations] = useState([]);
  const [globalConfig, setGlobalConfig] = useState(DEFAULT_GLOBAL_CONFIG);
  const [globalConfigExists, setGlobalConfigExists] = useState(false);
  const [savingGlobalConfig, setSavingGlobalConfig] = useState(false);
  const [scraperStatus, setScraperStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingConfig, setEditingConfig] = useState(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [showIETFGroupsModal, setShowIETFGroupsModal] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState({});

  const toggleGroup = (key) =>
    setCollapsedGroups(prev => ({ ...prev, [key]: !prev[key] }));
  const [hoveredFolder, setHoveredFolder] = useState(null);
  const [folderPosition, setFolderPosition] = useState({ x: 0, y: 0 });
  const [hoveredUrl, setHoveredUrl] = useState(null);
  const [urlPosition, setUrlPosition] = useState({ x: 0, y: 0 });

  useEffect(() => {
    fetchConfigurations();
    fetchScraperStatus();
    
    // Poll for status updates every 5 seconds
    const interval = setInterval(() => {
      fetchScraperStatus();
    }, 5000);
    
    return () => clearInterval(interval);
  }, []);

  const fetchConfigurations = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/backend/admin/system-configuration');
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to fetch configurations: ${response.status} ${response.statusText} - ${errorText}`);
      }
      const data = await response.json();
      const defaultConfig = data.find((config) => config.datasource_id === 'default');
      setGlobalConfig({
        ...DEFAULT_GLOBAL_CONFIG,
        ...(defaultConfig || {}),
      });
      setGlobalConfigExists(Boolean(defaultConfig));
      setConfigurations(data.filter((config) => config.datasource_id !== 'default'));
      setError(null);
    } catch (err) {
      console.error('Error fetching configurations:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchScraperStatus = async () => {
    try {
      const response = await fetch('/api/retriever/status');
      if (!response.ok) {
        throw new Error('Failed to fetch scraper status');
      }
      const data = await response.json();
      setScraperStatus(data);
    } catch (err) {
      console.error('Error fetching scraper status:', err);
    }
  };

  const handleCreate = async (formData) => {
    try {
      const response = await fetch('/api/backend/admin/system-configuration', {
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
      const response = await fetch(`/api/backend/admin/system-configuration/${datasourceId}`, {
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

  const handleGlobalConfigChange = (field, value) => {
    setGlobalConfig((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const handleSaveGlobalConfig = async () => {
    const payload = {
      ingestion_lookback_value: Number(globalConfig.ingestion_lookback_value),
      ingestion_lookback_unit: globalConfig.ingestion_lookback_unit,
    };

    try {
      setSavingGlobalConfig(true);
      const response = await fetch(
        globalConfigExists
          ? '/api/backend/admin/system-configuration/default'
          : '/api/backend/admin/system-configuration',
        {
          method: globalConfigExists ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            globalConfigExists
              ? payload
              : {
                  ...DEFAULT_GLOBAL_CONFIG,
                  ...payload,
                }
          ),
        }
      );

      if (!response.ok) {
        throw new Error('Failed to save global ingestion settings');
      }

      await fetchConfigurations();
      alert('✅ Global ingestion lookback saved');
    } catch (err) {
      alert('❌ Error saving global ingestion settings: ' + err.message);
    } finally {
      setSavingGlobalConfig(false);
    }
  };

  const handleDelete = async (datasourceId) => {
    if (!window.confirm(`Delete configuration for ${datasourceId}?`)) return;
    
    try {
      const response = await fetch(`/api/backend/admin/system-configuration/${datasourceId}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to delete configuration');
      await fetchConfigurations();
    } catch (err) {
      alert('Error deleting configuration: ' + err.message);
    }
  };

  const handleTriggerScraper = async (datasourceId, datasourceName, lastScrapedAt) => {
    // Tell the user what the scraper will actually do before proceeding
    const isFirstRun = !lastScrapedAt;
    const sinceTxt = isFirstRun
      ? 'first run — will fetch up to 30 days of history'
      : `incremental — fetching since ${new Date(lastScrapedAt).toLocaleDateString()}`;
    if (!window.confirm(`▶ Run scraper for: ${datasourceName || datasourceId}\n\nMode: ${sinceTxt}\n\nProceed?`)) return;

    try {
      const response = await fetch(`/api/retriever/scrape/datasource/${datasourceId}`, {
        method: 'POST',
      });
      if (!response.ok) throw new Error('Failed to trigger scraper');
      const data = await response.json();
      if (data.status === 'started') {
        fetchScraperStatus();
      } else {
        alert(`⚠️ ${data.message}`);
      }
    } catch (err) {
      alert('❌ Error triggering scraper: ' + err.message);
    }
  };

  // True only when THIS specific datasource is being scraped right now.
  // Uses the per-datasource list returned by the retriever (not the global count).
  const isScraperRunning = (datasourceId) => {
    const activeDsIds = scraperStatus?.active_datasource_ids;
    if (Array.isArray(activeDsIds)) return activeDsIds.includes(datasourceId);
    // Fallback: old API without active_datasource_ids — use global count but only
    // block if count is very high so we don't freeze everything for one scrape.
    return false;
  };

  const handleTriggerGroup = async (groupConfigs) => {
    const withScraper = groupConfigs.filter(c => c.scraper_type);
    if (!withScraper.length) return;
    const names = withScraper.map(c => c.name).join(', ');
    if (!window.confirm(`▶ Run all ${withScraper.length} scrapers in this group?\n\n${names}\n\nEach will fetch since its last run (or 30 days on first run). Proceed?`)) return;
    let started = 0;
    for (const cfg of withScraper) {
      try {
        const resp = await fetch(`/api/retriever/scrape/datasource/${cfg.datasource_id}`, { method: 'POST' });
        if (resp.ok) started++;
      } catch {}
    }
    fetchScraperStatus();
    if (started) fetchConfigurations();
  };

  const handleShowFolders = (config, event) => {
    if (config.folders && config.folders.length > 0) {
      setHoveredFolder(config);
      const rect = event.target.getBoundingClientRect();
      setFolderPosition({ x: rect.left, y: rect.bottom + 5 });
    }
  };

  const handleHideFolders = () => {
    setHoveredFolder(null);
  };

  const handleShowUrl = (url, event) => {
    if (url) {
      setHoveredUrl(url);
      const rect = event.target.getBoundingClientRect();
      setUrlPosition({ x: rect.left, y: rect.bottom + 5 });
    }
  };

  const handleHideUrl = () => {
    setHoveredUrl(null);
  };

  const handlePurgeQueue = async () => {
    if (!window.confirm('⚠️ WARNING: This will delete ALL pending documents in the queue!\n\nAre you sure you want to purge the queue?')) return;
    
    try {
      const response = await fetch('/api/backend/admin/purge-queue', {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Failed to purge queue');
      const data = await response.json();
      alert(`✅ Successfully purged ${data.messages_purged} messages from the queue`);
    } catch (err) {
      alert('❌ Error purging queue: ' + err.message);
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
        <div>
          <h2>Scraper Management</h2>
          <div className="status-badges">
            {scraperStatus && (
              <>
                <span className="status-badge">
                  <span className={`status-indicator ${scraperStatus.active_scrapes > 0 ? 'active' : ''}`}></span>
                  {scraperStatus.active_scrapes} Active
                </span>
                <span className="status-badge">
                  <span className="status-indicator total"></span>
                  {scraperStatus.total_datasources || configurations.length} Total
                </span>
                <span className="status-badge">
                  <span className="status-indicator today"></span>
                  {scraperStatus.total_scrapes_today || 0} Today
                </span>
              </>
            )}
          </div>
        </div>
        <div className="header-actions">
          <button
            className="btn-scrape-all"
            onClick={handleScrapeAllSources}
            title="Trigger all configured scrapers (each fetches since its last run)"
          >
            ▶ Run All Sources
          </button>
          <button className="btn-purge" onClick={handlePurgeQueue}>
            🗑 Purge Queue
          </button>
          <button className="btn-create" onClick={() => setShowCreateForm(true)}>
            + New Scraper
          </button>
        </div>
      </div>

      {showCreateForm && (
        <div className="modal-overlay" onClick={() => setShowCreateForm(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <ConfigForm
              onSubmit={handleCreate}
              onCancel={() => setShowCreateForm(false)}
              onOpenIETFGroups={() => setShowIETFGroupsModal(true)}
            />
          </div>
        </div>
      )}

      {editingConfig && (
        <div className="modal-overlay" onClick={() => setEditingConfig(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <ConfigForm
              config={configurations.find(c => c.datasource_id === editingConfig)}
              onSubmit={(data) => handleUpdate(editingConfig, data)}
              onCancel={() => setEditingConfig(null)}
              onOpenIETFGroups={() => setShowIETFGroupsModal(true)}
            />
          </div>
        </div>
      )}

      {hoveredFolder && (
        <div 
          className="folder-modal"
          style={{ 
            left: `${folderPosition.x}px`, 
            top: `${folderPosition.y}px` 
          }}
        >
          <div className="folder-modal-header">Allowed Folders</div>
          <ul className="folder-modal-list">
            {hoveredFolder.folders.map((folder, idx) => (
              <li key={idx}>{folder}</li>
            ))}
          </ul>
        </div>
      )}

      {hoveredUrl && (
        <div 
          className="url-modal"
          style={{ 
            left: `${urlPosition.x}px`, 
            top: `${urlPosition.y}px` 
          }}
        >
          <div className="url-modal-header">Resource URL</div>
          <div className="url-modal-content">{hoveredUrl}</div>
        </div>
      )}

      {showIETFGroupsModal && (
        <IETFGroupsModal isOpen={showIETFGroupsModal} onClose={() => setShowIETFGroupsModal(false)} />
      )}

      <section className="global-ingestion-card">
        <div className="global-ingestion-copy">
          <h3>Manual &amp; First-Run Lookback</h3>
          <p>
            Maximum period to look back when scraping a source for the <strong>first time</strong>,
            or when content history is reset. <br />
            <strong>Incremental scrapes always use the last run date</strong> — this setting
            does not affect automated weekly runs. Portal sources like WBA Extranet use
            their own first-run window (30 days) regardless of this value.
          </p>
        </div>

        <div className="global-ingestion-controls">
          <label className="global-ingestion-field">
            <span>Look back</span>
            <select
              value={globalConfig.ingestion_lookback_value}
              onChange={(event) =>
                handleGlobalConfigChange('ingestion_lookback_value', Number(event.target.value))
              }
            >
              {DEFAULT_LOOKBACK_VALUES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          <label className="global-ingestion-field">
            <span>Unit</span>
            <select
              value={globalConfig.ingestion_lookback_unit}
              onChange={(event) =>
                handleGlobalConfigChange('ingestion_lookback_unit', event.target.value)
              }
            >
              {LOOKBACK_UNITS.map((unit) => (
                <option key={unit} value={unit}>
                  {unit}
                </option>
              ))}
            </select>
          </label>

          <button
            className="btn-save-ingestion"
            onClick={handleSaveGlobalConfig}
            disabled={savingGlobalConfig}
          >
            {savingGlobalConfig ? 'Saving…' : 'Save'}
          </button>
        </div>
      </section>

      {configurations.length === 0 ? (
        <p className="no-configs">No scrapers configured. Create your first scraper above.</p>
      ) : (
        <div className="sc-groups">
          {groupByType(configurations).map(({ key, label, color, configs }) => {
            const isCollapsed = !!collapsedGroups[key];
            return (
              <div key={key} className="sc-group">
                <div className="sc-group-header-row">
                  <button className="sc-group-header" onClick={() => toggleGroup(key)}>
                    <span className="sc-chevron">{isCollapsed ? '▶' : '▼'}</span>
                    <span className="sc-type-dot" style={{ background: color }} />
                    <span className="sc-group-label">{label}</span>
                    <span className="sc-group-count">{configs.length}</span>
                  </button>
                  {configs.some(c => c.scraper_type) && (
                    <button
                      className="btn-run-group"
                      title={`Run all ${label} scrapers now`}
                      onClick={() => handleTriggerGroup(configs)}
                    >
                      ▶ Run all
                    </button>
                  )}
                </div>
                {!isCollapsed && (
                  <div className="sc-cards-grid">
                    {configs.map(config => {
                      const running = isScraperRunning(config.datasource_id);
                      const sched = friendlySchedule(config.scrape_schedule);
                      const lastRun = timeAgoShort(config.last_scraped_at);
                      const hasFolders = config.scraper_type === 'wfa_causeway' && config.folders?.length > 0;
                      return (
                        <div key={config.datasource_id} className={`sc-card ${running ? 'running' : ''}`}>
                          <div className="sc-card-top">
                            <div className="sc-card-name">{config.name}</div>
                            <div className="sc-card-id">{config.datasource_id}</div>
                          </div>
                          <div className="sc-card-meta">
                            {sched ? (
                              <span className="sc-meta-chip sched" title={config.scrape_schedule}>{sched}</span>
                            ) : (
                              <span className="sc-meta-chip manual">Manual</span>
                            )}
                            {config.run_on_startup && (
                              <span className="sc-meta-chip auto">Auto-start</span>
                            )}
                            {lastRun ? (
                              <span className="sc-meta-chip last">↻ {lastRun}</span>
                            ) : (
                              <span className="sc-meta-chip never">Never run</span>
                            )}
                            {hasFolders && (
                              <button
                                className="sc-meta-chip folders"
                                onMouseEnter={(e) => handleShowFolders(config, e)}
                                onMouseLeave={handleHideFolders}
                              >
                                {config.folders.length} folder{config.folders.length !== 1 ? 's' : ''}
                              </button>
                            )}
                            {config.resource_url && (
                              <button
                                className="sc-meta-chip url"
                                onMouseEnter={(e) => handleShowUrl(config.resource_url, e)}
                                onMouseLeave={handleHideUrl}
                              >
                                URL
                              </button>
                            )}
                          </div>
                          <div className="sc-card-actions">
                            {config.scraper_type && (
                              <button
                                className={`btn-action ${running ? 'btn-stop' : 'btn-run'}`}
                                onClick={() => handleTriggerScraper(config.datasource_id, config.name, config.last_scraped_at)}
                                disabled={running}
                                title={running ? 'Scraper is running' : config.last_scraped_at ? `Run now — fetch since ${new Date(config.last_scraped_at).toLocaleDateString()}` : 'Run now — first run, fetches up to 30 days'}
                              >
                                {running ? '⏸' : '▶'}
                              </button>
                            )}
                            <button
                              className="btn-action btn-edit"
                              onClick={() => setEditingConfig(config.datasource_id)}
                            >✎</button>
                            <button
                              className="btn-action btn-delete"
                              onClick={() => handleDelete(config.datasource_id)}
                            >✕</button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};


const ConfigForm = ({ config, onSubmit, onCancel, onOpenIETFGroups }) => {
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
    auth_token: config?.auth_token || '',
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
      <h3 className="form-title">{config ? 'Edit Scraper Configuration' : 'Create New Scraper'}</h3>
      
      <div className="form-grid">
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
            <option value="wba">WBA (wballiance.com)</option>
            <option value="ietf_blog">IETF Blog (ietf.org/blog)</option>
            <option value="ietf_datatracker">IETF Datatracker (datatracker.ietf.org)</option>
          </select>
          <small className="form-hint">Select the scraper to use for this datasource</small>
        </div>

        {formData.scraper_type && formData.scraper_type !== 'ietf_datatracker' && (
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
        {formData.scraper_type === 'ietf_datatracker' && (
          <div className="form-group">
            <label>IETF Working Groups:</label>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => onOpenIETFGroups && onOpenIETFGroups()}
            >
              Configure IETF Groups →
            </button>
            <small className="form-hint">Select IETF areas and working groups to scrape</small>
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
      </div>

      {/* Credentials — shown for authenticated portal scrapers */}
      {formData.scraper_type === 'wba_extranet' && (
        <div className="credentials-section">
          <h4 className="credentials-title">🔑 Authentication Token</h4>
          <p className="credentials-hint">
            Enter the <strong>HLLogin</strong> cookie value from your browser
            (DevTools → Application → Cookies → <code>extranet.wballiance.com</code> →{' '}
            <code>HLLogin</code>). This token expires after ~7 days — refresh it when
            scraping stops working.
          </p>
          <div className="form-group">
            <label htmlFor="auth_token">HLLogin Token:</label>
            <textarea
              id="auth_token"
              name="auth_token"
              className="auth-token-input"
              value={formData.auth_token}
              onChange={handleChange}
              rows={3}
              placeholder="Paste HLLogin cookie value here (975-char hex string)…"
              spellCheck={false}
            />
            {formData.auth_token && (
              <small className="credentials-status credentials-set">
                ✓ Token set ({formData.auth_token.length} chars)
                {formData.auth_token.length < 900 && ' — looks short, double-check the value'}
              </small>
            )}
            {!formData.auth_token && (
              <small className="credentials-status credentials-missing">
                No token — scraper will use env var WBA_EXTRANET_HLLOGIN if set
              </small>
            )}
          </div>
        </div>
      )}

      <details className="advanced-section">
        <summary>Advanced Settings</summary>
        <div className="form-grid">
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
            <>
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
            </>
          )}
          
          {isCausewayDatasource && (
            <div className="form-group form-group-full">
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
        </div>
      </details>

      <div className="form-actions">
        <button type="submit" className="btn-submit">
          {config ? 'Save Changes' : 'Create Scraper'}
        </button>
        <button type="button" className="btn-cancel" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
};

export default AdminSystemConfig;
