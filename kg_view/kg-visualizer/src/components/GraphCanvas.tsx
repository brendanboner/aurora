import React, { useCallback, useEffect, useRef } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import type { GraphNode, GraphLink, GraphData } from '../types/graph';
import { gsap } from 'gsap';

interface GraphCanvasProps {
  data: GraphData;
  selectedNodes: Set<number | string>;
  onNodeClick: (node: GraphNode) => void;
  onNodeDoubleClick?: (node: GraphNode) => void; // Optional double-click handler
  onNodeHover: (node: GraphNode | null) => void;
  highlightNodes: Set<number | string>;
  highlightLinks: Set<string>;
  directLinks: Set<string>; // Direct links between entity nodes for special animation
  nodeDistances: Map<number | string, number>; // Distance from selected entities
  nodeConnectionCount: Map<number | string, number>; // How many entities connect through this node
  hiddenNodeTypes: Set<string>;
  nodeSize?: number; // 0 to 100% size adjustment
  linkSize?: number; // 0 to 100% size adjustment
}

// Node color mapping by type
const NODE_COLORS: Record<string, string> = {
  Resource: '#4A90E2',      // Blue
  Topic: '#9B59B6',         // Purple
  Organization: '#2ECC71',  // Green
  Event: '#E67E22',         // Orange
  Person: '#E74C3C',        // Red
  DataSource: '#95A5A6',    // Gray
  Default: '#34495E',       // Dark gray
};

// ==============================================================================
// VISUAL CONSTANTS - Adjust these to tune the graph appearance
// ==============================================================================

// Node Size Multipliers (base size = 3)
const NODE_SIZE = {
  BASE: 3,
  ENTITY: 2.5,           // Entity nodes (distance 0) - largest and prominent (increased)
  HOP_1_MULTI: 1.8,      // 1-hop with multiple connections (increased)
  HOP_1_SINGLE: 1.2,     // 1-hop with single connection (increased)
  HOP_2: 1.0,            // 2-hop (increased)
  HOP_3_PLUS: 0.85,      // 3+ hops (increased)
  SELECTED: 2.0,         // Selected but not highlighted
  IMPORTANCE_MIN: 0.4,   // Minimum importance factor (increased for more visibility)
  IMPORTANCE_MAX: 1.2,   // Maximum importance boost (increased for more dramatic sizing)
};

// Node Color Brightness (for highlighting)
const NODE_BRIGHTNESS = {
  ENTITY: 1.0,           // Entity nodes - full brightness
  HOP_1: 0.75,           // 1-hop - 75% brightness
  HOP_2: 0.5,            // 2-hop - 50% brightness
  HOP_3_PLUS: 0.4,       // 3+ hops - 40% brightness
  MULTI_CONNECTION_BOOST: 0.25,  // Bonus for nodes with multiple connections
  DIMMED: 0.2,           // Non-highlighted nodes when filtering
};

// Node Glow Effects
const NODE_GLOW = {
  SIZE_MULTIPLIER: 1.1,  // Glow sphere size relative to node
  OPACITY_BASE: 0.1,     // Base glow opacity for highlighted nodes
  OPACITY_MAX: 0.4,      // Max glow opacity for entity pulsing
  OPACITY_NORMAL: 0.2,   // Normal glow opacity for non-entity highlighted nodes
  PULSE_DURATION: 2.0,   // Entity pulse animation duration (seconds)
  PULSE_DURATION_NORMAL: 1.0,  // Normal glow pulse duration (seconds)
  ENTITY_OPACITY_MIN: 0.85,    // Min opacity for entity node pulse
};

