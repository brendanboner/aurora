import React, { useCallback, useEffect, useRef } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import type { GraphNode, GraphLink, GraphData } from '../types/graph';
import { gsap } from 'gsap';

interface GraphCanvasProps {
  data: GraphData;
  selectedNodes: Set<number>;
  onNodeClick: (node: GraphNode) => void;
  onNodeDoubleClick?: (node: GraphNode) => void; // Optional double-click handler
  onNodeHover: (node: GraphNode | null) => void;
  highlightNodes: Set<number>;
  highlightLinks: Set<string>;
  directLinks: Set<string>; // Direct links between entity nodes for special animation
  nodeDistances: Map<number, number>; // Distance from selected entities
  nodeConnectionCount: Map<number, number>; // How many entities connect through this node
  hiddenNodeTypes: Set<string>;
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
      
      // Calculate brightness based on distance:
      // Entity (distance 0) = 100%
      // 1-hop (distance 1) = 75%
      // 2-hop (distance 2) = 50%
      let brightnessFactor = 1.0;
      if (distance === 0) {
        brightnessFactor = 1.0; // Entity: full brightness
      } else if (distance === 1) {
        brightnessFactor = 0.75; // 1-hop: 75%
      } else if (distance === 2) {
        brightnessFactor = 0.5; // 2-hop: 50%
      } else {
        brightnessFactor = 0.4; // 3+ hops: 40%
      }
      
