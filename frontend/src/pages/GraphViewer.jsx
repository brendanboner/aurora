import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Network, DataSet } from 'vis-network/standalone';
import { SearchIcon, RefreshIcon, CloseIcon } from '../components/icons';
import {
  getGraphVisualisationStats,
  getBalancedGraphData,
  getRecentConnectedGraphData,
  getSingleTypeGraphData,
  searchGraphNodes,
  getNodeNeighborhood,
} from '../services/api';
import './GraphViewer.css';

const NODE_META = {
  Resource:     { color: '#4A90D9' },
  Topic:        { color: '#9B59B6' },
  Organization: { color: '#27AE60' },
  Person:       { color: '#E74C3C' },
  Event:        { color: '#F39C12' },
};

// Node types shown in the graph and legend (IngestionBatch / DataSource excluded)
const ALL_TYPES = Object.keys(NODE_META);

// Node types to hide from the stats panel (internal pipeline noise)
const HIDDEN_STAT_TYPES = new Set(['IngestionBatch', 'DataSource']);

const VIS_OPTIONS = {
  physics: {
    enabled: true,
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {
      gravitationalConstant: -50,
      centralGravity: 0.005,
      springLength: 100,
      springConstant: 0.08,
      damping: 0.4,
    },
    stabilization: {
      enabled: true,
      iterations: 200,
      updateInterval: 25,
    },
    maxVelocity: 50,
    minVelocity: 0.1,
  },
  nodes: {
    shape: 'dot',
    scaling: {
      min: 5,
      max: 42,
      label: { enabled: true, min: 9, max: 18, maxVisible: 22, drawThreshold: 7 },
    },
    font: { size: 11, color: '#e8e8f0', face: 'system-ui, sans-serif' },
    borderWidth: 0,
    shadow: false,
  },
  edges: {
    width: 1,
    color: { color: '#5a5b7e', highlight: '#a89df5', hover: '#a89df5', opacity: 1 },
    smooth: { type: 'continuous' },
    arrows: { to: { enabled: false } },
    hoverWidth: 3,
    selectionWidth: 3,
  },
  interaction: {
    hover: true,
    tooltipDelay: 200,
    zoomView: true,
    dragView: true,
    navigationButtons: false,
    keyboard: false,
    selectConnectedEdges: true,
  },
  layout: {
    improvedLayout: false,
  },
};

// vis-network 9+ requires a DOM element for tooltips, not an HTML string
function buildTooltipElement(n) {
  const p = n.properties || {};
  const el = document.createElement('div');
  el.style.cssText = 'padding:8px 10px;max-width:240px;line-height:1.6;font-size:12px;font-family:system-ui,sans-serif;background:#1e1f2e;border:1px solid #3a3b4e;border-radius:6px;color:#e8e8f0';

  const name = document.createElement('div');
  name.style.cssText = 'font-weight:600;font-size:13px;margin-bottom:2px';
  name.textContent = n.name || n.id;
  el.appendChild(name);

  const type = document.createElement('div');
  type.style.cssText = `font-size:10px;color:${NODE_META[n.label]?.color || '#aaa'};font-weight:600;text-transform:uppercase;letter-spacing:0.4px;margin-bottom:4px`;
  type.textContent = n.label;
  el.appendChild(type);

  if (p.importance != null && p.importance > 0) {
    const row = document.createElement('div');
    row.style.cssText = 'font-size:11px;color:#aaa';
    row.textContent = `Importance: ${(p.importance * 100).toFixed(0)}%`;
    el.appendChild(row);
  }
  if (n.degree != null) {
    const row = document.createElement('div');
    row.style.cssText = 'font-size:11px;color:#aaa';
    row.textContent = `Connections: ${n.degree}`;
    el.appendChild(row);
  }

  return el;
}

