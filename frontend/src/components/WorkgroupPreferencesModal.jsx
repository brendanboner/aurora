/**
 * WorkgroupPreferencesModal — thin wrapper around PreferencesPanel.
 *
 * Preserved for backward-compatibility with the Chatbot quick-access button.
 * Opens the Groups tab by default. All logic lives in PreferencesPanel.
 */
import React from 'react';
import PreferencesPanel from './PreferencesPanel';
import './WorkgroupPreferencesModal.css';

/**
 * WorkgroupPreferencesModal
 *
 * Lets users join (boost) or ignore (hard-exclude) data sources.
 * Changes are saved instantly on toggle — no submit button needed.
 *
 * Rules:
 *   - Joined  → results from this source are boosted
 *   - Ignored → results from this source are completely excluded
 *   - Ignore overrides Join (when Ignore is on, Join is disabled)
 *   - Default (neither) → standard behaviour, nothing changes
 */
export default function WorkgroupPreferencesModal({ userId, onClose }) {
  return (
    <div className="wgp-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="wgp-modal" role="dialog" aria-modal="true" aria-labelledby="wgp-title"
           style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '80vh' }}>
        <PreferencesPanel userId={userId} defaultTab="group" onClose={onClose} />
      </div>
    </div>
  );
}

// Dead code below kept only for reference — logic moved to PreferencesPanel.
// eslint-disable-next-line no-unused-vars
function _LegacyWorkgroupPreferencesModal({ userId, onClose }) {
  const [datasources, setDatasources] = useState({ public: [], workgroup: [], ietfWg: [] });
  const [collapsedAreas, setCollapsedAreas] = useState({});
  const [memberships, setMemberships] = useState({ joined: [], ignored: [] });
  const [loading, setLoading] = useState(true);
  const [rowState, setRowState] = useState({}); // { [datasourceId]: 'saving' | 'error' | null }

  // Fetch datasources + current memberships on open
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    Promise.all([
      getListableDatasources(),
      getUserSourceMemberships(userId),
    ])
      .then(([sources, mems]) => {
        if (cancelled) return;
        const publicSources = sources.filter((s) => s.category === 'public');
        const workgroups = sources.filter((s) => s.category === 'workgroup' && !s.area_acronym);
        const ietfWgs = sources.filter((s) => s.category === 'workgroup' && s.area_acronym);
        setDatasources({ public: publicSources, workgroup: workgroups, ietfWg: ietfWgs });
        setMemberships(mems);
      })
      .catch((err) => {
        console.error('WorkgroupPreferencesModal: failed to load', err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [userId]);

  const isJoined = (id) => memberships.joined.includes(id);
  const isIgnored = (id) => memberships.ignored.includes(id);

  const setRowSaving = (id, state) =>
    setRowState((prev) => ({ ...prev, [id]: state }));

  const handleToggle = useCallback(
    async (datasourceId, action) => {
      // action: 'join' | 'leave' | 'ignore' | 'unignore'
      setRowSaving(datasourceId, 'saving');
      try {
        if (action === 'join') {
          await upsertSourceMembership(userId, datasourceId, 'joined');
          setMemberships((prev) => ({
            joined: [...prev.joined.filter((x) => x !== datasourceId), datasourceId],
            ignored: prev.ignored.filter((x) => x !== datasourceId),
          }));
        } else if (action === 'leave') {
          await deleteSourceMembership(userId, datasourceId);
          setMemberships((prev) => ({
            ...prev,
            joined: prev.joined.filter((x) => x !== datasourceId),
          }));
        } else if (action === 'ignore') {
          await upsertSourceMembership(userId, datasourceId, 'ignored');
          setMemberships((prev) => ({
            joined: prev.joined.filter((x) => x !== datasourceId),
            ignored: [...prev.ignored.filter((x) => x !== datasourceId), datasourceId],
          }));
        } else if (action === 'unignore') {
          await deleteSourceMembership(userId, datasourceId);
          setMemberships((prev) => ({
            ...prev,
            ignored: prev.ignored.filter((x) => x !== datasourceId),
          }));
        }
        setRowSaving(datasourceId, null);
      } catch (err) {
        console.error('WorkgroupPreferencesModal: save failed', err);
        setRowSaving(datasourceId, 'error');
        // Clear error indicator after 3 s
        setTimeout(() => setRowSaving(datasourceId, null), 3000);
      }
    },
    [userId]
  );

  // Close on Escape key
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const renderRow = (source) => {
    const { datasource_id: id, name, fetch_url } = source;
    const joined = isJoined(id);
    const ignored = isIgnored(id);
    const saving = rowState[id] === 'saving';
    const error = rowState[id] === 'error';

    return (
      <div key={id} className="wgp-source-row">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="wgp-source-name" title={name}>{name}</div>
          {fetch_url && (
            <div className="wgp-source-url" title={fetch_url}>{fetch_url}</div>
          )}
        </div>

        <div className="wgp-toggle-group">
          {/* Join / Leave toggle */}
          <button
            className={`wgp-toggle-btn${joined ? ' active-join' : ''}`}
            disabled={saving || ignored}
            title={ignored ? 'Remove Ignore to enable Join' : joined ? 'Leave this source' : 'Join this source (boost results)'}
            onClick={() => handleToggle(id, joined ? 'leave' : 'join')}
          >
            {joined ? 'Leave' : 'Join'}
          </button>

          {/* Ignore toggle — overrides Join */}
          <button
            className={`wgp-toggle-btn${ignored ? ' active-ignore' : ''}`}
            disabled={saving}
            title={ignored ? 'Stop ignoring this source' : 'Ignore this source (exclude from results)'}
            onClick={() => handleToggle(id, ignored ? 'unignore' : 'ignore')}
          >
            {ignored ? 'Unignore' : 'Ignore'}
          </button>
        </div>

        {/* Per-row status indicators */}
        {saving && <div className="wgp-spinner" aria-label="Saving…" />}
        {error && <span className="wgp-error-icon" title="Save failed — please try again">⚠️</span>}
      </div>
    );
  };

  return (
    <div className="wgp-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="wgp-modal" role="dialog" aria-modal="true" aria-labelledby="wgp-title">
        <div className="wgp-header">
          <h2 className="wgp-title" id="wgp-title">Source Preferences</h2>
          <button className="wgp-close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="wgp-body">
          {loading ? (
            <div className="wgp-loading">
              <div className="wgp-spinner" />
              Loading sources…
            </div>
          ) : (
            <>
              {/* Public Sources section */}
              <div className="wgp-section">
                <p className="wgp-section-title">Public Sources</p>
                {datasources.public.length === 0 ? (
                  <div className="wgp-empty">No public sources available.</div>
                ) : (
                  datasources.public.map(renderRow)
                )}
              </div>

              {/* Workgroups section */}
              <div className="wgp-section">
                <p className="wgp-section-title">Workgroups</p>
                {datasources.workgroup.length === 0 ? (
                  <div className="wgp-empty">No workgroups available.</div>
                ) : (
                  datasources.workgroup.map(renderRow)
                )}
              </div>

              {/* IETF Working Groups section — only shown when IETF WGs exist */}
              {datasources.ietfWg.length > 0 && (() => {
                const byArea = Object.entries(
                  datasources.ietfWg.reduce((acc, wg) => {
                    if (!acc[wg.area_acronym]) acc[wg.area_acronym] = [];
                    acc[wg.area_acronym].push(wg);
                    return acc;
                  }, {})
                ).sort(([a], [b]) => a.localeCompare(b));

                return (
                  <div className="wgp-section">
                    <p className="wgp-section-title">IETF Working Groups</p>
                    {byArea.map(([acronym, wgs]) => {
                      const collapsed = collapsedAreas[acronym] !== false;
                      const areaName = wgs[0].area_name || acronym;
                      return (
                        <div key={acronym} className="wgp-area-group">
                          <button
                            className="wgp-area-header"
                            onClick={() =>
                              setCollapsedAreas((prev) => ({ ...prev, [acronym]: !collapsed }))
                            }
                            aria-expanded={!collapsed}
                          >
                            <span className="wgp-area-chevron">{collapsed ? '▶' : '▼'}</span>
                            <span className="wgp-area-name">{areaName}</span>
                            <span className="wgp-area-count">
                              ({wgs.length} group{wgs.length !== 1 ? 's' : ''})
                            </span>
                          </button>
                          {!collapsed && (
                            <div className="wgp-area-rows">{wgs.map(renderRow)}</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })()}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
