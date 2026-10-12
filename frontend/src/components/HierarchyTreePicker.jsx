import React, { useState, useMemo } from 'react';
import './HierarchyTreePicker.css';

/**
 * HierarchyTreePicker
 *
 * Generic collapsible tree picker used by PreferencesPanel tabs.
 *
 * Props:
 *   nodes          [{id, name, parentId, description, isMemberOnly}]
 *   idField        string — property name for node id (default 'id')
 *   parentField    string — property name for parent id (default 'parentId')
 *   nameField      string — property name for display name (default 'name')
 *   joined         Set<string> — ids the user has joined
 *   ignored        Set<string> — ids the user has ignored (optional)
 *   preferred      Set<string> — ids the user prefers (weighted boost, optional)
 *   onJoin         (id) => void
 *   onLeave        (id) => void
 *   onIgnore       (id) => void — optional
 *   onUnignore     (id) => void — optional
 *   onPrefer       (id) => void — optional
 *   onUnprefer     (id) => void — optional
 *   mode           'join-ignore' | 'prefer' (default 'join-ignore')
 *   searchQuery    string — filter nodes by name
 *   saving         Set<string> — ids currently saving
 *   errors         Set<string> — ids with save errors
 */
export default function HierarchyTreePicker({
  nodes = [],
  idField = 'id',
  parentField = 'parentId',
  nameField = 'name',
  joined = new Set(),
  ignored = new Set(),
  preferred = new Set(),
  onJoin,
  onLeave,
  onIgnore,
  onUnignore,
  onPrefer,
  onUnprefer,
  mode = 'join-ignore',
  searchQuery = '',
  saving = new Set(),
  errors = new Set(),
}) {
  const [collapsed, setCollapsed] = useState({});

  // Build parent→children map
  const childMap = useMemo(() => {
    const map = {};
    for (const node of nodes) {
      const pid = node[parentField];
      if (pid) {
        if (!map[pid]) map[pid] = [];
        map[pid].push(node);
      }
    }
    return map;
  }, [nodes, parentField]);

  // Root nodes (no parent, or parent not in the node set)
  const nodeIds = useMemo(() => new Set(nodes.map((n) => n[idField])), [nodes, idField]);
  const roots = useMemo(
    () => nodes.filter((n) => !n[parentField] || !nodeIds.has(n[parentField])),
    [nodes, parentField, nodeIds]
  );

  // Text filter: a node is visible if its name matches OR any descendant matches
  function nodeMatchesSearch(node) {
    const q = searchQuery.toLowerCase();
    if (!q) return true;
    if ((node[nameField] || '').toLowerCase().includes(q)) return true;
    for (const child of childMap[node[idField]] || []) {
      if (nodeMatchesSearch(child)) return true;
    }
    return false;
  }

  function toggleCollapse(id) {
    setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function renderNode(node, depth = 0) {
    if (!nodeMatchesSearch(node)) return null;
    const id = node[idField];
    const name = node[nameField] || id;
    const children = (childMap[id] || []).filter(nodeMatchesSearch);
    const hasChildren = children.length > 0;
    const isCollapsed = collapsed[id] !== false && depth === 0; // default: roots expanded
    const isJoined = joined.has(id);
    const isIgnored = ignored.has(id);
    const isPref = preferred.has(id);
    const isSaving = saving.has(id);
    const isError = errors.has(id);
    const isMemberOnly = node.isMemberOnly;

    return (
      <div key={id} className={`htp-node depth-${depth}`}>
        <div className="htp-row">
          {/* Expand/collapse chevron */}
          <button
            className="htp-chevron"
            onClick={() => toggleCollapse(id)}
            aria-label={isCollapsed ? 'Expand' : 'Collapse'}
            style={{ visibility: hasChildren ? 'visible' : 'hidden' }}
          >
            {isCollapsed ? '▶' : '▼'}
          </button>

          <div className="htp-info">
            <span className="htp-name">{name}</span>
            {isMemberOnly && <span className="htp-badge member-only">Member-only</span>}
            {node.description && (
              <span className="htp-desc" title={node.description}>
                {node.description.slice(0, 80)}{node.description.length > 80 ? '…' : ''}
              </span>
            )}
          </div>

          <div className="htp-actions">
            {mode === 'join-ignore' ? (
              <>
                <button
                  className={`htp-btn${isJoined ? ' active-join' : ''}`}
                  disabled={isSaving || isIgnored}
                  title={isIgnored ? 'Remove Ignore to enable Join' : isJoined ? 'Leave' : 'Join (boost results)'}
                  onClick={() => isJoined ? onLeave?.(id) : onJoin?.(id)}
                >
                  {isJoined ? 'Leave' : 'Join'}
                </button>
                {onIgnore && (
                  <button
                    className={`htp-btn${isIgnored ? ' active-ignore' : ''}`}
                    disabled={isSaving}
                    title={isIgnored ? 'Stop ignoring' : 'Ignore (exclude from results)'}
                    onClick={() => isIgnored ? onUnignore?.(id) : onIgnore?.(id)}
                  >
                    {isIgnored ? 'Unignore' : 'Ignore'}
                  </button>
                )}
              </>
            ) : (
              <button
                className={`htp-btn${isPref ? ' active-prefer' : ''}`}
                disabled={isSaving}
                title={isPref ? 'Remove preference' : 'Prefer (boost results)'}
                onClick={() => isPref ? onUnprefer?.(id) : onPrefer?.(id)}
              >
                {isPref ? 'Unprefer' : 'Prefer'}
              </button>
            )}

            {isSaving && <div className="htp-spinner" aria-label="Saving…" />}
            {isError && <span className="htp-error" title="Save failed">⚠️</span>}
          </div>
        </div>

        {hasChildren && !isCollapsed && (
          <div className="htp-children">
            {children.map((child) => renderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  }

  if (roots.length === 0) {
    return <div className="htp-empty">No items available.</div>;
  }

  return (
    <div className="htp-tree">
      {roots.map((root) => renderNode(root, 0))}
    </div>
  );
}