// Brighter-tinted halo per node type — used for the "glow" effect on
// high-importance nodes so they stand out from the background field.
const GLOW_COLOR = {
  Resource:     '#7fb3e8',
  Topic:        '#c382e8',
  Organization: '#5fd49a',
  Person:       '#f0857b',
  Event:        '#f8c060',
};

// Visual size weight by node type — Resources are individual docs/pages, so
// each one looks "too important" if sized like a Topic/Org. Aggregate types
// get a multiplicative boost so the eye reads the hierarchy correctly.
const SIZE_WEIGHT = {
  Topic:        2.0,   // Topics are conceptual aggregates → biggest
  Organization: 1.6,
  Person:       1.4,
  Event:        1.3,
  Resource:     0.8,   // Single documents — smallest in the family
};

function toVisNode(n) {
  const meta = NODE_META[n.label] || { color: '#6E7079' };
  const importance = n.properties?.importance || 0;
  const degree = n.degree || 0;
  // Glow when importance crosses a threshold OR the node is unusually well
  // connected (degree ≥ 20 — usually a hub topic/org). Two intensities so
  // exceptional nodes pop more than merely-prominent ones.
  const isHighlyImportant = importance >= 0.7;
  const isImportant = importance >= 0.45 || degree >= 20;
  const glowColor = GLOW_COLOR[n.label] || '#a89df5';
  const shadow = isHighlyImportant
    ? { enabled: true, color: glowColor, size: 28, x: 0, y: 0 }
    : isImportant
      ? { enabled: true, color: glowColor, size: 14, x: 0, y: 0 }
      : { enabled: false };

  // Combine type-weight, importance, and degree into a single sizing value.
  // Resources use their `importance` directly (most have it set 0.0-1.0).
  // Non-Resources have importance=0 in the KG, so we fall back to degree-
  // based scaling — a Topic linked to 50 docs is bigger than one linked to 3.
  const typeWeight = SIZE_WEIGHT[n.label] ?? 1.0;
  const degreeScore = Math.min(1.0, degree / 40);  // 40+ degree → max
  const baseScore = importance > 0 ? importance : Math.max(0.2, degreeScore);
  const value = baseScore * typeWeight;

  return {
    id: n.id,
    label: (n.name || String(n.id)).slice(0, 28),
    title: buildTooltipElement(n),
    value,
    color: {
      background: meta.color,
      border: meta.color,
      highlight: { background: '#ffffff', border: meta.color },
      hover: { background: '#ffffff', border: meta.color },
    },
    shadow,
    _label: n.label,
    _important: isImportant || isHighlyImportant,
    _raw: n,
  };
}

function toVisEdge(l) {
  const src = typeof l.source === 'object' ? l.source.id : l.source;
  const tgt = typeof l.target === 'object' ? l.target.id : l.target;
  return {
    id: `${src}__${tgt}__${l.type}`,
    from: src,
    to: tgt,
    title: l.type,
  };
}

const DISPLAY_PROPS = [
  { key: 'importance', label: 'Importance', fmt: v => v > 0 ? `${(v * 100).toFixed(0)}%` : null },
  { key: 'degree',     label: 'Connections', fmt: v => String(v) },
  { key: 'doc_type',   label: 'Doc Type',    fmt: v => v },
  { key: 'event_type', label: 'Event Type',  fmt: v => v },
  { key: 'org_type',   label: 'Org Type',    fmt: v => v },
  { key: 'publish_date', label: 'Published', fmt: v => v ? v.slice(0, 10) : null },
  { key: 'summary',    label: 'Summary',     fmt: v => v?.slice(0, 220) },
  { key: 'url',        label: 'URL',         fmt: null },
  { key: 'email',      label: 'Email',       fmt: null },
];