// Link Visual Properties
const LINK_STYLE = {
  BASE_WIDTH: 0.8,           // Increased base width for better visibility
  WIDTH_DIRECT: 2.5,         // Direct entity-to-entity links - much thicker
  WIDTH_HIGHLIGHTED: 2.0,    // Highlighted links - thicker
  OPACITY_DIRECT: 1.0,       // Direct entity-to-entity links
  OPACITY_HOP_0: 1.0,        // Entity links
  OPACITY_HOP_1: 0.75,       // 1-hop links
  OPACITY_HOP_2: 0.60,       // 2-hop links
  OPACITY_HOP_3_PLUS: 0.65,  // 3+ hop links
  OPACITY_DIMMED: 0.10,      // Non-highlighted when filtering
  OPACITY_NORMAL: 0.4,       // Normal state
};

// Link Colors
const LINK_COLORS = {
  DIRECT: '#00D9FF',     // Bright cyan for direct entity-to-entity connections
  HIGHLIGHTED: '#cada92ff', // Bright orange for highlighted connections
  DIMMED: '#5a6a7bff',     // Dimmed when filtering
  NORMAL: '#9babacff',     // Normal gray
};

// Link Particles (synapse effect)
const LINK_PARTICLES = {
  COUNT_DIRECT: 8,       // Particle count for direct links
  COUNT_HIGHLIGHTED: 4,  // Particle count for highlighted links
  COUNT_NORMAL: 0,       // No particles for normal links
  WIDTH_DIRECT: 3,       // Particle size for direct links
  WIDTH_NORMAL: 2,       // Particle size for highlighted links
  SPEED_DIRECT: 0.01,    // Particle speed for direct links
  SPEED_NORMAL: 0.006,   // Particle speed for highlighted links
};

// Camera
const CAMERA = {
  INITIAL_DISTANCE: 1000,
  MIN_DISTANCE: 300,
  MAX_DISTANCE: 800,
  TRANSITION_DURATION: 1000, // milliseconds
};

