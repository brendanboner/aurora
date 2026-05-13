import React, { useState, useEffect, useCallback } from 'react';
import './AdminMonitoring.css';

// ── Source label helpers ──────────────────────────────────────────────────────

const SOURCE_PREFIXES = [
  { prefix: 'wba_extranet', label: 'WBA Extranet', short: 'WBA' },
  { prefix: 'wba_',         label: 'WBA',           short: 'WBA' },
  { prefix: 'wfa_causeway', label: 'WFA Causeway',  short: 'WFA' },
  { prefix: 'wfa_',         label: 'WFA',           short: 'WFA' },
  { prefix: 'ietf_wg_',     label: 'IETF',          short: 'IETF' },
  { prefix: 'ietf_',        label: 'IETF',          short: 'IETF' },
  { prefix: 'ieee802_',     label: 'IEEE 802',       short: 'IEEE' },
  { prefix: 'mef_',         label: 'MEF',            short: 'MEF' },
  { prefix: 'nist_',        label: 'NIST',           short: 'NIST' },
  { prefix: 'onf_',         label: 'ONF',            short: 'ONF' },
  { prefix: 'dmtf_',        label: 'DMTF',           short: 'DMTF' },
  { prefix: 'youtube',      label: 'YouTube',        short: 'YT' },
];

function parseSource(datasource_id) {
  if (!datasource_id) return { source: 'Unknown', short: '?', suffix: '' };
  const id = datasource_id.toLowerCase();
  for (const { prefix, label, short } of SOURCE_PREFIXES) {
    if (id.startsWith(prefix)) {
      const suffix = datasource_id.slice(prefix.length).replace(/_/g, ' ').trim();
      return { source: label, short, suffix };
    }
  }
  return { source: datasource_id, short: datasource_id.slice(0, 4).toUpperCase(), suffix: '' };
}

function sourceLabel(datasource_id, display_name) {
  if (display_name && display_name !== datasource_id) return display_name;
  const { source, suffix } = parseSource(datasource_id);
  return suffix ? `${source} · ${suffix}` : source;
}

function timeAgo(isoString) {
  if (!isoString) return '';
  const delta = Math.floor((Date.now() - new Date(isoString)) / 1000);
  if (delta < 5)  return 'just now';
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  return `${Math.floor(delta / 3600)}h ago`;
}