      // Connection boost: multiple connections = brighter (+25%)
      if (connections > 1) {
        brightnessFactor = Math.min(1.0, brightnessFactor + 0.25);
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
    
    // Dim non-highlighted nodes when something is highlighted (10% brightness)
    if (highlightNodes.size > 0) {
      const hex = baseColor.replace('#', '');
      const r = Math.round(parseInt(hex.substring(0, 2), 16) * 0.1);
      const g = Math.round(parseInt(hex.substring(2, 4), 16) * 0.1);
      const b = Math.round(parseInt(hex.substring(4, 6), 16) * 0.1);
      return `rgb(${r}, ${g}, ${b})`;
    }
    
    return baseColor;
  }, [selectedNodes, highlightNodes, nodeDistances, nodeConnectionCount]);

  const getNodeSize = useCallback((node: GraphNode) => {
    const baseSize = 4;
    const importance = node.properties?.importance || 0.5;
    const distance = nodeDistances.get(node.id);
    const connections = nodeConnectionCount.get(node.id) || 0;
    
    // If node is an entity (distance 0) - make it the largest
    if (distance === 0) {
      return baseSize * 2.5 * (0.5 + importance); // 250% of base - largest
    }
    
    // If node is highlighted (connected to entities)
    if (highlightNodes.has(node.id) && distance !== undefined) {
      // Size based on distance and connection strength
      let sizeMultiplier = 1.0;
      
      if (distance === 1) {
        // 1-hop: size based on number of connections (strength indicator)
        // Strong connections (multiple entities) get 90-95% of entity size
        // Weaker connections get 80-90%
        if (connections > 1) {
          sizeMultiplier = 2.3; // ~95% of entity size
        } else {
          sizeMultiplier = 2.0; // ~85% of entity size
        }
      } else if (distance === 2) {
        // 2-hop: 70-75% of entity size
        sizeMultiplier = 1.7;
      } else if (distance === 3) {
        // 3+ hops: 60% of entity size
        sizeMultiplier = 1.5;
      }
      
      return baseSize * sizeMultiplier * (0.5 + importance);
    }
    
    // Selected but not highlighted - slightly larger than default
    if (selectedNodes.has(node.id)) {
      return baseSize * 1.3 * (0.5 + importance);
    }
    
    // Default size
    return baseSize * (0.5 + importance);
  }, [selectedNodes, highlightNodes, nodeDistances, nodeConnectionCount]);

  // Custom node object with glow effect
  const nodeThreeObject = useCallback((node: GraphNode) => {
    const isHighlighted = selectedNodes.has(node.id) || highlightNodes.has(node.id);
    const isEntity = nodeDistances.get(node.id) === 0; // Entity nodes have distance 0
    const color = getNodeColor(node);
    const size = getNodeSize(node);
    
    const geometry = new THREE.SphereGeometry(size, 16, 16);
    const material = new THREE.MeshLambertMaterial({
      color: color,
      transparent: true,
      opacity: isHighlighted ? 1.0 : 0.8,
    });
    
    const mesh = new THREE.Mesh(geometry, material);
    
    // Add glow for highlighted nodes
    if (isHighlighted) {
      const glowGeometry = new THREE.SphereGeometry(size * 1.5, 16, 16);
      const glowMaterial = new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0.2,
      });
      const glow = new THREE.Mesh(glowGeometry, glowMaterial);
      mesh.add(glow);
      
      // Special pulsing animation for entity nodes (distance 0)
      if (isEntity) {
        gsap.to(glowMaterial, {
          opacity: 0.5,
          duration: 1.5,
          repeat: -1,
          yoyo: true,
          ease: 'sine.inOut',
        });
        
        // Also pulse the main material slightly for extra emphasis
        gsap.to(material, {
          opacity: 0.85,
          duration: 1.5,
          repeat: -1,
          yoyo: true,
          ease: 'sine.inOut',
        });
      } else {
        // Normal glow for non-entity highlighted nodes
        gsap.to(glowMaterial, {
          opacity: 0.3,
          duration: 1.0,
          repeat: -1,
          yoyo: true,
          ease: 'sine.inOut',
        });
      }
    }
    
    return mesh;
  }, [selectedNodes, highlightNodes, nodeDistances, getNodeColor, getNodeSize]);

  // Link visual properties
  const getLinkColor = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    
    // Direct entity-to-entity links get bright cyan - always bright
    if (directLinks.has(linkId)) {
      return '#00D9FF'; // Bright cyan for direct connections
    }
    
    // If links are highlighted, use consistent bright golden color
    // Brightness is controlled by opacity in getLinkOpacity, not color darkness
    if (highlightLinks.has(linkId)) {
      // Use bright golden/orange color - keep it constant, let opacity handle brightness
      return '#FFA500'; // Bright orange (constant brightness)
    }
    
    if (highlightLinks.size > 0) {
      return '#2C3E50'; // Dimmed
    }
    
    return '#7F8C8D'; // Normal gray
  }, [highlightLinks, directLinks]);

  const getLinkWidth = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    const confidence = link.properties?.confidence || 0.5;
    const importance = link.properties?.importance || 0.5;
    
    const baseWidth = 0.5;
    const weight = (confidence + importance) / 2;
    
    // Direct entity-to-entity links are moderately thicker
    if (directLinks.has(linkId)) {
      return baseWidth * 2.5 * weight;
    }
    
    // Highlighted links only slightly thicker - brightness comes from opacity and color
    if (highlightLinks.has(linkId)) {
      return baseWidth * 1.5 * weight;
    }
    
    return baseWidth * weight;
  }, [highlightLinks, directLinks]);

  const getLinkOpacity = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    
    // Direct entity-to-entity links are most visible
    if (directLinks.has(linkId)) {
      return 1.0;
    }
    
    // Highlighted links vary opacity by distance for true brightness effect
    if (highlightLinks.has(linkId)) {
      const targetId = typeof link.target === 'object' ? link.target.id : link.target;
      const distance = nodeDistances.get(targetId) || 0;
      
      // Distance-based opacity - higher values for better visibility
      if (distance === 0) return 1.0;      // Entity: fully opaque
      if (distance === 1) return 0.95;     // 1-hop: 95% (very bright)
      if (distance === 2) return 0.85;     // 2-hop: 85% (bright)
      return 0.7;                          // 3+ hops: 70%
    }
    
    if (highlightLinks.size > 0) {
      return 0.08;  // Very dim when not highlighted
    }
    
    return 0.4;
  }, [highlightLinks, directLinks, nodeDistances]);

  // Handle node click
  const handleNodeClick = useCallback((node: GraphNode) => {
    onNodeClick(node);
    
    // Smooth camera transition to node - position camera at a reasonable distance
    if (fgRef.current && node.x !== undefined && node.y !== undefined && node.z !== undefined) {
      // Get current camera position
      const camera = fgRef.current.camera();
      const currentDist = Math.hypot(camera.position.x, camera.position.y, camera.position.z);
      
      // Use current distance or default if too close/far
      const targetDist = Math.max(300, Math.min(currentDist, 800));
      
      // Calculate direction from node to camera
      const nodePos = new THREE.Vector3(node.x, node.y, node.z);
      const nodeToOrigin = new THREE.Vector3(-node.x, -node.y, -node.z).normalize();
      
      // Position camera at target distance from node, looking at it
      const camPos = nodePos.clone().add(nodeToOrigin.multiplyScalar(targetDist));
      
      fgRef.current.cameraPosition(
        { x: camPos.x, y: camPos.y, z: camPos.z },
        { x: node.x, y: node.y, z: node.z },
        1000
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
      return 8; // More particles for direct connections
    }
    return highlightLinks.has(linkId) ? 4 : 0;
  }, [highlightLinks, directLinks]);

  const linkDirectionalParticleWidth = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    // Direct links have larger particles
    if (directLinks.has(linkId)) {
      return 3;
    }
    return 2;
  }, [directLinks]);

  const linkDirectionalParticleSpeed = useCallback((link: GraphLink) => {
    const linkId = `${typeof link.source === 'object' ? link.source.id : link.source}-${typeof link.target === 'object' ? link.target.id : link.target}`;
    // Direct links have faster particles
    if (directLinks.has(linkId)) {
      return 0.01;
    }
    return 0.006;
  }, [directLinks]);

  // Setup camera and controls
  useEffect(() => {
    if (fgRef.current) {
      const fg = fgRef.current;
      
      // Set initial camera position
      fg.cameraPosition({ z: 1000 });
      
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
    prevProps.hiddenNodeTypes === nextProps.hiddenNodeTypes
  );
});