const GraphCanvas = React.forwardRef<any, GraphCanvasProps>((
  {
    data,
    selectedNodes,
    onNodeClick,
    onNodeDoubleClick,
    onNodeHover,
    highlightNodes,
    highlightLinks,
    directLinks,
    nodeDistances,
    nodeConnectionCount,
    hiddenNodeTypes,
    nodeSize = 100,
    linkSize = 100,
  },
  forwardedRef
) => {
  const fgRef = useRef<any>(null);
  
  // Expose the force graph ref to parent
  React.useImperativeHandle(forwardedRef, () => fgRef.current);
  // hoveredNode state removed - using parent's onNodeHover callback instead

  // Filter out hidden node types
  const filteredData = {
    nodes: data.nodes.filter(node => !hiddenNodeTypes.has(node.label)),
    links: data.links.filter(link => {
      const sourceNode = data.nodes.find(n => n.id === (typeof link.source === 'object' ? link.source.id : link.source));
      const targetNode = data.nodes.find(n => n.id === (typeof link.target === 'object' ? link.target.id : link.target));
      return sourceNode && targetNode && 
             !hiddenNodeTypes.has(sourceNode.label) && 
             !hiddenNodeTypes.has(targetNode.label);
    })
  };

  // Node visual properties
  const getNodeColor = useCallback((node: GraphNode) => {
    const baseColor = NODE_COLORS[node.label] || NODE_COLORS.Default;
    
    // If node is highlighted, apply distance-based brightness
    if (highlightNodes.has(node.id)) {
      const distance = nodeDistances.get(node.id) || 0;
      const connections = nodeConnectionCount.get(node.id) || 1;
      
      // Parse hex color to RGB
      const hex = baseColor.replace('#', '');
      let r = parseInt(hex.substring(0, 2), 16);
      let g = parseInt(hex.substring(2, 4), 16);
      let b = parseInt(hex.substring(4, 6), 16);
      
      // Calculate brightness based on distance
      let brightnessFactor = NODE_BRIGHTNESS.HOP_3_PLUS;
      if (distance === 0) {
        brightnessFactor = NODE_BRIGHTNESS.ENTITY;
      } else if (distance === 1) {
        brightnessFactor = NODE_BRIGHTNESS.HOP_1;
      } else if (distance === 2) {
        brightnessFactor = NODE_BRIGHTNESS.HOP_2;
      }
      
      // Connection boost: multiple connections = brighter
      if (connections > 1) {
        brightnessFactor = Math.min(1.0, brightnessFactor + NODE_BRIGHTNESS.MULTI_CONNECTION_BOOST);
      }
      
      r = Math.round(r * brightnessFactor);
      g = Math.round(g * brightnessFactor);
      b = Math.round(b * brightnessFactor);
      
      return `rgb(${r}, ${g}, ${b})`;
    }
    
    // Selected nodes stay full brightness
    if (selectedNodes.has(node.id)) {
      return baseColor;
    }
    
    // Dim non-highlighted nodes when something is highlighted
    if (highlightNodes.size > 0) {
      const hex = baseColor.replace('#', '');
      let r = Math.round(parseInt(hex.substring(0, 2), 16) * NODE_BRIGHTNESS.DIMMED);
      let g = Math.round(parseInt(hex.substring(2, 4), 16) * NODE_BRIGHTNESS.DIMMED);
      let b = Math.round(parseInt(hex.substring(4, 6), 16) * NODE_BRIGHTNESS.DIMMED);
      
      return `rgb(${r}, ${g}, ${b})`;
    }
    
    return baseColor;
  }, [selectedNodes, highlightNodes, nodeDistances, nodeConnectionCount]);

  const getNodeSize = useCallback((node: GraphNode) => {
    const importance = node.properties?.importance || 0.5;
    const distance = nodeDistances.get(node.id);
    const connections = nodeConnectionCount.get(node.id) || 0;
    const sizeMultiplier = nodeSize / 100; // Convert 0-100% to 0-1 multiplier
    
    // Importance factor: scale between MIN and MAX based on actual importance
    const importanceFactor = NODE_SIZE.IMPORTANCE_MIN + (importance * (NODE_SIZE.IMPORTANCE_MAX - NODE_SIZE.IMPORTANCE_MIN));
    
    // If node is an entity (distance 0) - make it the largest
    if (distance === 0) {
      return NODE_SIZE.BASE * NODE_SIZE.ENTITY * importanceFactor * sizeMultiplier;
    }
    
    // If node is highlighted (connected to entities)
    if (highlightNodes.has(node.id) && distance !== undefined) {
      let distanceMultiplier = NODE_SIZE.HOP_3_PLUS;
      
      if (distance === 1) {
        // 1-hop: size based on number of connections and importance
        distanceMultiplier = connections > 1 ? NODE_SIZE.HOP_1_MULTI : NODE_SIZE.HOP_1_SINGLE;
      } else if (distance === 2) {
        distanceMultiplier = NODE_SIZE.HOP_2;
      }
      
      // Apply both distance multiplier and importance
      return NODE_SIZE.BASE * distanceMultiplier * importanceFactor * sizeMultiplier;
    }
    
    // Selected but not highlighted - slightly larger than default
    if (selectedNodes.has(node.id)) {
      return NODE_SIZE.BASE * NODE_SIZE.SELECTED * importanceFactor * sizeMultiplier;
    }
    
    // Default size - small
    return NODE_SIZE.BASE * 0.8 * importanceFactor * sizeMultiplier;
  }, [selectedNodes, highlightNodes, nodeDistances, nodeConnectionCount, nodeSize]);

  // Custom node object with glow effect
  const nodeThreeObject = useCallback((node: GraphNode) => {
    const isHighlighted = selectedNodes.has(node.id) || highlightNodes.has(node.id);
    const isEntity = nodeDistances.get(node.id) === 0; // Entity nodes have distance 0
    const color = getNodeColor(node);
    const size = getNodeSize(node); // This already includes importance and size multipliers
    
    const geometry = new THREE.SphereGeometry(size, 16, 16);
    const material = new THREE.MeshLambertMaterial({
      color: color,
      transparent: true,
      opacity: isHighlighted ? 1.0 : 0.8,
    });
    
    const mesh = new THREE.Mesh(geometry, material);
    
    // Add glow ONLY for entity nodes (selected/searched topics)
    // Glow size MUST scale proportionally with the computed node size
    // This ensures glow matches both importance-based and distance-based sizing
    if (isEntity) {
      const glowSize = size * NODE_GLOW.SIZE_MULTIPLIER; // Proportional to actual node size
      const glowGeometry = new THREE.SphereGeometry(glowSize, 16, 16);
      const glowMaterial = new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: NODE_GLOW.OPACITY_BASE,
      });
      const glow = new THREE.Mesh(glowGeometry, glowMaterial);
      mesh.add(glow);
      
      // Pulsing animation for entity nodes
      gsap.to(glowMaterial, {
        opacity: NODE_GLOW.OPACITY_MAX,
        duration: NODE_GLOW.PULSE_DURATION,
        repeat: -1,
        yoyo: true,
        ease: 'sine.inOut',
      });
      
      // Also pulse the main material slightly for extra emphasis
      gsap.to(material, {
        opacity: NODE_GLOW.ENTITY_OPACITY_MIN,
        duration: NODE_GLOW.PULSE_DURATION,
        repeat: -1,
        yoyo: true,
        ease: 'sine.inOut',
      });
    }
    
    return mesh;
  }, [selectedNodes, highlightNodes, nodeDistances, getNodeColor, getNodeSize]);

  // Link visual properties
  const getLinkColor = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    
    // Direct entity-to-entity links get bright cyan - always bright
    if (directLinks.has(linkId)) {
      return LINK_COLORS.DIRECT;
    }
    
    // If links are highlighted, use consistent bright color
    // Brightness is controlled by opacity in getLinkOpacity, not color darkness
    if (highlightLinks.has(linkId)) {
      return LINK_COLORS.HIGHLIGHTED;
    }
    
    if (highlightLinks.size > 0) {
      return LINK_COLORS.DIMMED;
    }
    
    return LINK_COLORS.NORMAL;
  }, [highlightLinks, directLinks]);

  const getLinkWidth = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    const confidence = link.properties?.confidence || 0.3;
    const importance = link.properties?.importance || 0.3;
    const sizeMultiplier = linkSize / 100; // Convert 0-100% to 0-1 multiplier
    
    // Weight ranges from 0.2 to 1.0 for more dramatic variation
    const weight = Math.max(0.2, (confidence + importance) / 2);
    
    // Direct entity-to-entity links are thickest
    if (directLinks.has(linkId)) {
      return LINK_STYLE.BASE_WIDTH * LINK_STYLE.WIDTH_DIRECT * weight * sizeMultiplier;
    }
    
    // Highlighted links scale with importance
    if (highlightLinks.has(linkId)) {
      return LINK_STYLE.BASE_WIDTH * LINK_STYLE.WIDTH_HIGHLIGHTED * weight * sizeMultiplier;
    }
    
    // Normal links are thinner and scale with importance
    return LINK_STYLE.BASE_WIDTH * 0.8 * weight * sizeMultiplier;
  }, [highlightLinks, directLinks, linkSize]);

  const getLinkOpacity = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    const sizeMultiplier = linkSize / 100; // Convert 0-100% to 0-1 multiplier
    
    let baseOpacity = LINK_STYLE.OPACITY_NORMAL;
    
    // Direct entity-to-entity links are most visible
    if (directLinks.has(linkId)) {
      baseOpacity = LINK_STYLE.OPACITY_DIRECT;
    }
    // Highlighted links vary opacity by distance for true brightness effect
    else if (highlightLinks.has(linkId)) {
      const targetId = typeof link.target === 'object' ? link.target.id : link.target;
      const distance = nodeDistances.get(targetId) || 0;
      
      // Distance-based opacity - higher values for better visibility
      if (distance === 0) baseOpacity = LINK_STYLE.OPACITY_HOP_0;
      else if (distance === 1) baseOpacity = LINK_STYLE.OPACITY_HOP_1;
      else if (distance === 2) baseOpacity = LINK_STYLE.OPACITY_HOP_2;
      else baseOpacity = LINK_STYLE.OPACITY_HOP_3_PLUS;
    }
    else if (highlightLinks.size > 0) {
      baseOpacity = LINK_STYLE.OPACITY_DIMMED;
    }
    
    // Apply size multiplier to opacity
    const adjustedOpacity = Math.max(0, Math.min(1, baseOpacity * sizeMultiplier));
    
    return adjustedOpacity;
  }, [highlightLinks, directLinks, nodeDistances, linkSize]);

  // Handle node click
  const handleNodeClick = useCallback((node: GraphNode) => {
    onNodeClick(node);
    
    // Smooth camera transition to node - position camera at a reasonable distance
    if (fgRef.current && node.x !== undefined && node.y !== undefined && node.z !== undefined) {
      // Get current camera position
      const camera = fgRef.current.camera();
      const currentDist = Math.hypot(camera.position.x, camera.position.y, camera.position.z);
      
      // Use current distance or default if too close/far
      const targetDist = Math.max(CAMERA.MIN_DISTANCE, Math.min(currentDist, CAMERA.MAX_DISTANCE));
      
      // Calculate direction from node to camera
      const nodePos = new THREE.Vector3(node.x, node.y, node.z);
      const nodeToOrigin = new THREE.Vector3(-node.x, -node.y, -node.z).normalize();
      
      // Position camera at target distance from node, looking at it
      const camPos = nodePos.clone().add(nodeToOrigin.multiplyScalar(targetDist));
      
      fgRef.current.cameraPosition(
        { x: camPos.x, y: camPos.y, z: camPos.z },
        { x: node.x, y: node.y, z: node.z },
        CAMERA.TRANSITION_DURATION
      );
    }
  }, [onNodeClick]);

  // Handle node hover
  const handleNodeHover = useCallback((node: GraphNode | null) => {
    onNodeHover(node);
    
    // Change cursor
    if (fgRef.current) {
      const elem = fgRef.current.renderer().domElement;
      elem.style.cursor = node ? 'pointer' : 'default';
    }
  }, [onNodeHover]);

  // Node label - show node information not relationship
  const nodeLabel = useCallback((node: GraphNode) => {
    const name = node.name || 'Unknown';
    const type = node.label;
    const properties = node.properties || {};
    const summary = properties.summary || properties.description || '';
    const importance = properties.importance ? `Importance: ${(properties.importance * 100).toFixed(0)}%` : '';
    const truncated = summary.length > 150 ? summary.substring(0, 150) + '...' : summary;
    
    return `
      <div style="background: rgba(0,0,0,0.9); padding: 10px 14px; border-radius: 6px; color: white; max-width: 350px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
        <div style="font-weight: 600; margin-bottom: 6px; font-size: 15px; color: #fff;">${name}</div>
        <div style="font-size: 12px; color: #aaa; margin-bottom: ${truncated || importance ? '8px' : '0'};">${type}</div>
        ${importance ? `<div style="font-size: 11px; color: #4A90E2; margin-bottom: 6px;">${importance}</div>` : ''}
        ${truncated ? `<div style="font-size: 12px; color: #ccc; line-height: 1.4;">${truncated}</div>` : ''}
      </div>
    `;
  }, []);

  // Link label - only show relationship type, not on hover to avoid confusion
  const linkLabel = useCallback((_link: GraphLink) => {
    return '';
  }, []);

  // Link particles for highlighted connections (synapse effect)
  const linkDirectionalParticles = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    // Direct entity-to-entity links get more particles
    if (directLinks.has(linkId)) {
      return LINK_PARTICLES.COUNT_DIRECT;
    }
    return highlightLinks.has(linkId) ? LINK_PARTICLES.COUNT_HIGHLIGHTED : LINK_PARTICLES.COUNT_NORMAL;
  }, [highlightLinks, directLinks]);

  const linkDirectionalParticleWidth = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    // Direct links have larger particles
    if (directLinks.has(linkId)) {
      return LINK_PARTICLES.WIDTH_DIRECT;
    }
    return LINK_PARTICLES.WIDTH_NORMAL;
  }, [directLinks]);

  const linkDirectionalParticleSpeed = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    // Direct links have faster particles
    if (directLinks.has(linkId)) {
      return LINK_PARTICLES.SPEED_DIRECT;
    }
    return LINK_PARTICLES.SPEED_NORMAL;
  }, [directLinks]);

  // Setup camera and controls
  useEffect(() => {
    if (fgRef.current) {
      const fg = fgRef.current;
      
      // Set initial camera position
      fg.cameraPosition({ z: CAMERA.INITIAL_DISTANCE });
      
      // Add ambient light for better visibility
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
      fg.scene().add(ambientLight);
      
      // Add directional light
      const directionalLight = new THREE.DirectionalLight(0xffffff, 0.4);
      directionalLight.position.set(200, 500, 300);
      fg.scene().add(directionalLight);
      
      // Background
      fg.scene().background = new THREE.Color(0x0a0a0a);
    }
  }, []);

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <ForceGraph3D
        ref={fgRef}
        graphData={filteredData}
        nodeId="id"
        nodeLabel={nodeLabel}
        nodeColor={getNodeColor}
        nodeThreeObject={nodeThreeObject}
        nodeThreeObjectExtend={true}
        onNodeClick={handleNodeClick}
        onNodeRightClick={onNodeDoubleClick}
        onNodeHover={handleNodeHover}
        linkLabel={linkLabel}
        linkColor={getLinkColor}
        linkWidth={getLinkWidth}
        linkOpacity={getLinkOpacity as any}
        linkDirectionalParticles={linkDirectionalParticles}
        linkDirectionalParticleWidth={linkDirectionalParticleWidth}
        linkDirectionalParticleSpeed={linkDirectionalParticleSpeed}
        linkDirectionalParticleColor={getLinkColor}
        enableNodeDrag={true}
        enableNavigationControls={true}
        showNavInfo={false}
        cooldownTicks={100}
        warmupTicks={0}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}
      />
      
      {/* Stats */}
      <div style={{
        position: 'absolute',
        bottom: '20px',
        left: '20px',
        background: 'rgba(0,0,0,0.8)',
        padding: '10px 15px',
        borderRadius: '8px',
        color: 'white',
        fontSize: '12px',
      }}>
        <div>Nodes: {filteredData.nodes.length}</div>
        <div>Links: {filteredData.links.length}</div>
        {selectedNodes.size > 0 && <div>Selected: {selectedNodes.size}</div>}
      </div>
    </div>
  );
});

GraphCanvas.displayName = 'GraphCanvas';

// Memoize to prevent unnecessary re-renders when parent state changes (like panelMode)
export default React.memo(GraphCanvas, (prevProps, nextProps) => {
  // Only re-render if these specific props change
  return (
    prevProps.data === nextProps.data &&
    prevProps.selectedNodes === nextProps.selectedNodes &&
    prevProps.highlightNodes === nextProps.highlightNodes &&
    prevProps.highlightLinks === nextProps.highlightLinks &&
    prevProps.directLinks === nextProps.directLinks &&
    prevProps.nodeDistances === nextProps.nodeDistances &&
    prevProps.nodeConnectionCount === nextProps.nodeConnectionCount &&
    prevProps.hiddenNodeTypes === nextProps.hiddenNodeTypes &&
    prevProps.nodeSize === nextProps.nodeSize &&
    prevProps.linkSize === nextProps.linkSize
  );
});