function elapsed(isoString) {
  if (!isoString) return '';
  const delta = Math.floor((Date.now() - new Date(isoString)) / 1000);
  if (delta < 60) return `${delta}s`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ${delta % 60}s`;
  return `${Math.floor(delta / 3600)}h ${Math.floor((delta % 3600) / 60)}m`;
}

// ── Status dot ────────────────────────────────────────────────────────────────

function StatusDot({ active, label }) {
  return (
    <span className={`mon-dot-row ${active ? 'active' : 'inactive'}`}>
      <span className="mon-dot" />
      <span className="mon-dot-label">{label}</span>
      <span className="mon-dot-state">{active ? 'Active' : 'Idle'}</span>
    </span>
  );
}

// ── Currently-processing card ─────────────────────────────────────────────────

function ProcessingCard({ service, item, active }) {
  if (!active && !item) {
    return (
      <div className="mon-proc-card idle">
        <div className="mon-proc-service">{service}</div>
        <div className="mon-proc-idle">Idle</div>
      </div>
    );
  }
  const { source, suffix } = item?.datasource_id ? parseSource(item.datasource_id) : {};
  return (
    <div className="mon-proc-card active">
      <div className="mon-proc-service">{service}</div>
      {item ? (
        <>
          <div className="mon-proc-source">
            <span className="mon-src-badge">{source || '—'}</span>
            {suffix && <span className="mon-src-suffix">{suffix}</span>}
          </div>
          <div className="mon-proc-title" title={item.title}>{item.title}</div>
          <div className="mon-proc-stage">{item.stage || item.status}</div>
        </>
      ) : (
        <div className="mon-proc-idle">Heartbeat active — waiting for item</div>
      )}
    </div>
  );
}

// ── Batch row ─────────────────────────────────────────────────────────────────

function BatchRow({ batch }) {
  const label = sourceLabel(batch.datasource_id, batch.display_name);
  const pct = Math.min(100, Math.round(batch.progress_percent));
  const statusColor = batch.status === 'digesting' ? 'digesting' : 'retrieving';
  // Show datasource_id as subtitle only when it differs meaningfully from the label
  const showSubtitle = batch.datasource_id && batch.datasource_id !== label;
  return (
    <div className="mon-batch-row">
      <div className="mon-batch-meta">
        <div className="mon-batch-name-col">
          <span className="mon-batch-name">{label}</span>
          {showSubtitle && (
            <span className="mon-batch-id">{batch.datasource_id}</span>
          )}
        </div>
        <span className={`mon-batch-status ${statusColor}`}>{batch.status}</span>
        {batch.started_at && (
          <span className="mon-batch-elapsed">↑ {elapsed(batch.started_at)}</span>
        )}
      </div>
      <div className="mon-batch-progress-row">
        <div className="mon-batch-bar">
          <div className="mon-batch-fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="mon-batch-count">
          {batch.items_digested}/{batch.items_scraped}
          <span className="mon-batch-pct"> {pct}%</span>
        </span>
      </div>
    </div>
  );
}

// ── Queue group ───────────────────────────────────────────────────────────────

function QueueGroup({ sourceKey, items, expanded, onToggle }) {
  const { source, suffix } = parseSource(sourceKey);
  const label = suffix ? `${source} · ${suffix}` : source;
  return (
    <div className="mon-queue-group">
      <button className="mon-queue-group-header" onClick={onToggle}>
        <span className="mon-queue-chevron">{expanded ? '▼' : '▶'}</span>
        <span className="mon-queue-src-label">{label}</span>
        <span className="mon-queue-count">{items.length}</span>
      </button>
      {expanded && (
        <div className="mon-queue-items">
          {items.slice(0, 20).map((r, i) => (
            <div key={i} className="mon-queue-item">
              <span className="mon-queue-pos">{r.position}</span>
              <span className="mon-queue-type">{r.message_type === 'event' ? '📅' : r.category || '📄'}</span>
              <span className="mon-queue-title" title={r.title}>{r.title}</span>
              {r.publish_date && <span className="mon-queue-date">{r.publish_date}</span>}
            </div>
          ))}
          {items.length > 20 && (
            <div className="mon-queue-more">+{items.length - 20} more</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Activity feed ─────────────────────────────────────────────────────────────

function ActivityFeed({ completed, failed, onSelect, onClearCompleted, onClearFailed }) {
  const allItems = [
    ...completed.map(i => ({ ...i, _outcome: 'completed' })),
    ...failed.map(i => ({ ...i, _outcome: 'failed' })),
  ].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)).slice(0, 30);

  return (
    <div className="mon-activity">
      <div className="mon-section-header">
        <h2>Recent Activity</h2>
        <div className="mon-activity-actions">
          {completed.length > 0 && (
            <button className="mon-clear-btn" onClick={onClearCompleted}>Clear completed</button>
          )}
          {failed.length > 0 && (
            <button className="mon-clear-btn danger" onClick={onClearFailed}>Clear failed</button>
          )}
        </div>
      </div>
      {allItems.length === 0 ? (
        <div className="mon-empty">No recent activity</div>
      ) : (
        <div className="mon-activity-list">
          {allItems.map((item, i) => {
            const { source, suffix } = parseSource(item.datasource_id);
            return (
              <div
                key={i}
                className={`mon-activity-row ${item._outcome} clickable`}
                onClick={() => onSelect(item)}
              >
                <span className={`mon-activity-icon ${item._outcome}`}>
                  {item._outcome === 'completed' ? '✓' : '✗'}
                </span>
                <div className="mon-activity-body">
                  <div className="mon-activity-title" title={item.title}>{item.title}</div>
                  <div className="mon-activity-meta">
                    <span className="mon-src-badge small">{source}</span>
                    {suffix && <span className="mon-src-suffix small">{suffix}</span>}
                    {item.category && <span className="mon-cat">{item.category}</span>}
                  </div>
                </div>
                <span className="mon-activity-time">{timeAgo(item.updated_at)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Document detail modal ─────────────────────────────────────────────────────

function DetailModal({ doc, onClose }) {
  if (!doc) return null;
  return (
    <div className="mon-modal-overlay" onClick={onClose}>
      <div className="mon-modal" onClick={e => e.stopPropagation()}>
        <div className="mon-modal-header">
          <h2>Document Details</h2>
          <button className="mon-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="mon-modal-body">
          <Section title="Basic Information">
            <Row label="Title" value={doc.title} />
            <Row label="URL" value={<a href={doc.url} target="_blank" rel="noopener noreferrer">{doc.url}</a>} />
            <Row label="Category" value={doc.category} />
            {doc.datasource_id && <Row label="Source" value={sourceLabel(doc.datasource_id)} />}
            {doc.publish_date && <Row label="Published" value={doc.publish_date} />}
            {doc.uploaded_by && <Row label="Uploaded by" value={doc.uploaded_by} />}
          </Section>
          <Section title="Processing">
            <Row label="Status" value={<span className={`mon-badge ${doc.status}`}>{doc.status}</span>} />
            <Row label="Stage" value={doc.stage} />
            <Row label="Started" value={doc.started_at ? new Date(doc.started_at).toLocaleString() : '—'} />
            <Row label="Updated" value={doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '—'} />
            {doc.error && <Row label="Error" value={<span className="mon-error-text">{doc.error}</span>} />}
          </Section>
          {doc.metadata?.nodes?.resource && (
            <Section title="Summary">
              <Row label="Summary" value={doc.metadata.nodes.resource.summary} />
              <Row label="Importance" value={`${Math.round((doc.metadata.nodes.resource.importance || 0) * 100)}%`} />
            </Section>
          )}
          {doc.metadata?.nodes?.topics?.length > 0 && (
            <Section title={`Topics (${doc.metadata.nodes.topics.length})`}>
              <div className="mon-tag-list">
                {doc.metadata.nodes.topics.map((t, i) => (
                  <span key={i} className="mon-tag">{t.name}</span>
                ))}
              </div>
            </Section>
          )}
          {doc.metadata?.nodes?.people?.length > 0 && (
            <Section title={`People (${doc.metadata.nodes.people.length})`}>
              <div className="mon-tag-list">
                {doc.metadata.nodes.people.map((p, i) => (
                  <span key={i} className="mon-tag">{p.name}</span>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="mon-detail-section">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="mon-detail-row">
      <span className="mon-detail-label">{label}</span>
      <span className="mon-detail-value">{value}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const AdminMonitoring = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/backend/admin/dashboard');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError('Failed to load monitoring data');
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const handleClear = async (endpoint) => {
    await fetch(`/api/backend/admin/${endpoint}`, { method: 'DELETE' });
    load();
  };

  const toggleGroup = (key) =>
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));

  const ps   = data?.processing_status;
  const qs   = data?.queue_status;
  const batches = data?.active_batches || [];

  // Group queue items by datasource_id
  const queueGroups = {};
  (qs?.resources || []).forEach(r => {
    const key = r.datasource_id || 'unknown';
    if (!queueGroups[key]) queueGroups[key] = [];
    queueGroups[key].push(r);
  });

  // Sort groups: largest first
  const sortedGroups = Object.entries(queueGroups)
    .sort(([, a], [, b]) => b.length - a.length);

  const totalQueue = (qs?.message_count) || 0;
  const retrieverActive = ps?.retriever_active;
  const digesterActive  = ps?.digester_active;

  return (
    <div className="mon-container">

      {/* ── Status strip ── */}
      <div className="mon-strip">
        <div className="mon-strip-left">
          <h1 className="mon-title">System Monitoring</h1>
          <StatusDot active={retrieverActive} label="Retriever" />
          <StatusDot active={digesterActive}  label="Digester" />
        </div>
        <div className="mon-strip-right">
          <div className="mon-metric">
            <span className="mon-metric-value">{totalQueue}</span>
            <span className="mon-metric-label">queued</span>
          </div>
          <div className="mon-metric">
            <span className="mon-metric-value">{batches.length}</span>
            <span className="mon-metric-label">active batches</span>
          </div>
          <div className="mon-metric">
            <span className="mon-metric-value">{qs?.consumer_count ?? '—'}</span>
            <span className="mon-metric-label">consumers</span>
          </div>
          {lastUpdated && (
            <span className="mon-refresh-ts">↻ {timeAgo(lastUpdated.toISOString())}</span>
          )}
        </div>
      </div>

      {error && <div className="mon-error-bar">{error}</div>}

      <div className="mon-body">

        {/* ── Currently processing ── */}
        <div className="mon-section">
          <h2>Currently Processing</h2>
          <div className="mon-proc-grid">
            <ProcessingCard
              service="Retriever"
              item={ps?.retriever_current}
              active={retrieverActive}
            />
            <ProcessingCard
              service="Digester"
              item={ps?.digester_current}
              active={digesterActive}
            />
          </div>
        </div>

        {/* ── Active batches ── */}
        {batches.length > 0 && (
          <div className="mon-section">
            <h2>Active Batches <span className="mon-count-badge">{batches.length}</span></h2>
            <div className="mon-batch-list">
              {batches.map(b => <BatchRow key={b.batch_id} batch={b} />)}
            </div>
          </div>
        )}

        {/* ── Queue ── */}
        <div className="mon-section">
          <h2>
            Queue
            {totalQueue > 0 && (
              <span className="mon-queue-summary">
                <span className="mon-queue-chip ready">{qs.messages_ready} ready</span>
                <span className="mon-queue-chip processing">{qs.messages_unacked} processing</span>
              </span>
            )}
          </h2>
          {totalQueue === 0 ? (
            <div className="mon-empty">Queue is empty</div>
          ) : sortedGroups.length === 0 ? (
            <div className="mon-empty">{totalQueue} messages (details unavailable)</div>
          ) : (
            <div className="mon-queue-groups">
              {sortedGroups.map(([key, items]) => (
                <QueueGroup
                  key={key}
                  sourceKey={key}
                  items={items}
                  expanded={!!expandedGroups[key]}
                  onToggle={() => toggleGroup(key)}
                />
              ))}
            </div>
          )}
        </div>

        {/* ── Recent activity ── */}
        <ActivityFeed
          completed={ps?.recent_completed || []}
          failed={ps?.recent_failed || []}
          onSelect={setSelectedDoc}
          onClearCompleted={() => handleClear('clear-completed')}
          onClearFailed={() => handleClear('clear-failed')}
        />

      </div>

      <DetailModal doc={selectedDoc} onClose={() => setSelectedDoc(null)} />
    </div>
  );
};

export default AdminMonitoring;
