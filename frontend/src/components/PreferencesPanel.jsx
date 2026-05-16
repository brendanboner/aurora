import React, { useEffect, useState, useCallback } from 'react';
import HierarchyTreePicker from './HierarchyTreePicker';
import {
  getDatasourceTree,
  getTopicTree,
  getOrganisations,
  getUserSourceMemberships,
  upsertSourceMembership,
  deleteSourceMembership,
  getUserSourcePreferences,
  upsertSourcePreference,
  deleteSourcePreference,
  getUserPreferences,
  updateUserPreferences,
} from '../services/api';
import './PreferencesPanel.css';

const TABS = [
  { id: 'group',  label: 'Groups',  desc: 'Join or ignore WBA, WFA, IETF and other workgroups' },
  { id: 'source', label: 'Sources', desc: 'Prefer or ignore public data sources' },
];

/**
 * PreferencesPanel
 *
 * Unified preferences UI with four tabs: Groups, Sources, Technology, Companies.
 *
 * Props:
 *   userId         string
 *   defaultTab     'group' | 'source' | 'technology' | 'company'
 *   onClose        () => void — optional (used when rendered inside a modal)
 */
export default function PreferencesPanel({ userId, defaultTab = 'group', onClose }) {
  const [activeTab, setActiveTab] = useState(defaultTab);
  const [search, setSearch] = useState('');

  // Data
  const [datasourceTree, setDatasourceTree] = useState([]);
  const [topicTree, setTopicTree]           = useState([]);
  const [organisations, setOrganisations]   = useState([]);
  const [memberships, setMemberships]       = useState({ joined: [], ignored: [] });
  const [sourcePrefs, setSourcePrefs]       = useState([]); // [{datasource_id, weight}]
  const [userPrefs, setUserPrefs]           = useState({});

  // Per-row save state
  const [saving, setSaving] = useState({});
  const [errors, setErrors] = useState({});

  const [loading, setLoading] = useState(true);

  // ── fetch all data on mount ──────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    // allSettled so a failed auth/user call doesn't blank the whole panel
    Promise.allSettled([
      getDatasourceTree(),
      getTopicTree(),
      getOrganisations(500, 0),
      getUserSourceMemberships(userId),
      getUserSourcePreferences(userId),
      getUserPreferences(userId),
    ])
      .then(([tree, topics, orgs, mems, sprefs, prefs]) => {
        if (cancelled) return;
        setDatasourceTree(tree.status === 'fulfilled' ? (tree.value || []) : []);
        setTopicTree(topics.status === 'fulfilled' ? (topics.value || []) : []);
        const rawOrgs = orgs.status === 'fulfilled' ? orgs.value : null;
        const orgVal = Array.isArray(rawOrgs) ? rawOrgs : (Array.isArray(rawOrgs?.items) ? rawOrgs.items : []);
        setOrganisations(orgVal.map((o) => ({
          id: o.org_id || o.id,
          name: o.name,
          parentId: null,
        })));
        setMemberships(mems.status === 'fulfilled' ? (mems.value || { joined: [], ignored: [] }) : { joined: [], ignored: [] });
        setSourcePrefs(sprefs.status === 'fulfilled' ? (sprefs.value || []) : []);
        setUserPrefs(prefs.status === 'fulfilled' ? (prefs.value || {}) : {});
        if (tree.status === 'rejected') console.warn('DatasourceTree failed:', tree.reason);
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [userId]);

  // ── helpers ──────────────────────────────────────────────────────────────
  const setSavingFor = (id, state) => setSaving((p) => ({ ...p, [id]: state }));
  const setErrorFor  = (id, state) => setErrors((p) => ({ ...p, [id]: state }));

  // ── group tab (join/ignore memberships) ──────────────────────────────────
  const handleMembershipToggle = useCallback(async (id, action) => {
    setSavingFor(id, true);
    try {
      if (action === 'join') {
        await upsertSourceMembership(userId, id, 'joined');
        setMemberships((p) => ({
          joined:  [...p.joined.filter((x) => x !== id), id],
          ignored: p.ignored.filter((x) => x !== id),
        }));
      } else if (action === 'leave') {
        await deleteSourceMembership(userId, id);
        setMemberships((p) => ({ ...p, joined: p.joined.filter((x) => x !== id) }));
      } else if (action === 'ignore') {
        await upsertSourceMembership(userId, id, 'ignored');
        setMemberships((p) => ({
          joined:  p.joined.filter((x) => x !== id),
          ignored: [...p.ignored.filter((x) => x !== id), id],
        }));
      } else if (action === 'unignore') {
        await deleteSourceMembership(userId, id);
        setMemberships((p) => ({ ...p, ignored: p.ignored.filter((x) => x !== id) }));
      }
      setSavingFor(id, false);
    } catch {
      setErrorFor(id, true);
      setSavingFor(id, false);
      setTimeout(() => setErrorFor(id, false), 3000);
    }
  }, [userId]);

  // ── source tab (weighted preferences) ────────────────────────────────────
  const handleSourcePref = useCallback(async (id, action) => {
    setSavingFor(id, true);
    try {
      if (action === 'prefer') {
        await upsertSourcePreference(userId, id, 1.0);
        setSourcePrefs((p) => [...p.filter((s) => s.datasource_id !== id), { datasource_id: id, weight: 1.0 }]);
      } else {
        await deleteSourcePreference(userId, id);
        setSourcePrefs((p) => p.filter((s) => s.datasource_id !== id));
      }
      setSavingFor(id, false);
    } catch {
      setErrorFor(id, true);
      setSavingFor(id, false);
      setTimeout(() => setErrorFor(id, false), 3000);
    }
  }, [userId]);

  // ── technology tab (user_preferences.topics array) ───────────────────────
  const handleTopicPref = useCallback(async (topicId, action) => {
    setSavingFor(topicId, true);
    try {
      const current = userPrefs.topics || [];
      const updated = action === 'prefer'
        ? [...new Set([...current, topicId])]
        : current.filter((t) => t !== topicId);
      await updateUserPreferences(userId, { ...userPrefs, topics: updated });
      setUserPrefs((p) => ({ ...p, topics: updated }));
      setSavingFor(topicId, false);
    } catch {
      setErrorFor(topicId, true);
      setSavingFor(topicId, false);
      setTimeout(() => setErrorFor(topicId, false), 3000);
    }
  }, [userId, userPrefs]);

  // ── company tab (user_preferences.organisations array) ───────────────────
  const handleOrgPref = useCallback(async (orgId, action) => {
    setSavingFor(orgId, true);
    try {
      const current = userPrefs.organisations || [];
      const updated = action === 'prefer'
        ? [...new Set([...current, orgId])]
        : current.filter((o) => o !== orgId);
      await updateUserPreferences(userId, { ...userPrefs, organisations: updated });
      setUserPrefs((p) => ({ ...p, organisations: updated }));
      setSavingFor(orgId, false);
    } catch {
      setErrorFor(orgId, true);
      setSavingFor(orgId, false);
      setTimeout(() => setErrorFor(orgId, false), 3000);
    }
  }, [userId, userPrefs]);

  // ── derived sets ─────────────────────────────────────────────────────────
  const joinedSet   = new Set(memberships.joined);
  const ignoredSet  = new Set(memberships.ignored);
  const sourcePrefSet = new Set(sourcePrefs.map((s) => s.datasource_id));
  const topicPrefSet  = new Set(userPrefs.topics || []);
  const orgPrefSet    = new Set(userPrefs.organisations || []);
  const savingSet  = new Set(Object.keys(saving).filter((k) => saving[k]));
  const errorsSet  = new Set(Object.keys(errors).filter((k) => errors[k]));

  // ── datasource tree nodes ─────────────────────────────────────────────────
  const groupNodes = datasourceTree
    .filter((d) => d.category === 'workgroup')
    .map((d) => ({
      id:           d.datasource_id,
      name:         d.name,
      parentId:     d.parent_datasource_id || null,
      description:  d.description,
      isMemberOnly: d.source_type === 'authenticated_portal',
    }));

  const sourceNodes = datasourceTree
    .filter((d) => d.category === 'public')
    .map((d) => ({
      id:           d.datasource_id,
      name:         d.name,
      parentId:     d.parent_datasource_id || null,
      description:  d.description,
      isMemberOnly: false,
    }));

  const topicNodes = topicTree.map((t) => ({
    id:       t.topic_id,
    name:     t.name,
    parentId: t.parent_topic_id || null,
  }));

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="pp-container">
      {/* Optional header when used as modal */}
      {onClose && (
        <div className="pp-modal-header">
          <h2 className="pp-modal-title">Preferences</h2>
          <button className="pp-close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
      )}

      {/* Tab bar */}
      <div className="pp-tabs" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`pp-tab${activeTab === tab.id ? ' active' : ''}`}
            onClick={() => { setActiveTab(tab.id); setSearch(''); }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="pp-search-row">
        <input
          className="pp-search"
          type="search"
          placeholder={`Search ${TABS.find((t) => t.id === activeTab)?.label.toLowerCase()}…`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search"
        />
      </div>

      {/* Content */}
      <div className="pp-body" role="tabpanel">
        {loading ? (
          <div className="pp-loading"><div className="pp-spinner" />Loading…</div>
        ) : (
          <>
            {activeTab === 'group' && (
              <HierarchyTreePicker
                nodes={groupNodes}
                joined={joinedSet}
                ignored={ignoredSet}
                onJoin={(id) => handleMembershipToggle(id, 'join')}
                onLeave={(id) => handleMembershipToggle(id, 'leave')}
                onIgnore={(id) => handleMembershipToggle(id, 'ignore')}
                onUnignore={(id) => handleMembershipToggle(id, 'unignore')}
                mode="join-ignore"
                searchQuery={search}
                saving={savingSet}
                errors={errorsSet}
              />
            )}
            {activeTab === 'source' && (
              <HierarchyTreePicker
                nodes={sourceNodes}
                joined={joinedSet}
                ignored={ignoredSet}
                preferred={sourcePrefSet}
                onJoin={(id) => handleMembershipToggle(id, 'join')}
                onLeave={(id) => handleMembershipToggle(id, 'leave')}
                onIgnore={(id) => handleMembershipToggle(id, 'ignore')}
                onUnignore={(id) => handleMembershipToggle(id, 'unignore')}
                onPrefer={(id) => handleSourcePref(id, 'prefer')}
                onUnprefer={(id) => handleSourcePref(id, 'unprefer')}
                mode="join-ignore"
                searchQuery={search}
                saving={savingSet}
                errors={errorsSet}
              />
            )}
            {activeTab === 'technology' && (
              <HierarchyTreePicker
                nodes={topicNodes}
                preferred={topicPrefSet}
                onPrefer={(id) => handleTopicPref(id, 'prefer')}
                onUnprefer={(id) => handleTopicPref(id, 'unprefer')}
                mode="prefer"
                searchQuery={search}
                saving={savingSet}
                errors={errorsSet}
              />
            )}
            {activeTab === 'company' && (
              <HierarchyTreePicker
                nodes={organisations}
                preferred={orgPrefSet}
                onPrefer={(id) => handleOrgPref(id, 'prefer')}
                onUnprefer={(id) => handleOrgPref(id, 'unprefer')}
                mode="prefer"
                searchQuery={search}
                saving={savingSet}
                errors={errorsSet}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