const GraphViewer = () => {
  const containerRef = useRef(null);
  const networkRef   = useRef(null);
  const nodesDS      = useRef(null);
  const edgesDS      = useRef(null);
  const pulseRef     = useRef(null);  // DOM ref to the target-pulse overlay

  const [stats,           setStats]           = useState(null);
  const [loading,         setLoading]         = useState(true);
  const [loadingMsg,      setLoadingMsg]      = useState('Loading graph…');
  const [error,           setError]           = useState(null);
  const [selectedNode,    setSelectedNode]    = useState(null);
  const [expanding,       setExpanding]       = useState(false);
  const [searchQuery,     setSearchQuery]     = useState('');
  const [hiddenTypes,     setHiddenTypes]     = useState(new Set());
  const [nodeCountByType, setNodeCountByType] = useState({});
  const [focussed,        setFocussed]        = useState(false);
  const [soloType,        setSoloType]        = useState(null);
  // 'recent_connected' is the default — interlinked recent cluster (~400 nodes).
  // 'balanced' is the legacy random-sample view, kept for completeness.
  const [viewMode,        setViewMode]        = useState('recent_connected');
  // Default: no importance filter (threshold=0) so all node types appear
  const [importanceThreshold, setImportanceThreshold] = useState(0);
  const [nodeLimit,       setNodeLimit]       = useState(500);

  // Continuous pulsing-ring animation at the focused node's position.
  // The pulse follows the node — if vis-network re-positions it, pans, or
  // zooms, the overlay tracks it via the `afterDrawing` callback. The CSS
  // keyframes loop, so the user always sees a "target" marker on the
  // current selection until they click away.
  const pulseNodeId = useRef(null);
  const startContinuousPulse = useCallback((nodeId) => {
    if (!networkRef.current || !pulseRef.current || !nodeId) return;
    pulseNodeId.current = nodeId;
    const el = pulseRef.current;
    el.classList.add('gv-pulse-active');
    // Force a position refresh now (afterDrawing will continue updating it)
    try {
      const positions = networkRef.current.getPositions([nodeId]);
      const canvasPos = positions[nodeId];
      if (canvasPos) {
        const domPos = networkRef.current.canvasToDOM(canvasPos);
        el.style.transform = `translate(${domPos.x}px, ${domPos.y}px) translate(-50%, -50%)`;
        el.style.opacity = '1';
      }
    } catch (_) { /* ignore */ }
  }, []);

  const stopContinuousPulse = useCallback(() => {
    pulseNodeId.current = null;
    if (pulseRef.current) {
      pulseRef.current.classList.remove('gv-pulse-active');
      pulseRef.current.style.opacity = '0';
    }
  }, []);

  const buildNetwork = useCallback((graphData) => {
    const counts = {};
    graphData.nodes.forEach(n => { counts[n.label] = (counts[n.label] || 0) + 1; });
    setNodeCountByType(counts);

    nodesDS.current = new DataSet(graphData.nodes.map(toVisNode));
    edgesDS.current = new DataSet(graphData.links.map(toVisEdge));

    if (networkRef.current) {
      networkRef.current.destroy();
      networkRef.current = null;
    }

    const net = new Network(
      containerRef.current,
      { nodes: nodesDS.current, edges: edgesDS.current },
      VIS_OPTIONS
    );

    net.on('stabilizationIterationsDone', () => {
      net.setOptions({ physics: { enabled: false } });
      setLoading(false);
      setLoadingMsg('');
    });

    net.on('click', (params) => {
      if (!params.nodes.length) {
        setSelectedNode(null);
        stopPulseRef.current?.();
        return;
      }
      const nodeId = params.nodes[0];
      const item = nodesDS.current.get(nodeId);
      setSelectedNode(item?._raw ?? null);
      // Auto-expand and focus — defined below, attached via ref to avoid stale closure
      if (expandAndFocusRef.current) expandAndFocusRef.current(nodeId);
    });

    // Keep the pulse overlay glued to the focused node — recomputed on
    // every vis-network render so it tracks pan / zoom / drag in real time.
    net.on('afterDrawing', () => {
      const id = pulseNodeId.current;
      if (!id || !pulseRef.current) return;
      try {
        const positions = net.getPositions([id]);
        const canvasPos = positions[id];
        if (!canvasPos) return;
        const domPos = net.canvasToDOM(canvasPos);
        pulseRef.current.style.transform =
          `translate(${domPos.x}px, ${domPos.y}px) translate(-50%, -50%)`;
      } catch (_) { /* node was removed — pulse fades naturally */ }
    });

    networkRef.current = net;
  }, []);

  // Stable refs so the network event handlers (registered once in
  // buildNetwork) can call the latest versions of the focus/pulse helpers.
  const expandAndFocusRef = useRef(null);
  const stopPulseRef = useRef(null);
  useEffect(() => { stopPulseRef.current = stopContinuousPulse; }, [stopContinuousPulse]);

  // Which ring each node type sits in when expanding. Higher-importance
  // types go outer so they read as the "frame" of the cluster; single
  // documents (Resources) sit inner so they don't dominate visually.
  const RING_BY_TYPE = {
    Resource: 0,     // inner
    Event:    0,
    Person:   1,     // middle
    Organization: 2, // outer
    Topic:    2,     // outer
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const expandAndFocus = useCallback(async (nodeId) => {
    if (!nodeId || !networkRef.current || !nodesDS.current) return;
    setExpanding(true);
    try {
      // Unpin the previously focused node so it can re-flow with the new
      // layout (we only want exactly one pinned anchor at a time).
      const prevFocused = pulseNodeId.current;
      if (prevFocused && prevFocused !== nodeId && nodesDS.current.get(prevFocused)) {
        nodesDS.current.update({ id: prevFocused, fixed: { x: false, y: false } });
      }

      // 1-hop stratified — bounded by type cap so a hub topic doesn't flood
      // the canvas with one node type.
      const hood = await getNodeNeighborhood(nodeId, 1, 80, { stratified: true });

      // Place the focused node at canvas origin and PIN it there so vis-
      // network can't drift the position on hover/redraw (was the source
      // of the "pulse jumps from centre to node and back" bug).
      const focusedNeighborIds = new Set((hood.nodes || []).map(n => n.id));
      focusedNeighborIds.add(nodeId);

      // Anchor focused node at (0, 0); ring coords are relative to it.
      const anchorX = 0;
      const anchorY = 0;

      // Adapt ring radii to canvas size for a fill-the-canvas layout.
      const wrap = containerRef.current;
      const canvasDim = wrap
        ? Math.min(wrap.clientWidth, wrap.clientHeight) || 800
        : 800;
      const ringRadii = [
        canvasDim * 0.30,
        canvasDim * 0.50,
        canvasDim * 0.70,
      ];

      // Group incoming neighbours by ring (skip the focused node itself).
      const incoming = (hood.nodes || []).filter(n => n.id !== nodeId);
      const grouped = { 0: [], 1: [], 2: [] };
      incoming.forEach(n => {
        const r = RING_BY_TYPE[n.label] ?? 1;
        grouped[r].push(n);
      });

      // Build the positions update for every focused-set member: new nodes
      // get added with x/y; existing nodes get repositioned via update().
      const nodeUpdates = [];
      const nodesToAdd = [];
      Object.entries(grouped).forEach(([ringStr, items]) => {
        const ring = parseInt(ringStr, 10);
        const radius = ringRadii[ring];
        const total = items.length;
        if (total === 0) return;
        const angleOffset = (ring * Math.PI) / 7;
        items.forEach((raw, i) => {
          const angle = angleOffset + (i / total) * Math.PI * 2;
          const x = anchorX + Math.cos(angle) * radius;
          const y = anchorY + Math.sin(angle) * radius;
          if (nodesDS.current.get(raw.id)) {
            // Existing node — reposition and ensure visible
            nodeUpdates.push({ id: raw.id, x, y, hidden: false, fixed: { x: false, y: false } });
          } else {
            nodesToAdd.push({ ...toVisNode(raw), x, y });
          }
        });
      });

      const newEdges = (hood.links || [])
        .map(toVisEdge)
        .filter(e => !edgesDS.current.get(e.id));

      // Hide everything that isn't in the focused set so the canvas
      // shows ONLY the clicked node + its 1-hop. Restore via "Fit All".
      const hideUpdates = nodesDS.current
        .get({ filter: n => !focusedNeighborIds.has(n.id) })
        .map(n => ({ id: n.id, hidden: true }));

      // Pin the focused node at the origin so hover/redraw can't drift it.
      const focusedNodePin = { id: nodeId, x: anchorX, y: anchorY, hidden: false, fixed: { x: true, y: true } };

      networkRef.current.setOptions({ physics: { enabled: false } });
      // Apply all in one tick — single render pass, no flicker
      if (nodesToAdd.length) nodesDS.current.add(nodesToAdd);
      if (newEdges.length) edgesDS.current.add(newEdges);
      nodesDS.current.update([focusedNodePin, ...nodeUpdates, ...hideUpdates]);

      // Fit to the focused subgraph — canvas now shows just this cluster.
      networkRef.current.fit({
        nodes: Array.from(focusedNeighborIds),
        animation: { duration: 700, easingFunction: 'easeInOutQuad' },
      });
      startContinuousPulse(nodeId);
      setFocussed(true);
    } catch (_) {
      // Non-critical
    } finally {
      setExpanding(false);
    }
  }, []);

  // Keep ref in sync
  useEffect(() => { expandAndFocusRef.current = expandAndFocus; }, [expandAndFocus]);

  const loadGraph = useCallback(async (limit, threshold, mode = viewMode) => {
    setLoading(true);
    setLoadingMsg('Fetching graph data…');
    setError(null);
    setSelectedNode(null);
    try {
      const fetcher = mode === 'recent_connected'
        ? getRecentConnectedGraphData({
            nodeBudget: limit,
            seedResourceCount: Math.min(120, Math.max(40, Math.floor(limit / 6))),
            // Demo anchors — always include these in the initial view so
            // the trial audience sees themselves + colleagues on landing.
            anchorOrgs:   ['Extreme Networks'],
            anchorPeople: ['Brendan Bonner', 'David Coleman', 'Nabil', 'Hardik'],
          })
        : getBalancedGraphData(limit, threshold);
      const [statsData, graphData] = await Promise.all([
        getGraphVisualisationStats(),
        fetcher,
      ]);
      setStats(statsData);
      setLoadingMsg('Rendering…');
      buildNetwork(graphData);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load graph');
      setLoading(false);
    }
  }, [buildNetwork, viewMode]);

  useEffect(() => {
    loadGraph(nodeLimit, importanceThreshold, viewMode);
    return () => {
      networkRef.current?.destroy();
      networkRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Search — debounced 300ms
  useEffect(() => {
    if (!networkRef.current || !nodesDS.current) return;

    if (!searchQuery.trim()) {
      networkRef.current.unselectAll();
      stopContinuousPulse();
      return;
    }

    const timer = setTimeout(async () => {
      const q = searchQuery.toLowerCase();
      const matches = nodesDS.current
        .get({ filter: n => (n.label || '').toLowerCase().includes(q) })
        .map(n => n.id);

      if (matches.length > 0) {
        networkRef.current.selectNodes(matches);
        networkRef.current.fit({ nodes: matches, animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
        // Single hit → also pull the 2-hop neighbourhood so the user sees
        // the full connected web of the thing they searched for. Pulse the
        // target so the eye lands on the focus node first.
        if (matches.length === 1) {
          const target = matches[0];
          const item = nodesDS.current.get(target);
          setSelectedNode(item?._raw ?? null);
          startContinuousPulse(target);
          if (expandAndFocusRef.current) expandAndFocusRef.current(target);
        }
      } else if (q.length > 2) {
        try {
          const results = await searchGraphNodes(searchQuery, 20);
          if (!results?.length) return;

          // Of the matches, prefer ones already in the graph (cheaper).
          // If none are in the DataSet, take the best match and *fetch* it
          // — this is the path that lets a user search for "Extreme
          // Networks" (or any entity not in the initial recent view) and
          // have its full neighbourhood load in.
          const inGraph = results.filter(r => nodesDS.current.get(r.id));
          const target = inGraph[0] || results[0];
          if (!target) return;

          if (!nodesDS.current.get(target.id)) {
            // The node isn't loaded — fetch its stratified 1-hop, add the
            // target itself first so expandAndFocus can anchor on it, then
            // re-use the normal expand path for radial placement + fit.
            try {
              // Drop the seed node at the canvas centre relative to the
              // current view, then expandAndFocus handles its neighbours.
              const view = networkRef.current.getViewPosition();
              nodesDS.current.add([{ ...toVisNode(target), x: view.x, y: view.y }]);
            } catch (_) {
              // Fallback: just add it without an anchor position
              nodesDS.current.add([toVisNode(target)]);
            }
          }
          networkRef.current.selectNodes([target.id]);
          const item = nodesDS.current.get(target.id);
          setSelectedNode(item?._raw ?? target);
          startContinuousPulse(target.id);
          if (expandAndFocusRef.current) expandAndFocusRef.current(target.id);
        } catch (_) { /* non-critical */ }
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Legend hide/show
  useEffect(() => {
    if (!nodesDS.current) return;
    nodesDS.current.get().forEach(node => {
      nodesDS.current.update({ id: node.id, hidden: hiddenTypes.has(node._label) });
    });
  }, [hiddenTypes]);

  const toggleType = (type) => {
    setHiddenTypes(prev => {
      const next = new Set(prev);
      next.has(type) ? next.delete(type) : next.add(type);
      return next;
    });
  };

  const loadSolo = useCallback(async (type, limit) => {
    setLoading(true);
    setLoadingMsg(`Loading ${type} nodes…`);
    setError(null);
    setSelectedNode(null);
    setFocussed(false);
    try {
      const graphData = await getSingleTypeGraphData(type, limit);
      setLoadingMsg('Rendering…');
      buildNetwork(graphData);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load graph');
      setLoading(false);
    }
  }, [buildNetwork]);

  const handleSoloToggle = (type) => {
    if (soloType === type) {
      // Exit solo — reload current view mode
      setSoloType(null);
      setHiddenTypes(new Set());
      loadGraph(nodeLimit, importanceThreshold, viewMode);
    } else {
      setSoloType(type);
      setHiddenTypes(new Set());
      loadSolo(type, nodeLimit);
    }
  };

  const handleReload = () => {
    setFocussed(false);
    if (soloType) {
      loadSolo(soloType, nodeLimit);
    } else {
      loadGraph(nodeLimit, importanceThreshold, viewMode);
    }
  };

  const handleFitAll = () => {
    setFocussed(false);
    setSelectedNode(null);
    stopContinuousPulse();
    networkRef.current?.unselectAll();
    // Restore any nodes the focus mode hid + unpin the previously-focused node
    if (nodesDS.current) {
      const restore = nodesDS.current
        .get({ filter: n => n.hidden || (n.fixed && (n.fixed.x || n.fixed.y)) })
        .map(n => ({ id: n.id, hidden: false, fixed: { x: false, y: false } }));
      if (restore.length) nodesDS.current.update(restore);
    }
    networkRef.current?.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
  };

  const totalNodes = Object.values(nodeCountByType).reduce((a, b) => a + b, 0);

  // Stats: only show meaningful node types, not internal pipeline types
  const visibleStats = stats
    ? Object.entries(stats.nodes || {}).filter(([type]) => !HIDDEN_STAT_TYPES.has(type))
    : [];

  return (
    <div className="gv-root">
      <aside className="gv-sidebar">
        <div className="gv-sidebar-header">
          <h2 className="gv-sidebar-title">Knowledge Graph</h2>
          <div style={{ display: 'flex', gap: 4 }}>
            {focussed && (
              <button className="gv-reload-btn" onClick={handleFitAll} title="Fit all nodes">
                <span style={{ fontSize: 13 }}>⊞</span>
              </button>
            )}
            <button className="gv-reload-btn" onClick={handleReload} title="Reload graph" disabled={loading}>
              <RefreshIcon size={15} />
            </button>
          </div>
        </div>

        <div className="gv-sidebar-scroll">

          {/* Stats — internal types filtered out */}
          {stats && (
            <div className="gv-stats-section">
              <p className="gv-section-title">Graph Scale</p>
              <div className="gv-stats-grid">
                {visibleStats.map(([type, count]) => (
                  <div className="gv-stat-chip" key={type}>
                    <span className="gv-stat-chip-value">{count.toLocaleString()}</span>
                    <span className="gv-stat-chip-label">
                      <span className="gv-stat-dot" style={{ background: NODE_META[type]?.color || '#6E7079' }} />
                      {type}
                    </span>
                  </div>
                ))}
              </div>
              {stats.relationships != null && (
                <div className="gv-stat-total" style={{ marginTop: 6 }}>
                  <span className="gv-stat-total-label">Total Relationships</span>
                  <span className="gv-stat-total-value">
                    {typeof stats.relationships === 'number'
                      ? stats.relationships.toLocaleString()
                      : Object.values(stats.relationships).reduce((a, b) => a + b, 0).toLocaleString()}
                  </span>
                </div>
              )}
            </div>
          )}

          <div className="gv-divider" />

          {/* Search */}
          <div className="gv-search-section">
            <p className="gv-section-title">Search</p>
            <div className="gv-search-wrap">
              <span className="gv-search-icon"><SearchIcon size={13} /></span>
              <input
                className="gv-search-input"
                placeholder="Find nodes…"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
              />
            </div>
          </div>

          <div className="gv-divider" />

          {/* Legend toggles */}
          <div className="gv-legend-section">
            <p className="gv-section-title">
              {soloType ? `Solo: ${soloType}` : `Showing — ${totalNodes.toLocaleString()} nodes`}
            </p>
            {ALL_TYPES.map(type => {
              const isSolo = soloType === type;
              const isHidden = !soloType && hiddenTypes.has(type);
              return (
                <div
                  key={type}
                  className={`gv-legend-item${isHidden ? ' gv-hidden' : ''}${isSolo ? ' gv-solo' : ''}`}
                >
                  <span
                    className="gv-legend-dot"
                    style={{ background: NODE_META[type].color }}
                    onClick={() => !soloType && toggleType(type)}
                    title="Toggle visibility"
                  />
                  <span
                    className="gv-legend-name"
                    onClick={() => !soloType && toggleType(type)}
                    style={{ cursor: soloType ? 'default' : 'pointer' }}
                  >{type}</span>
                  <span className="gv-legend-count">{(nodeCountByType[type] || 0).toLocaleString()}</span>
                  <button
                    className={`gv-solo-btn${isSolo ? ' active' : ''}`}
                    onClick={() => handleSoloToggle(type)}
                    title={isSolo ? 'Exit solo view' : `Show only ${type} nodes`}
                  >
                    {isSolo ? '✕' : '⊙'}
                  </button>
                </div>
              );
            })}
          </div>

          <div className="gv-divider" />

          {/* Controls */}
          <div className="gv-controls-section">
            <p className="gv-section-title">Controls</p>

            <div className="gv-control-row">
              <span className="gv-control-label">View</span>
              <select
                className="gv-select"
                value={viewMode}
                onChange={e => setViewMode(e.target.value)}
                disabled={!!soloType}
                title={soloType ? 'Exit solo view to change view mode' : 'Switch between recency-clustered and random-balanced sampling'}
              >
                <option value="recent_connected">Recent & connected</option>
                <option value="balanced">Balanced sample</option>
              </select>
            </div>

            <div className="gv-control-row">
              <span className="gv-control-label">Min importance</span>
              <input
                type="range"
                className="gv-slider"
                min="0" max="0.9" step="0.05"
                value={importanceThreshold}
                onChange={e => setImportanceThreshold(parseFloat(e.target.value))}
                disabled={viewMode === 'recent_connected'}
                title={viewMode === 'recent_connected' ? 'Importance is implicit in the recency seed — switch to Balanced to filter' : ''}
              />
              <span className="gv-control-value">
                {importanceThreshold === 0 ? 'off' : `${(importanceThreshold * 100).toFixed(0)}%`}
              </span>
            </div>

            <div className="gv-control-row">
              <span className="gv-control-label">Node limit</span>
              <select
                className="gv-select"
                value={nodeLimit}
                onChange={e => setNodeLimit(parseInt(e.target.value, 10))}
              >
                <option value={300}>300</option>
                <option value={500}>500</option>
                <option value={1000}>1000</option>
                <option value={2000}>2000</option>
              </select>
            </div>

            <button
              className="gv-expand-btn"
              onClick={handleReload}
              disabled={loading}
            >
              Apply & Reload
            </button>
          </div>

          {/* Selected node panel */}
          {selectedNode && (
            <>
              <div className="gv-divider" />
              <div className="gv-node-panel">
                <div className="gv-node-panel-header">
                  <p className="gv-section-title" style={{ margin: 0 }}>Selected Node</p>
                  <button className="gv-close-btn" onClick={() => setSelectedNode(null)}>
                    <CloseIcon size={13} />
                  </button>
                </div>

                <div className="gv-node-name">{selectedNode.name || selectedNode.id}</div>
                <span
                  className="gv-node-type-badge"
                  style={{ background: NODE_META[selectedNode.label]?.color || '#6E7079' }}
                >
                  {selectedNode.label}
                </span>

                {DISPLAY_PROPS.map(({ key, label, fmt }) => {
                  const raw = selectedNode.properties?.[key] ?? selectedNode[key];
                  if (raw == null || raw === '') return null;
                  const val = fmt ? fmt(raw) : raw;
                  if (val == null || val === '') return null;
                  return (
                    <div className="gv-prop-row" key={key}>
                      <div className="gv-prop-label">{label}</div>
                      <div className="gv-prop-value">
                        {key === 'url' ? (
                          <a href={raw} target="_blank" rel="noreferrer">{raw.slice(0, 60)}{raw.length > 60 ? '…' : ''}</a>
                        ) : key === 'email' ? (
                          <a href={`mailto:${raw}`}>{raw}</a>
                        ) : val}
                      </div>
                    </div>
                  );
                })}

                {expanding && (
                  <div style={{ fontSize: 11, color: 'var(--muted-foreground)', marginTop: 8 }}>
                    Loading connections…
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </aside>

      <div className="gv-canvas-wrap">
        <div id="gv-network-container" ref={containerRef} />

        {/* Target-pulse overlay — positioned via JS at the focused node's
            screen coords. Hidden by default; CSS keyframes fade & expand
            three concentric rings when .gv-pulse-active is toggled on. */}
        <div className="gv-target-pulse" ref={pulseRef} aria-hidden="true">
          <span className="gv-pulse-ring gv-pulse-ring-1" />
          <span className="gv-pulse-ring gv-pulse-ring-2" />
          <span className="gv-pulse-ring gv-pulse-ring-3" />
        </div>

        <div className={`gv-overlay${loading ? '' : ' gv-hidden'}`}>
          <div className="gv-spinner" />
          <span className="gv-overlay-text">{loadingMsg}</span>
        </div>

        {error && <div className="gv-error-banner">{error}</div>}

        {!loading && (
          <div className="gv-canvas-hint">
            Scroll to zoom · Drag to pan · Click node for details
          </div>
        )}
      </div>
    </div>
  );
};

export default GraphViewer;
