import React, { useState, useEffect, useCallback } from 'react';
import './AdminMonitoring.css';

// ── Helpers ───────────────────────────────────────────────────────────────────

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
  if (!isoString) return '—';
  const delta = Math.floor((Date.now() - new Date(isoString)) / 1000);
  if (delta < 5)    return 'just now';
  if (delta < 60)   return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

function elapsed(isoString) {
  if (!isoString) return '';
  const delta = Math.floor((Date.now() - new Date(isoString)) / 1000);
  if (delta < 60)   return `${delta}s`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ${delta % 60}s`;
  return `${Math.floor(delta / 3600)}h ${Math.floor((delta % 3600) / 60)}m`;
}

// ── Collapsible section wrapper ───────────────────────────────────────────────

function Section({ title, badge, badgeClass, defaultOpen = false, children, action }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mon-section">
      <button className="mon-section-toggle" onClick={() => setOpen(o => !o)}>
        <span className="mon-section-chevron">{open ? '▼' : '▶'}</span>
        <h2 className="mon-section-title">
          {title}
          {badge != null && (
            <span className={`mon-count-badge ${badgeClass || ''}`}>{badge}</span>
          )}
        </h2>
        {action && <span className="mon-section-action" onClick={e => e.stopPropagation()}>{action}</span>}
      </button>
      {open && <div className="mon-section-body">{children}</div>}
    </div>
  );
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
  const isStalled = batch.stalled;
  return (
    <div className={`mon-batch-row ${isStalled ? 'stalled' : ''}`}>
      <div className="mon-batch-meta">
        <div className="mon-batch-name-col">
          <span className="mon-batch-name">{label}</span>
          {isStalled && <span className="mon-stalled-badge">stalled</span>}
          {batch.datasource_id && batch.datasource_id !== label && (
            <span className="mon-batch-id">{batch.datasource_id}</span>
          )}
        </div>
        <span className={`mon-batch-status ${batch.status}`}>{batch.status}</span>
        {batch.started_at && (
          <span className={`mon-batch-elapsed ${isStalled ? 'stalled' : ''}`}>
            ↑ {elapsed(batch.started_at)}
          </span>
        )}
      </div>
      <div className="mon-batch-progress-row">
        <div className="mon-batch-bar">
          <div className={`mon-batch-fill ${isStalled ? 'stalled' : ''}`} style={{ width: `${pct}%` }} />
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

// ── Scheduler section ─────────────────────────────────────────────────────────

function SchedulerSection({ scheduler, onRunNow, runningIds = new Set() }) {
  if (!scheduler) return null;
  const overdue = (scheduler.datasource_schedules || []).filter(d => d.overdue);
  const noSchedule = (scheduler.datasource_schedules || []).filter(d => !d.schedule);

  return (
    <div className="mon-scheduler">
      {scheduler.dev_mode && (
        <div className="mon-warn-bar">
          ⚠ Scheduler is in DEV MODE — automatic scrapes are disabled. Trigger sources manually.
        </div>
      )}
      {!scheduler.dev_mode && !scheduler.scheduler_running && (
        <div className="mon-warn-bar danger">
          ✗ Scheduler is not running — no automatic scrapes will fire.
        </div>
      )}
      {scheduler.error && (
        <div className="mon-warn-bar danger">Could not reach retriever: {scheduler.error}</div>
      )}

      <div className="mon-sched-stats">
        <div className="mon-sched-stat">
          <span className="mon-sched-val">{scheduler.total_datasources}</span>
          <span className="mon-sched-lbl">sources</span>
        </div>
        <div className="mon-sched-stat">
          <span className="mon-sched-val">{scheduler.active_scrapes}</span>
          <span className="mon-sched-lbl">active now</span>
        </div>
        <div className="mon-sched-stat">
          <span className="mon-sched-val">{scheduler.total_scrapes_today}</span>
          <span className="mon-sched-lbl">scrapes today</span>
        </div>
        {overdue.length > 0 && (
          <div className="mon-sched-stat warn">
            <span className="mon-sched-val">{overdue.length}</span>
            <span className="mon-sched-lbl">overdue</span>
          </div>
        )}
      </div>

      {overdue.length > 0 && (
        <div className="mon-sched-overdue">
          <div className="mon-sched-overdue-title">Overdue Sources</div>
          {overdue.map(d => {
            const running = runningIds.has(d.datasource_id);
            return (
              <div key={d.datasource_id} className="mon-sched-row overdue">
                <span className="mon-sched-name">{d.name || d.datasource_id}</span>
                <span className="mon-sched-cron">{d.schedule || 'no schedule'}</span>
                <span className="mon-sched-last">
                  {d.last_scraped_at ? `last: ${timeAgo(d.last_scraped_at)}` : 'never scraped'}
                </span>
                {onRunNow && (
                  <button
                    className={`mon-run-btn${running ? ' running' : ''}`}
                    title="Run now"
                    disabled={running}
                    onClick={() => onRunNow(d.datasource_id)}
                  >
                    {running ? '…' : '▶'}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {noSchedule.length > 0 && (
        <div className="mon-sched-noschedule">
          <div className="mon-sched-overdue-title" style={{ color: 'var(--muted-foreground)' }}>
            No Schedule Configured ({noSchedule.length})
          </div>
          {noSchedule.map(d => (
            <div key={d.datasource_id} className="mon-sched-row">
              <span className="mon-sched-name">{d.name || d.datasource_id}</span>
              <span className="mon-sched-last">
                {d.last_scraped_at ? `last: ${timeAgo(d.last_scraped_at)}` : 'never'}
              </span>
            </div>
          ))}
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
      <div className="mon-activity-actions">
        {completed.length > 0 && (
          <button className="mon-clear-btn" onClick={onClearCompleted}>Clear completed</button>
        )}
        {failed.length > 0 && (
          <button className="mon-clear-btn danger" onClick={onClearFailed}>Clear failed</button>
        )}
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
          <ModalSection title="Basic Information">
            <ModalRow label="Title" value={doc.title} />
            <ModalRow label="URL" value={<a href={doc.url} target="_blank" rel="noopener noreferrer">{doc.url}</a>} />
            <ModalRow label="Category" value={doc.category} />
            {doc.datasource_id && <ModalRow label="Source" value={sourceLabel(doc.datasource_id)} />}
            {doc.publish_date && <ModalRow label="Published" value={doc.publish_date} />}
          </ModalSection>
          <ModalSection title="Processing">
            <ModalRow label="Status" value={<span className={`mon-badge ${doc.status}`}>{doc.status}</span>} />
            <ModalRow label="Stage" value={doc.stage} />
            <ModalRow label="Started" value={doc.started_at ? new Date(doc.started_at).toLocaleString() : '—'} />
            <ModalRow label="Updated" value={doc.updated_at ? new Date(doc.updated_at).toLocaleString() : '—'} />
            {doc.error && <ModalRow label="Error" value={<span className="mon-error-text">{doc.error}</span>} />}
          </ModalSection>
          {doc.metadata?.nodes?.resource && (
            <ModalSection title="Summary">
              <ModalRow label="Summary" value={doc.metadata.nodes.resource.summary} />
              <ModalRow label="Importance" value={`${Math.round((doc.metadata.nodes.resource.importance || 0) * 100)}%`} />
            </ModalSection>
          )}
          {doc.metadata?.nodes?.topics?.length > 0 && (
            <ModalSection title={`Topics (${doc.metadata.nodes.topics.length})`}>
              <div className="mon-tag-list">
                {doc.metadata.nodes.topics.map((t, i) => <span key={i} className="mon-tag">{t.name}</span>)}
              </div>
            </ModalSection>
          )}
          {doc.metadata?.nodes?.people?.length > 0 && (
            <ModalSection title={`People (${doc.metadata.nodes.people.length})`}>
              <div className="mon-tag-list">
                {doc.metadata.nodes.people.map((p, i) => <span key={i} className="mon-tag">{p.name}</span>)}
              </div>
            </ModalSection>
          )}
        </div>
      </div>
    </div>
  );
}

function ModalSection({ title, children }) {
  return <div className="mon-detail-section"><h3>{title}</h3>{children}</div>;
}
function ModalRow({ label, value }) {
  return (
    <div className="mon-detail-row">
      <span className="mon-detail-label">{label}</span>
      <span className="mon-detail-value">{value}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

const AdminMonitoring = () => {
  const [data, setData]             = useState(null);
  const [error, setError]           = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  const [fixingStalled, setFixingStalled] = useState(false);
  const [runningIds, setRunningIds]       = useState(new Set());

  const handleRunNow = async (datasourceId) => {
    setRunningIds(prev => new Set(prev).add(datasourceId));
    try {
      const res = await fetch(`/api/retriever/scrape/datasource/${datasourceId}`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      alert(`Failed to start scraper: ${err.message}`);
    } finally {
      setTimeout(() => setRunningIds(prev => {
        const next = new Set(prev);
        next.delete(datasourceId);
        return next;
      }), 8000);
    }
  };

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/backend/admin/dashboard');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
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

  const handleFixStalled = async () => {
    setFixingStalled(true);
    try {
      await fetch('/api/backend/admin/fix-stalled-batches', { method: 'POST' });
      await load();
    } finally {
      setFixingStalled(false);
    }
  };

  const toggleGroup = (key) =>
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));

  const ps      = data?.processing_status;
  const qs      = data?.queue_status;
  const batches = data?.active_batches || [];
  const sched   = data?.scheduler;

  const stalledBatches  = batches.filter(b => b.stalled);
  const activeBatches   = batches.filter(b => !b.stalled);

  const queueGroups = {};
  (qs?.resources || []).forEach(r => {
    const key = r.datasource_id || 'unknown';
    if (!queueGroups[key]) queueGroups[key] = [];
    queueGroups[key].push(r);
  });
  const sortedGroups = Object.entries(queueGroups).sort(([, a], [, b]) => b.length - a.length);
  const totalQueue = qs?.message_count || 0;

  const recentCompleted = ps?.recent_completed || [];
  const recentFailed    = ps?.recent_failed || [];
  const totalActivity   = recentCompleted.length + recentFailed.length;

  return (
    <div className="mon-container">

      {/* ── Status strip ── */}
      <div className="mon-strip">
        <div className="mon-strip-left">
          <h1 className="mon-title">System Monitoring</h1>
          <StatusDot active={ps?.retriever_active} label="Retriever" />
          <StatusDot active={ps?.digester_active}  label="Digester" />
          {sched && (
            <span className={`mon-dot-row ${sched.scheduler_running ? 'active' : 'inactive'}`}>
              <span className="mon-dot" />
              <span className="mon-dot-label">Scheduler</span>
              <span className="mon-dot-state">
                {sched.dev_mode ? 'Dev Mode' : sched.scheduler_running ? 'Active' : 'Stopped'}
              </span>
            </span>
          )}
        </div>
        <div className="mon-strip-right">
          <div className="mon-metric">
            <span className="mon-metric-value">{totalQueue}</span>
            <span className="mon-metric-label">queued</span>
          </div>
          <div className="mon-metric">
            <span className="mon-metric-value">{activeBatches.length}</span>
            <span className="mon-metric-label">active batches</span>
          </div>
          {stalledBatches.length > 0 && (
            <div className="mon-metric warn">
              <span className="mon-metric-value">{stalledBatches.length}</span>
              <span className="mon-metric-label">stalled</span>
            </div>
          )}
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

        {/* ── Recent Activity — open by default, most useful section ── */}
        <Section
          title="Recent Activity"
          badge={totalActivity || null}
          defaultOpen={true}
        >
          <ActivityFeed
            completed={recentCompleted}
            failed={recentFailed}
            onSelect={setSelectedDoc}
            onClearCompleted={() => handleClear('clear-completed')}
            onClearFailed={() => handleClear('clear-failed')}
          />
        </Section>

        {/* ── Stalled batches — open by default if any exist ── */}
        {stalledBatches.length > 0 && (
          <Section
            title="Stalled Batches"
            badge={stalledBatches.length}
            badgeClass="warn"
            defaultOpen={true}
            action={
              <button
                className="mon-clear-btn danger"
                onClick={handleFixStalled}
                disabled={fixingStalled}
              >
                {fixingStalled ? 'Fixing…' : 'Mark all failed'}
              </button>
            }
          >
            <div className="mon-warn-bar">
              These batches have been running for over 2 hours and are likely stuck.
              The digester probably restarted mid-run without marking them complete.
            </div>
            <div className="mon-batch-list">
              {stalledBatches.map(b => <BatchRow key={b.batch_id} batch={b} />)}
            </div>
          </Section>
        )}

        {/* ── Active batches — collapsed by default ── */}
        <Section
          title="Active Batches"
          badge={activeBatches.length || null}
          defaultOpen={false}
        >
          {activeBatches.length === 0 ? (
            <div className="mon-empty">No active batches</div>
          ) : (
            <div className="mon-batch-list">
              {activeBatches.map(b => <BatchRow key={b.batch_id} batch={b} />)}
            </div>
          )}
        </Section>

        {/* ── Currently processing — collapsed by default ── */}
        <Section title="Currently Processing" defaultOpen={false}>
          <div className="mon-proc-grid">
            <ProcessingCard service="Retriever" item={ps?.retriever_current} active={ps?.retriever_active} />
            <ProcessingCard service="Digester"  item={ps?.digester_current}  active={ps?.digester_active} />
          </div>
        </Section>

        {/* ── Scheduler / sources ── */}
        {sched && (
          <Section
            title="Sources & Scheduler"
            badge={sched.datasource_schedules?.filter(d => d.overdue).length || null}
            badgeClass="warn"
            defaultOpen={false}
          >
            <SchedulerSection scheduler={sched} onRunNow={handleRunNow} runningIds={runningIds} />
          </Section>
        )}

        {/* ── Queue — collapsed by default ── */}
        <Section
          title="Queue"
          badge={totalQueue || null}
          defaultOpen={false}
        >
          {totalQueue === 0 ? (
            <div className="mon-empty">Queue is empty</div>
          ) : sortedGroups.length === 0 ? (
            <div className="mon-empty">{totalQueue} messages (details unavailable)</div>
          ) : (
            <>
              <div className="mon-queue-summary-row">
                <span className="mon-queue-chip ready">{qs?.messages_ready ?? 0} ready</span>
                <span className="mon-queue-chip processing">{qs?.messages_unacked ?? 0} processing</span>
              </div>
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
            </>
          )}
        </Section>

      </div>

      <DetailModal doc={selectedDoc} onClose={() => setSelectedDoc(null)} />
    </div>
  );
};

export default AdminMonitoring;
