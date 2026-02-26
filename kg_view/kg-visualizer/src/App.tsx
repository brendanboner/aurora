import React, { useState, useEffect, useCallback, useRef } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as THREE from 'three';
import GraphCanvas from './components/GraphCanvas';
import QueryBar from './components/QueryBar';
import TopicSelector from './components/TopicSelector';
import NodeDetails from './components/NodeDetails';
import { graphApi } from './services/api';
import type { GraphData, GraphNode, Entity, GraphStats } from './types/graph';
import './App.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function AppContent() {
  const graphRef = useRef<any>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [selectedNodes, setSelectedNodes] = useState<Set<number | string>>(new Set());
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEntities, setSelectedEntities] = useState<Entity[]>([]);
  const [highlightNodes, setHighlightNodes] = useState<Set<number | string>>(new Set());
  const [highlightLinks, setHighlightLinks] = useState<Set<string>>(new Set());
  const [directLinks, setDirectLinks] = useState<Set<string>>(new Set()); // Direct links between entity nodes
  const [nodeDistances, setNodeDistances] = useState<Map<number | string, number>>(new Map()); // Distance from selected entities
  const [nodeConnectionCount, setNodeConnectionCount] = useState<Map<number | string, number>>(new Map()); // How many entities connect through this node
  
  // Separate state for entity search highlights (primary) vs node exploration (secondary)
  const [entityHighlightNodes, setEntityHighlightNodes] = useState<Set<number | string>>(new Set());
  const [entityHighlightLinks, setEntityHighlightLinks] = useState<Set<string>>(new Set());
  const [entityDirectLinks, setEntityDirectLinks] = useState<Set<string>>(new Set());
  const [entityNodeDistances, setEntityNodeDistances] = useState<Map<number | string, number>>(new Map());
  const [entityNodeConnectionCount, setEntityNodeConnectionCount] = useState<Map<number | string, number>>(new Map());
  const [isNodeExplorationMode, setIsNodeExplorationMode] = useState(false);
  const [currentHops, setCurrentHops] = useState<number>(0);
  const [isLoadingHops, setIsLoadingHops] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [transformResult, setTransformResult] = useState<any>(null);
  const [transformError, setTransformError] = useState<string | null>(null);
  const [showBottomPanel, setShowBottomPanel] = useState(false);
  const [showSearchPanel, setShowSearchPanel] = useState(false);
  const [showTopicsPanel, setShowTopicsPanel] = useState(false);
  const [showNodeDetails, setShowNodeDetails] = useState(true);
  const [panelMode, setPanelMode] = useState<'stats' | 'legend' | 'off'>('stats');
  const [hiddenNodeTypes, setHiddenNodeTypes] = useState<Set<string>>(new Set(['IngestionBatch'])); // Hide IngestionBatch by default
  const [showNavHelper, setShowNavHelper] = useState(false);
  const [nodeSize, setNodeSize] = useState<number>(100); // 0 to 100%
  const [linkSize, setLinkSize] = useState<number>(100); // 0 to 100%

  // Load initial graph data and stats
  useEffect(() => {
    const loadInitialData = async () => {
      setIsLoading(true);
      try {
        const [graphStats, initialData] = await Promise.all([
          graphApi.getStats(),
          graphApi.getGraphData(1000, 0),
        ]);
        setStats(graphStats);
        setGraphData(initialData);
      } catch (err: any) {
        console.error('Failed to load initial data:', err);
        setError('Failed to connect to the knowledge graph. Please ensure the backend is running.');
      } finally {
        setIsLoading(false);
      }
    };

    loadInitialData();
  }, []);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Don't interfere if user is typing in an input
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return;
      }

      if (!graphRef.current) return;

      const camera = graphRef.current.camera();
      const moveSpeed = 100; // Units to move per key press
      const rotateSpeed = 0.3; // Radians to rotate

      switch (event.key) {
        case 'ArrowUp':
          event.preventDefault();
          // Move camera up (Y axis)
          graphRef.current.cameraPosition(
            {
              x: camera.position.x,
              y: camera.position.y + moveSpeed,
              z: camera.position.z,
            },
            undefined,
            200
          );
          break;

        case 'ArrowDown':
          event.preventDefault();
          // Move camera down (Y axis)
          graphRef.current.cameraPosition(
            {
              x: camera.position.x,
              y: camera.position.y - moveSpeed,
              z: camera.position.z,
            },
            undefined,
            200
          );
          break;

        case 'ArrowLeft':
          event.preventDefault();
          // Rotate camera left (around Y axis)
          {
            const currentPos = new THREE.Vector3(camera.position.x, camera.position.y, camera.position.z);
            const distance = currentPos.length();
            const currentAngle = Math.atan2(currentPos.x, currentPos.z);
            const newAngle = currentAngle + rotateSpeed;
            
            graphRef.current.cameraPosition(
              {
                x: Math.sin(newAngle) * distance,
                y: camera.position.y,
                z: Math.cos(newAngle) * distance,
              },
              { x: 0, y: 0, z: 0 },
              200
            );
          }
          break;

        case 'ArrowRight':
          event.preventDefault();
          // Rotate camera right (around Y axis)
          {
            const currentPos = new THREE.Vector3(camera.position.x, camera.position.y, camera.position.z);
            const distance = currentPos.length();
            const currentAngle = Math.atan2(currentPos.x, currentPos.z);
            const newAngle = currentAngle - rotateSpeed;
            
            graphRef.current.cameraPosition(
              {
                x: Math.sin(newAngle) * distance,
                y: camera.position.y,
                z: Math.cos(newAngle) * distance,
              },
              { x: 0, y: 0, z: 0 },
              200
            );
          }
          break;

        case '+':
        case '=':
          event.preventDefault();
          // Zoom in
          {
            const camera = graphRef.current.camera();
            const currentDistance = Math.sqrt(
              camera.position.x ** 2 + 
              camera.position.y ** 2 + 
              camera.position.z ** 2
            );
            const newDistance = currentDistance * 0.7;
            
            const direction = {
              x: camera.position.x / currentDistance,
              y: camera.position.y / currentDistance,
              z: camera.position.z / currentDistance,
            };
            
            graphRef.current.cameraPosition(
              {
                x: direction.x * newDistance,
                y: direction.y * newDistance,
                z: direction.z * newDistance,
              },
              { x: 0, y: 0, z: 0 },
              300
            );
          }
          break;

        case '-':
        case '_':
          event.preventDefault();
          // Zoom out
          {
            const camera = graphRef.current.camera();
            const currentDistance = Math.sqrt(
              camera.position.x ** 2 + 
              camera.position.y ** 2 + 
              camera.position.z ** 2
            );
            const newDistance = currentDistance * 1.4;
            
            const direction = {
              x: camera.position.x / currentDistance,
              y: camera.position.y / currentDistance,
              z: camera.position.z / currentDistance,
            };
            
            graphRef.current.cameraPosition(
              {
                x: direction.x * newDistance,
                y: direction.y * newDistance,
                z: direction.z * newDistance,
              },
              { x: 0, y: 0, z: 0 },
              300
            );
          }
          break;

        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Handle query execution
  const handleQueryExecute = useCallback(async (cypher: string, params: Record<string, any>) => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await graphApi.executeQuery(cypher, params);
      
      // Check if we have valid results
      if (!result || !result.results) {
        setError('Query returned no results. Try a different query.');
        setIsLoading(false);
        return;
      }
      
      // Transform results to graph data
      const nodes: GraphNode[] = [];
      const links: any[] = [];
      const nodeMap = new Map<number | string, GraphNode>();

      // Extract nodes and relationships from results
      result.results.forEach((record: any) => {
        Object.values(record).forEach((value: any) => {
          if (value && typeof value === 'object') {
            // Check if it's a node
            if (value.id !== undefined && value.labels) {
              const node: GraphNode = {
                id: value.id,
                label: value.labels[0],
                name: value.properties?.name || value.properties?.title || `Node ${value.id}`,
                properties: value.properties || {},
              };
              if (!nodeMap.has(node.id)) {
                nodeMap.set(node.id, node);
                nodes.push(node);
              }
            }
            // Check if it's a relationship
            if (value.start !== undefined && value.end !== undefined && value.type) {
              links.push({
                source: value.start,
                target: value.end,
                type: value.type,
                properties: value.properties || {},
              });
            }
          }
        });
      });

      if (nodes.length > 0) {
        setGraphData({ nodes, links });
        setError(null);
      } else {
        setError('Query returned no graph data. Try a different query.');
      }
    } catch (err: any) {
      console.error('Query execution failed:', err);
      setError(err.response?.data?.detail || err.message || 'Query execution failed');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Update highlighted connections between selected entities
  const updateHighlightedConnections = useCallback(async (entities: Entity[]) => {
    if (entities.length === 0) {
      setHighlightLinks(new Set());
      setHighlightNodes(new Set());
      setDirectLinks(new Set());
      setNodeDistances(new Map());
      setNodeConnectionCount(new Map());
      return;
    }

    try {
      // For single entity, show its neighborhood
      if (entities.length === 1) {
        const entity = entities[0];
        const searchResults = await graphApi.searchNodes(entity.name, 10);
        const matchingNodes = searchResults.filter(
          node => node.label.toLowerCase() === entity.type.toLowerCase()
        );
        
        if (matchingNodes.length > 0) {
          const nodeId = matchingNodes[0].id;
          const neighborhood = await graphApi.getNeighborhood(nodeId, 2, 200);
          
          // Validate neighborhood data
          if (!neighborhood || !neighborhood.nodes || !Array.isArray(neighborhood.nodes) || neighborhood.nodes.length === 0) {
            console.warn('No neighborhood data found for entity');
            setHighlightNodes(new Set());
            setHighlightLinks(new Set());
            setDirectLinks(new Set());
            return;
          }
          
          // Merge neighborhood into graph data
          setGraphData(prevData => {
            const existingNodeIds = new Set(prevData.nodes.map(n => n.id));
            const existingLinkKeys = new Set(
              prevData.links.map(l => {
                const src = typeof l.source === 'object' ? l.source.id : l.source;
                const tgt = typeof l.target === 'object' ? l.target.id : l.target;
                return `${src}-${tgt}`;
              })
            );

            const newNodes = neighborhood.nodes.filter(n => !existingNodeIds.has(n.id));
            const newLinks = neighborhood.links.filter(l => {
              const key = `${l.source}-${l.target}`;
              return !existingLinkKeys.has(key);
            });

            return {
              nodes: [...prevData.nodes, ...newNodes],
              links: [...prevData.links, ...newLinks],
              total_returned: (prevData.total_returned || 0) + newNodes.length,
            };
          });

          // Build adjacency for BFS distance calculation
          const adjacency = new Map<number | string, (number | string)[]>();
          if (neighborhood.links && Array.isArray(neighborhood.links)) {
            neighborhood.links.forEach(link => {
              const src = typeof link.source === 'object' ? link.source.id : link.source;
              const tgt = typeof link.target === 'object' ? link.target.id : link.target;
              if (!adjacency.has(src)) adjacency.set(src, []);
              if (!adjacency.has(tgt)) adjacency.set(tgt, []);
              adjacency.get(src)!.push(tgt);
              adjacency.get(tgt)!.push(src);
            });
          }

          // Calculate distances using BFS from the entity node
          const distances = calculateDistances(nodeId, adjacency);
          setNodeDistances(distances);
          setNodeConnectionCount(new Map([[nodeId, 1]]));

          // Highlight just this entity's neighborhood
          const nodeSet = new Set(neighborhood.nodes.map(n => n.id));
          const linkSet = new Set(
            neighborhood.links.map(l => `${l.source}-${l.target}`)
          );
          
          setHighlightNodes(nodeSet);
          setHighlightLinks(linkSet);
          setDirectLinks(new Set()); // No direct entity-to-entity links for single entity
        }
        return;
      }

      // For multiple entities, fetch the connecting subgraph
      const entityIds = entities.map(e => e.id);
      const subgraph = await graphApi.getEntitySubgraph(entityIds, 3, 500);
      
      // Validate subgraph data
      if (!subgraph || !subgraph.nodes || !Array.isArray(subgraph.nodes)) {
        console.warn('Invalid subgraph data received');
        setHighlightNodes(new Set());
        setHighlightLinks(new Set());
        setDirectLinks(new Set());
        return;
      }
      
      if (subgraph.nodes.length > 0) {
        // Find which nodes in the subgraph match our selected entities
        const entityNodeIds = new Set<number | string>();
        for (const entity of entities) {
          const matchingNode = subgraph.nodes.find(
            n => n.label.toLowerCase() === entity.type.toLowerCase() &&
                 (n.name === entity.name || 
                  n.properties?.person_id === entity.id ||
                  n.properties?.org_id === entity.id ||
                  n.properties?.topic_id === entity.id)
          );
          if (matchingNode) {
            entityNodeIds.add(matchingNode.id);
          }
        }

        // Build a graph to find paths between entity nodes
        const adjacency = new Map<number | string, (number | string)[]>();
        if (subgraph.links && Array.isArray(subgraph.links)) {
          subgraph.links.forEach(link => {
            const src = typeof link.source === 'object' ? link.source.id : link.source;
            const tgt = typeof link.target === 'object' ? link.target.id : link.target;
            if (!adjacency.has(src)) adjacency.set(src, []);
            if (!adjacency.has(tgt)) adjacency.set(tgt, []);
            adjacency.get(src)!.push(tgt);
            adjacency.get(tgt)!.push(src);
          });
        }

        // Check if we found any matching entity nodes
        if (entityNodeIds.size === 0) {
          console.warn('Could not find matching nodes for selected entities in subgraph');
          setHighlightNodes(new Set());
          setHighlightLinks(new Set());
          setDirectLinks(new Set());
          setNodeDistances(new Map());
          setNodeConnectionCount(new Map());
          return;
        }

        // Calculate distances from each entity node and count connections
        const allDistances = new Map<number | string, number>();
        const connectionCounts = new Map<number | string, number>();
        
        entityNodeIds.forEach(entityNodeId => {
          const distances = calculateDistances(entityNodeId, adjacency);
          distances.forEach((dist, nodeId) => {
            // Track minimum distance from any entity
            if (!allDistances.has(nodeId) || dist < allDistances.get(nodeId)!) {
              allDistances.set(nodeId, dist);
            }
            // Count how many entities this node connects to
            connectionCounts.set(nodeId, (connectionCounts.get(nodeId) || 0) + 1);
          });
        });

        setNodeDistances(allDistances);
        setNodeConnectionCount(connectionCounts);
        setEntityNodeDistances(allDistances);
        setEntityNodeConnectionCount(connectionCounts);

        // Find nodes and links on paths between entity nodes
        const pathNodes = new Set<number | string>(entityNodeIds);
        const pathLinks = new Set<string>();
        const directEntityLinks = new Set<string>(); // Track direct entity-to-entity links
        
        const entityNodeArray = Array.from(entityNodeIds);
        for (let i = 0; i < entityNodeArray.length; i++) {
          for (let j = i + 1; j < entityNodeArray.length; j++) {
            const path = findShortestPath(entityNodeArray[i], entityNodeArray[j], adjacency);
            if (path) {
              path.forEach(nodeId => pathNodes.add(nodeId));
              for (let k = 0; k < path.length - 1; k++) {
                const link1 = `${path[k]}-${path[k+1]}`;
                const link2 = `${path[k+1]}-${path[k]}`;
                pathLinks.add(link1);
                pathLinks.add(link2); // bidirectional
                
                // Check if this is a direct link between two entity nodes
                if (entityNodeIds.has(path[k]) && entityNodeIds.has(path[k+1])) {
                  directEntityLinks.add(link1);
                  directEntityLinks.add(link2);
                }
              }
            }
          }
        }

        // Merge new nodes into graph data
        setGraphData(prevData => {
          const existingNodeIds = new Set(prevData.nodes.map(n => n.id));
          const existingLinkKeys = new Set(
            prevData.links.map(l => {
              const src = typeof l.source === 'object' ? l.source.id : l.source;
              const tgt = typeof l.target === 'object' ? l.target.id : l.target;
              return `${src}-${tgt}`;
            })
          );

          const newNodes = subgraph.nodes.filter(n => !existingNodeIds.has(n.id));
          const newLinks = subgraph.links.filter(l => {
            const key = `${l.source}-${l.target}`;
            return !existingLinkKeys.has(key);
          });

          return {
            nodes: [...prevData.nodes, ...newNodes],
            links: [...prevData.links, ...newLinks],
            total_returned: (prevData.total_returned || 0) + newNodes.length,
          };
        });

        // Highlight only the path nodes and links
        setHighlightNodes(pathNodes);
        setHighlightLinks(pathLinks);
        setDirectLinks(directEntityLinks);
        // Save entity highlights (primary)
        setEntityHighlightNodes(pathNodes);
        setEntityHighlightLinks(pathLinks);
        setEntityDirectLinks(directEntityLinks);
        // Clear node exploration mode
        setIsNodeExplorationMode(false);
        setCurrentHops(0);

        // Zoom camera to fit the cluster of highlighted nodes
        setTimeout(() => {
          if (graphRef.current && pathNodes.size > 0) {
            const highlightedNodeObjects = subgraph.nodes.filter(n => pathNodes.has(n.id));
            
            if (highlightedNodeObjects.length > 0) {
              // Calculate center of cluster
              let sumX = 0, sumY = 0, sumZ = 0;
              highlightedNodeObjects.forEach(node => {
                sumX += node.x || 0;
                sumY += node.y || 0;
                sumZ += node.z || 0;
              });
              const centerX = sumX / highlightedNodeObjects.length;
              const centerY = sumY / highlightedNodeObjects.length;
              const centerZ = sumZ / highlightedNodeObjects.length;

              // Calculate appropriate distance based on cluster size
              let maxDist = 0;
              highlightedNodeObjects.forEach(node => {
                const dist = Math.sqrt(
                  Math.pow((node.x || 0) - centerX, 2) +
                  Math.pow((node.y || 0) - centerY, 2) +
                  Math.pow((node.z || 0) - centerZ, 2)
                );
                maxDist = Math.max(maxDist, dist);
              });

              const distance = Math.max(400, maxDist * 1.8);
              
              graphRef.current.cameraPosition(
                {
                  x: centerX,
                  y: centerY,
                  z: centerZ + distance,
                },
                { x: centerX, y: centerY, z: centerZ },
                1500
              );
            }
          }
        }, 100);
      } else {
        // Silently clear highlights if no connections found
        console.warn('No connections found between selected entities');
        setHighlightNodes(new Set());
        setHighlightLinks(new Set());
        setDirectLinks(new Set());
        setNodeDistances(new Map());
        setNodeConnectionCount(new Map());
      }
    } catch (err) {
      console.error('Failed to fetch entity subgraph:', err);
      // Gracefully degrade - clear highlights instead of showing error
      setHighlightNodes(new Set());
      setHighlightLinks(new Set());
      setDirectLinks(new Set());
      setNodeDistances(new Map());
      setNodeConnectionCount(new Map());
      // Only show error if it's a network issue
      if (err instanceof Error && (err.message.includes('Network') || err.message.includes('timeout'))) {
        setError('Network error. Please check your connection and try refreshing the page.');
      }
    }
  }, []);

  // Helper function to calculate distances from a start node using BFS
  const calculateDistances = (start: number | string, adjacency: Map<number | string, (number | string)[]>): Map<number | string, number> => {
    const distances = new Map<number | string, number>();
    const queue: [number | string, number][] = [[start, 0]];
    distances.set(start, 0);

    while (queue.length > 0) {
      const [current, dist] = queue.shift()!;
      
      const neighbors = adjacency.get(current) || [];
      for (const neighbor of neighbors) {
        if (!distances.has(neighbor)) {
          distances.set(neighbor, dist + 1);
          queue.push([neighbor, dist + 1]);
        }
      }
    }

    return distances;
  };

  // Helper function to find shortest path using BFS
  const findShortestPath = (start: number | string, end: number | string, adjacency: Map<number | string, (number | string)[]>): (number | string)[] | null => {
    const queue: [number | string, (number | string)[]][] = [[start, [start]]];
    const visited = new Set<number | string>([start]);

    while (queue.length > 0) {
      const [current, path] = queue.shift()!;
      
      if (current === end) {
        return path;
      }

      const neighbors = adjacency.get(current) || [];
      for (const neighbor of neighbors) {
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          queue.push([neighbor, [...path, neighbor]]);
        }
      }
    }

    return null;
  };

  // Handle entities extracted from query
  const handleEntitiesExtracted = useCallback(async (entities: Entity[]) => {
    // Add extracted entities to selected entities
    const newEntities: Entity[] = [];
    entities.forEach(entity => {
      if (!selectedEntities.find(e => e.id === entity.id)) {
        newEntities.push(entity);
      }
    });
    
    if (newEntities.length > 0) {
      setSelectedEntities(prev => [...prev, ...newEntities]);
      
      try {
        // Fetch and display subgraph for all selected entities
        const allEntities = [...selectedEntities, ...newEntities];
        await updateHighlightedConnections(allEntities);
      } catch (err) {
        console.error('Error updating connections after entity extraction:', err);
        // Keep entities in list even if connection update fails
      }
    }
  }, [selectedEntities, updateHighlightedConnections]);

  // Handle transform result from QueryBar
  const handleTransformResult = useCallback((result: any, error: string | null) => {
    setTransformResult(result);
    setTransformError(error);
    setShowBottomPanel(result !== null || error !== null);
  }, []);

  // Handle entity selection
  const handleEntityAdd = useCallback(async (entity: Entity) => {
    try {
      const newEntities = [...selectedEntities, entity];
      setSelectedEntities(newEntities);
      
      // If multiple entities, update connections automatically
      if (newEntities.length > 1) {
        await updateHighlightedConnections(newEntities);
      }
    } catch (err) {
      console.error('Error adding entity:', err);
      // Keep the entity in the list even if highlighting fails
      return;
    }
    
    // Center on the entity node
    try {
      const searchResults = await graphApi.searchNodes(entity.name, 100);
      const matchingResults = searchResults.filter(
        node => node.label.toLowerCase() === entity.type.toLowerCase()
      );
      
      if (matchingResults.length > 0 && graphRef.current) {
        const nodeInGraph = graphData.nodes.find(n => n.id === matchingResults[0].id);
        
        if (nodeInGraph && nodeInGraph.x !== undefined) {
          // Just center on the node without zooming
          graphRef.current.cameraPosition(
            undefined,
            { x: nodeInGraph.x || 0, y: nodeInGraph.y || 0, z: nodeInGraph.z || 0 },
            1000
          );
        }
      }
    } catch (err) {
      console.error('Failed to find entity:', err);
    }
  }, [selectedEntities, graphData, updateHighlightedConnections]);

  const handleEntityRemove = useCallback(async (entity: Entity) => {
    try {
      const remaining = selectedEntities.filter(e => e.id !== entity.id);
      setSelectedEntities(remaining);
      
      // Update highlights based on remaining entities
      if (remaining.length > 1) {
        await updateHighlightedConnections(remaining);
      } else if (remaining.length === 1) {
        // Update to show just the single entity's neighborhood
        await updateHighlightedConnections(remaining);
      } else if (remaining.length === 0) {
        // Clear all highlights
        setHighlightNodes(new Set());
        setHighlightLinks(new Set());
        setDirectLinks(new Set());
        setNodeDistances(new Map());
        setNodeConnectionCount(new Map());
      }
    } catch (err) {
      console.error('Error removing entity:', err);
      // Continue anyway - entity is already removed from UI
    }
  }, [selectedEntities, updateHighlightedConnections]);

  // Handle entity click to center and flash the node
  const handleEntityClick = useCallback(async (_entity: Entity) => {
    // Just select the entity, camera will be handled by handleEntityMouseUp
    // This prevents competing camera movements
  }, []);

  // Handle entity highlight from hover - disabled, only used for mouse down/up
  const handleEntityHighlight = useCallback(async () => {
    // Do nothing on hover
  }, []);

  // Handle entity mouse down - show 1-2 hop neighborhood
  const handleEntityMouseDown = useCallback(async (entity: Entity) => {
    try {
      const searchResults = await graphApi.searchNodes(entity.name, 10);
      const matchingResults = searchResults.filter(
        node => node.label.toLowerCase() === entity.type.toLowerCase()
      );
      
      if (matchingResults.length > 0) {
        const entityNodeId = matchingResults[0].id; // This is now a string (elementId)
        
        // Fetch 2-hop neighborhood
        const neighborhoodData = await graphApi.getNeighborhood(entityNodeId, 2, 500);
        
        // Merge neighborhood data into graph FIRST
        setGraphData(prevData => {
          const existingNodeIds = new Set(prevData.nodes.map(n => n.id));
          const existingLinkKeys = new Set(
            prevData.links.map(l => {
              const src = typeof l.source === 'object' ? l.source.id : l.source;
              const tgt = typeof l.target === 'object' ? l.target.id : l.target;
              return `${src}-${tgt}`;
            })
          );

          const newNodes = neighborhoodData.nodes.filter(n => !existingNodeIds.has(n.id));
          const newLinks = neighborhoodData.links.filter(l => {
            const key = `${l.source}-${l.target}`;
            return !existingLinkKeys.has(key);
          });

          return {
            nodes: [...prevData.nodes, ...newNodes],
            links: [...prevData.links, ...newLinks],
            total_returned: (prevData.total_returned || 0) + newNodes.length,
          };
        });
        
        // Build adjacency map for distance calculation
        const adjacency = new Map<number | string, (number | string)[]>();
        neighborhoodData.links.forEach(link => {
          const src = typeof link.source === 'object' ? link.source.id : link.source;
          const tgt = typeof link.target === 'object' ? link.target.id : link.target;
          if (!adjacency.has(src)) adjacency.set(src, []);
          if (!adjacency.has(tgt)) adjacency.set(tgt, []);
          adjacency.get(src)!.push(tgt);
          adjacency.get(tgt)!.push(src);
        });

        // Calculate distances from entity node
        const distances = calculateDistances(entityNodeId, adjacency);
        
        // Filter to only 0, 1, 2 hop nodes
        const filteredDistances = new Map<number | string, number>();
        distances.forEach((dist, nodeId) => {
          if (dist <= 2) {
            filteredDistances.set(nodeId, dist);
          }
        });
        
        setNodeDistances(filteredDistances);
        setNodeConnectionCount(new Map()); // Reset connection count
        
        // Highlight only nodes within 2 hops
        const nodesToHighlight = new Set(Array.from(filteredDistances.keys()));
        setHighlightNodes(nodesToHighlight);
        
        // Highlight links between these nodes
        const linksToHighlight = new Set<string>();
        neighborhoodData.links.forEach(link => {
          const src = typeof link.source === 'object' ? link.source.id : link.source;
          const tgt = typeof link.target === 'object' ? link.target.id : link.target;
          if (nodesToHighlight.has(src) && nodesToHighlight.has(tgt)) {
            linksToHighlight.add(`${src}-${tgt}`);
            linksToHighlight.add(`${tgt}-${src}`);
          }
        });
        setHighlightLinks(linksToHighlight);
        setDirectLinks(new Set()); // No direct links in single entity mode
      }
    } catch (err) {
      console.error('Failed to highlight neighborhood:', err);
    }
  }, [graphData]);

  // Handle entity mouse up - center with intelligent zoom and keep highlights
  const handleEntityMouseUp = useCallback(async (entity: Entity) => {
    try {
      const searchResults = await graphApi.searchNodes(entity.name, 10);
      const matchingResults = searchResults.filter(
        node => node.label.toLowerCase() === entity.type.toLowerCase()
      );
      
      if (matchingResults.length > 0 && graphRef.current) {
        const entityNodeId = matchingResults[0].id;
        const nodeInGraph = graphData.nodes.find(n => n.id === entityNodeId);
        
        if (nodeInGraph && nodeInGraph.x !== undefined) {
          // Wait for graph positions to stabilize after data update
          setTimeout(() => {
            if (!graphRef.current) return;
            
            // Find all highlighted nodes with valid positions
            const highlightedNodeObjects = graphData.nodes.filter(n => 
              highlightNodes.has(n.id) && 
              n.x !== undefined && 
              n.y !== undefined && 
              n.z !== undefined &&
              !isNaN(n.x) && !isNaN(n.y) && !isNaN(n.z)
            );
            
            if (highlightedNodeObjects.length > 0) {
              // Calculate center and extent of highlighted nodes
              let sumX = 0, sumY = 0, sumZ = 0;
              highlightedNodeObjects.forEach(node => {
                sumX += node.x!;
                sumY += node.y!;
                sumZ += node.z!;
              });
              const centerX = sumX / highlightedNodeObjects.length;
              const centerY = sumY / highlightedNodeObjects.length;
              const centerZ = sumZ / highlightedNodeObjects.length;

              // Calculate max distance from center to set appropriate zoom
              let maxDist = 0;
              highlightedNodeObjects.forEach(node => {
                const dist = Math.sqrt(
                  Math.pow(node.x! - centerX, 2) +
                  Math.pow(node.y! - centerY, 2) +
                  Math.pow(node.z! - centerZ, 2)
                );
                maxDist = Math.max(maxDist, dist);
              });

              // Set camera to show all highlighted nodes with appropriate padding
              const distance = Math.max(400, maxDist * 1.8);
              
              graphRef.current.cameraPosition(
                {
                  x: centerX,
                  y: centerY,
                  z: centerZ + distance,
                },
                { x: centerX, y: centerY, z: centerZ },
                1000
              );
            }
          }, 100); // Small delay to let graph positions stabilize
        }
      }
      // Keep the highlights (don't clear them)
    } catch (err) {
      console.error('Failed to center on entity:', err);
    }
  }, [graphData, highlightNodes]);

  // Handle node click
  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node);
    setIsNodeExplorationMode(false); // Start with no hops
    setCurrentHops(0);
    
    // Single click: center the camera on the node at reasonable distance
    if (graphRef.current && node.x !== undefined && node.y !== undefined && node.z !== undefined) {
      const camera = graphRef.current.camera();
      const currentDist = Math.hypot(
        camera.position.x - node.x,
        camera.position.y - node.y,
        camera.position.z - node.z
      );
      
      const targetDist = Math.max(400, Math.min(currentDist, 800));
      
      const direction = new THREE.Vector3(
        camera.position.x - node.x,
        camera.position.y - node.y,
        camera.position.z - node.z
      ).normalize();
      
      graphRef.current.cameraPosition(
        {
          x: node.x + direction.x * targetDist,
          y: node.y + direction.y * targetDist,
          z: node.z + direction.z * targetDist
        },
        { x: node.x, y: node.y, z: node.z },
        1000
      );
    }
    
    // Toggle selection
    setSelectedNodes(prev => {
      const newSet = new Set(prev);
      if (newSet.has(node.id)) {
        newSet.delete(node.id);
      } else {
        newSet.add(node.id);
      }
      return newSet;
    });
  }, []);

  // Handle node hover
  const handleNodeHover = useCallback((_node: GraphNode | null) => {
    // Just pass through to child components if needed
  }, []);

  // Handle hop selection for current node (boost on top of entity highlights)
  const handleHopSelection = useCallback(async (nodeId: number | string, hops: number) => {
    if (hops === 0) {
      // Reset to entity highlights only
      setIsNodeExplorationMode(false);
      setCurrentHops(0);
      setHighlightNodes(entityHighlightNodes);
      setHighlightLinks(entityHighlightLinks);
      setDirectLinks(entityDirectLinks);
      setNodeDistances(entityNodeDistances);
      setNodeConnectionCount(entityNodeConnectionCount);
      return;
    }

    setIsLoadingHops(true);
    setCurrentHops(hops);
    try {
      // Convert nodeId to string if it's a number (for backwards compatibility)
      const nodeIdStr = typeof nodeId === 'number' ? String(nodeId) : nodeId;
      const neighborhoodData = await graphApi.getNeighborhood(nodeIdStr, hops, 300);
      
      // Merge with graph data
      setGraphData(prevData => {
        const existingNodeIds = new Set(prevData.nodes.map(n => n.id));
        const existingLinkKeys = new Set(
          prevData.links.map(l => {
            const src = typeof l.source === 'object' ? l.source.id : l.source;
            const tgt = typeof l.target === 'object' ? l.target.id : l.target;
            return `${src}-${tgt}`;
          })
        );

        const newNodes = neighborhoodData.nodes.filter(n => !existingNodeIds.has(n.id));
        const newLinks = neighborhoodData.links.filter(l => {
          const key = `${l.source}-${l.target}`;
          return !existingLinkKeys.has(key);
        });

        return {
          nodes: [...prevData.nodes, ...newNodes],
          links: [...prevData.links, ...newLinks],
          total_returned: (prevData.total_returned || 0) + newNodes.length,
        };
      });
      
      // Build adjacency for distance calculation
      const adjacency = new Map<number | string, (number | string)[]>();
      if (neighborhoodData.links && Array.isArray(neighborhoodData.links)) {
        neighborhoodData.links.forEach(link => {
          const src = typeof link.source === 'object' ? link.source.id : link.source;
          const tgt = typeof link.target === 'object' ? link.target.id : link.target;
          if (!adjacency.has(src)) adjacency.set(src, []);
          if (!adjacency.has(tgt)) adjacency.set(tgt, []);
          adjacency.get(src)!.push(tgt);
          adjacency.get(tgt)!.push(src);
        });
      }

      // Calculate distances from selected node
      const distances = calculateDistances(nodeId, adjacency);
      const filteredDistances = new Map<number | string, number>();
      distances.forEach((dist, nId) => {
        if (dist <= hops) {
          filteredDistances.set(nId, dist);
        }
      });
      
      // Combine entity highlights with node exploration highlights
      const combinedNodes = new Set([...entityHighlightNodes, ...Array.from(filteredDistances.keys())]);
      const nodesToHighlight = new Set(Array.from(filteredDistances.keys()));
      
      // Highlight links for hop neighborhood
      const linksToHighlight = new Set<string>();
      if (neighborhoodData.links && Array.isArray(neighborhoodData.links)) {
        neighborhoodData.links.forEach(link => {
          const src = typeof link.source === 'object' ? link.source.id : link.source;
          const tgt = typeof link.target === 'object' ? link.target.id : link.target;
          if (nodesToHighlight.has(src) && nodesToHighlight.has(tgt)) {
            linksToHighlight.add(`${src}-${tgt}`);
            linksToHighlight.add(`${tgt}-${src}`);
          }
        });
      }
      
      // Combine with entity highlights
      const combinedLinks = new Set([...entityHighlightLinks, ...linksToHighlight]);
      
      setHighlightNodes(combinedNodes);
      setHighlightLinks(combinedLinks);
      setDirectLinks(new Set([...entityDirectLinks])); // Keep entity direct links
      setNodeDistances(filteredDistances);
      setNodeConnectionCount(new Map());
      setIsNodeExplorationMode(true);
    } catch (err) {
      console.error('Failed to load hop neighborhood:', err);
    } finally {
      setIsLoadingHops(false);
    }
  }, [entityHighlightNodes, entityHighlightLinks, entityDirectLinks, entityNodeDistances, entityNodeConnectionCount, graphData]);

  // Explore node neighborhood
  const handleExploreNeighborhood = useCallback(async (nodeId: number | string, hops: number) => {
    setIsLoading(true);
    try {
      const neighborhoodData = await graphApi.getNeighborhood(nodeId, hops, 200);
      
      // Merge with existing data
      const existingNodeIds = new Set(graphData.nodes.map(n => n.id));
      const newNodes = neighborhoodData.nodes.filter(n => !existingNodeIds.has(n.id));
      
      setGraphData(prev => ({
        nodes: [...prev.nodes, ...newNodes],
        links: [...prev.links, ...neighborhoodData.links],
      }));
    } catch (err) {
      console.error('Failed to explore neighborhood:', err);
      setError('Failed to load neighborhood data');
    } finally {
      setIsLoading(false);
    }
  }, [graphData]);

  // Handle node right-click (double-click alternative): center and explore neighborhood
  const handleNodeDoubleClick = useCallback(async (node: GraphNode) => {
    // Select the node
    setSelectedNode(node);
    setSelectedNodes(new Set([node.id]));
    
    // Explore 2-hop neighborhood first (loads data)
    await handleExploreNeighborhood(node.id, 2);
    
    // Wait for graph to update, then center camera on node and its neighborhood
    setTimeout(() => {
      if (!graphRef.current || node.x === undefined || node.y === undefined || node.z === undefined) return;
      
      // Find all highlighted nodes
      const highlightedNodeObjects = graphData.nodes.filter(n => 
        highlightNodes.has(n.id) && 
        n.x !== undefined && 
        n.y !== undefined && 
        n.z !== undefined &&
        !isNaN(n.x) && !isNaN(n.y) && !isNaN(n.z)
      );
      
      if (highlightedNodeObjects.length > 1) {
        // Calculate center of neighborhood
        let sumX = 0, sumY = 0, sumZ = 0;
        highlightedNodeObjects.forEach(n => {
          sumX += n.x!;
          sumY += n.y!;
          sumZ += n.z!;
        });
        const centerX = sumX / highlightedNodeObjects.length;
        const centerY = sumY / highlightedNodeObjects.length;
        const centerZ = sumZ / highlightedNodeObjects.length;
        
        // Calculate max distance to fit all nodes
        let maxDist = 0;
        highlightedNodeObjects.forEach(n => {
          const dist = Math.sqrt(
            Math.pow(n.x! - centerX, 2) +
            Math.pow(n.y! - centerY, 2) +
            Math.pow(n.z! - centerZ, 2)
          );
          maxDist = Math.max(maxDist, dist);
        });
        
        // Zoom out to adequate distance to see entire neighborhood
        const distance = Math.max(500, maxDist * 2.5);
        
        graphRef.current.cameraPosition(
          { x: centerX, y: centerY, z: centerZ + distance },
          { x: centerX, y: centerY, z: centerZ },
          1500 // Smooth 1.5s transition
        );
      } else {
        // Just center on the node
        const distance = 600;
        graphRef.current.cameraPosition(
          { x: node.x, y: node.y, z: node.z + distance },
          { x: node.x, y: node.y, z: node.z },
          1500
        );
      }
    }, 300); // Wait for neighborhood data to load and positions to update
  }, [handleExploreNeighborhood, graphData, highlightNodes]);

  // Navigation helper functions
  const handleZoomToFit = useCallback(() => {
    if (graphRef.current) {
      graphRef.current.zoomToFit(1000);
    }
  }, []);

  const handleZoomToCluster = useCallback(() => {
    if (graphRef.current) {
      // If we have selected entities, focus on them and their 2-hop neighborhoods
      if (selectedEntities.length > 0 && highlightNodes.size > 0) {
        const highlightedNodeObjects = graphData.nodes.filter(n => 
          highlightNodes.has(n.id) && 
          n.x !== undefined && 
          n.y !== undefined && 
          n.z !== undefined &&
          !isNaN(n.x) && !isNaN(n.y) && !isNaN(n.z)
        );
        
        if (highlightedNodeObjects.length > 0) {
          // Calculate center of the highlighted cluster
          let sumX = 0, sumY = 0, sumZ = 0;
          highlightedNodeObjects.forEach(node => {
            sumX += node.x!;
            sumY += node.y!;
            sumZ += node.z!;
          });
          const centerX = sumX / highlightedNodeObjects.length;
          const centerY = sumY / highlightedNodeObjects.length;
          const centerZ = sumZ / highlightedNodeObjects.length;

          // Calculate max distance from center to encompass all 2-hop nodes
          let maxDist = 0;
          highlightedNodeObjects.forEach(node => {
            const dist = Math.sqrt(
              Math.pow(node.x! - centerX, 2) +
              Math.pow(node.y! - centerY, 2) +
              Math.pow(node.z! - centerZ, 2)
            );
            maxDist = Math.max(maxDist, dist);
          });

          // Intelligent zoom: ensure all nodes are visible with appropriate padding
          const distance = Math.max(400, maxDist * 1.8);
          
          graphRef.current.cameraPosition(
            {
              x: centerX,
              y: centerY,
              z: centerZ + distance,
            },
            { x: centerX, y: centerY, z: centerZ },
            1000
          );
        }
      } else if (highlightNodes.size > 0) {
        // Fallback: zoom to any highlighted nodes
        const highlightedNodeObjects = graphData.nodes.filter(n => highlightNodes.has(n.id));
        
        if (highlightedNodeObjects.length > 0) {
          let sumX = 0, sumY = 0, sumZ = 0;
          highlightedNodeObjects.forEach(node => {
            sumX += node.x || 0;
            sumY += node.y || 0;
            sumZ += node.z || 0;
          });
          const centerX = sumX / highlightedNodeObjects.length;
          const centerY = sumY / highlightedNodeObjects.length;
          const centerZ = sumZ / highlightedNodeObjects.length;

          let maxDist = 0;
          highlightedNodeObjects.forEach(node => {
            const dist = Math.sqrt(
              Math.pow((node.x || 0) - centerX, 2) +
              Math.pow((node.y || 0) - centerY, 2) +
              Math.pow((node.z || 0) - centerZ, 2)
            );
            maxDist = Math.max(maxDist, dist);
          });

          const distance = Math.max(300, maxDist * 2.5);
          
          graphRef.current.cameraPosition(
            {
              x: centerX,
              y: centerY,
              z: centerZ + distance,
            },
            { x: centerX, y: centerY, z: centerZ },
            1000
          );
        }
      }
    }
  }, [graphData, highlightNodes, selectedEntities]);

  const handleZoomIn = useCallback(() => {
    if (graphRef.current) {
      const camera = graphRef.current.camera();
      const currentDistance = Math.sqrt(
        camera.position.x ** 2 + 
        camera.position.y ** 2 + 
        camera.position.z ** 2
      );
      const newDistance = currentDistance * 0.7;
      
      const direction = {
        x: camera.position.x / currentDistance,
        y: camera.position.y / currentDistance,
        z: camera.position.z / currentDistance,
      };
      
      graphRef.current.cameraPosition(
        {
          x: direction.x * newDistance,
          y: direction.y * newDistance,
          z: direction.z * newDistance,
        },
        { x: 0, y: 0, z: 0 },
        300
      );
    }
  }, []);

  const handleZoomOut = useCallback(() => {
    if (graphRef.current) {
      const camera = graphRef.current.camera();
      const currentDistance = Math.sqrt(
        camera.position.x ** 2 + 
        camera.position.y ** 2 + 
        camera.position.z ** 2
      );
      const newDistance = currentDistance * 1.4;
      
      const direction = {
        x: camera.position.x / currentDistance,
        y: camera.position.y / currentDistance,
        z: camera.position.z / currentDistance,
      };
      
      graphRef.current.cameraPosition(
        {
          x: direction.x * newDistance,
          y: direction.y * newDistance,
          z: direction.z * newDistance,
        },
        { x: 0, y: 0, z: 0 },
        300
      );
    }
  }, []);

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#0a0a0a' }}>
      {/* Top Control Buttons */}
      <div style={{
        position: 'fixed',
        top: '10px',
        left: '10px',
        zIndex: 1001,
        display: 'flex',
        gap: '8px',
      }}>
        <button
          onClick={() => {
            setShowSearchPanel(!showSearchPanel);
            setShowTopicsPanel(false);
          }}
          style={{
            padding: '10px 20px',
            background: showSearchPanel ? '#1976d2' : 'rgba(0,0,0,0.8)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: '500',
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            transition: 'all 0.2s',
          }}
        >
          🔍 Search
        </button>
        <button
          onClick={() => {
            setShowTopicsPanel(!showTopicsPanel);
            setShowSearchPanel(false);
          }}
          style={{
            padding: '10px 20px',
            background: showTopicsPanel ? '#1976d2' : 'rgba(0,0,0,0.8)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: '500',
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            transition: 'all 0.2s',
          }}
        >
          🏷️ Topics ({selectedEntities.length})
        </button>
      </div>

      {/* Collapsible Search Panel */}
      {showSearchPanel && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 1000,
          background: 'rgba(0,0,0,0.95)',
          padding: '60px 20px 20px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
          animation: 'slideDown 0.3s ease-out',
        }}>
          <QueryBar
            onQueryExecute={handleQueryExecute}
            onEntitiesExtracted={handleEntitiesExtracted}
            onTransformResult={handleTransformResult}
            isLoading={isLoading}
          />
        </div>
      )}

      {/* Collapsible Topics Panel */}
      {showTopicsPanel && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 1000,
          background: 'rgba(0,0,0,0.95)',
          padding: '60px 20px 20px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
          animation: 'slideDown 0.3s ease-out',
        }}>
          <TopicSelector
            selectedEntities={selectedEntities}
            onEntityAdd={handleEntityAdd}
            onEntityRemove={handleEntityRemove}
            onEntityClick={handleEntityClick}
            onHighlight={handleEntityHighlight}
            onEntityMouseDown={handleEntityMouseDown}
            onEntityMouseUp={handleEntityMouseUp}
          />
        </div>
      )}

      {/* Graph Canvas */}
      <div style={{ width: '100%', height: '100%' }}>
        {error ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: 'white',
            fontSize: '18px',
            padding: '40px',
            textAlign: 'center',
          }}>
            <div>
              <div style={{ fontSize: '48px', marginBottom: '20px' }}>⚠️</div>
              <div>{error}</div>
              <div style={{ marginTop: '20px', fontSize: '14px', opacity: 0.7 }}>
                Try refreshing the page or check your connection
              </div>
            </div>
          </div>
        ) : graphData.nodes.length === 0 && !isLoading ? (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            color: 'white',
            fontSize: '18px',
          }}>
            Loading knowledge graph...
          </div>
        ) : (
          <GraphCanvas
            ref={graphRef}
            data={graphData}
            selectedNodes={selectedNodes}
            onNodeClick={handleNodeClick}
            onNodeDoubleClick={handleNodeDoubleClick}
            onNodeHover={handleNodeHover}
            highlightNodes={highlightNodes}
            highlightLinks={highlightLinks}
            directLinks={directLinks}
            nodeDistances={nodeDistances}
            nodeConnectionCount={nodeConnectionCount}
            hiddenNodeTypes={hiddenNodeTypes}
            nodeSize={nodeSize}
            linkSize={linkSize}
          />
        )}
      </div>

      {/* Node Details Panel */}
      {selectedNode && showNodeDetails && (
        <NodeDetails
          node={selectedNode}
          onClose={() => {
            setSelectedNode(null);
            setSelectedNodes(new Set());
            // Restore entity highlights when closing
            if (isNodeExplorationMode) {
              setHighlightNodes(entityHighlightNodes);
              setHighlightLinks(entityHighlightLinks);
              setDirectLinks(entityDirectLinks);
              setNodeDistances(entityNodeDistances);
              setNodeConnectionCount(entityNodeConnectionCount);
              setIsNodeExplorationMode(false);
              setCurrentHops(0);
            }
          }}
          onToggle={() => setShowNodeDetails(!showNodeDetails)}
          onExploreNeighborhood={handleExploreNeighborhood}
          onHopSelection={handleHopSelection}
          currentHops={currentHops}
          isLoadingHops={isLoadingHops}
        />
      )}

      {/* Toggle Node Details Button (when hidden) */}
      {selectedNode && !showNodeDetails && (
        <button
          onClick={() => setShowNodeDetails(true)}
          style={{
            position: 'fixed',
            bottom: '20px',
            left: '20px',
            padding: '10px 16px',
            background: 'rgba(0,0,0,0.8)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '13px',
            fontWeight: '500',
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
            zIndex: 100,
          }}
        >
          Show Node Details
        </button>
      )}

      {/* Panel Mode Toggle Button */}
      <button
        onClick={() => {
          setPanelMode(prev => 
            prev === 'stats' ? 'legend' : 
            prev === 'legend' ? 'off' : 'stats'
          );
        }}
        style={{
          position: 'fixed',
          top: '10px',
          right: '10px',
          padding: '10px 16px',
          background: 'rgba(0,0,0,0.8)',
          color: 'white',
          border: 'none',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: '500',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
          zIndex: 100,
        }}
      >
        {panelMode === 'stats' ? '📊 Stats' : 
         panelMode === 'legend' ? '🎨 Legend' : '◯ Off'}
      </button>

      {/* Combined Stats/Legend Panel */}
      {panelMode !== 'off' && stats && (
        <div style={{
          position: 'fixed',
          top: '50px',
          right: '10px',
          background: 'rgba(0,0,0,0.9)',
          padding: '12px',
          borderRadius: '6px',
          color: 'white',
          fontSize: '12px',
          zIndex: 100,
          maxWidth: '220px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        }}>
          {panelMode === 'stats' ? (
            <>
              <div style={{ fontWeight: 'bold', marginBottom: '10px' }}>Knowledge Graph Stats</div>
              {Object.entries(stats.nodes).map(([label, count]) => (
                <div 
                  key={label} 
                  onClick={() => {
                    setHiddenNodeTypes(prev => {
                      const newSet = new Set(prev);
                      if (newSet.has(label)) {
                        newSet.delete(label);
                      } else {
                        newSet.add(label);
                      }
                      return newSet;
                    });
                  }}
                  style={{ 
                    marginBottom: '5px',
                    cursor: 'pointer',
                    textDecoration: hiddenNodeTypes.has(label) ? 'line-through' : 'none',
                    opacity: hiddenNodeTypes.has(label) ? 0.5 : 1,
                    transition: 'opacity 0.2s',
                  }}
                >
                  <span style={{ color: '#95A5A6' }}>{label}:</span>{' '}
                  <span style={{ fontWeight: 'bold' }}>{count.toLocaleString()}</span>
                </div>
              ))}
              <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid #34495E' }}>
                <span style={{ color: '#95A5A6' }}>Total Relationships:</span>{' '}
                <span style={{ fontWeight: 'bold' }}>{stats.relationships.toLocaleString()}</span>
              </div>
              <div style={{ marginTop: '8px', fontSize: '10px', color: '#7F8C8D', fontStyle: 'italic' }}>
                💡 Click node types to show/hide
              </div>
            </>
          ) : (
            <>
              <div style={{ fontWeight: 'bold', marginBottom: '10px' }}>Node Type Legend</div>
              {Object.entries({
                Organization: '#2ECC71',
                Topic: '#9B59B6',
                Person: '#E74C3C',
                Resource: '#3498DB',
                Event: '#F39C12',
                DataSource: '#1ABC9C',
                IngestionBatch: '#95A5A6',
              }).map(([type, color]) => (
                <div 
                  key={type}
                  onClick={() => {
                    setHiddenNodeTypes(prev => {
                      const newSet = new Set(prev);
                      if (newSet.has(type)) {
                        newSet.delete(type);
                      } else {
                        newSet.add(type);
                      }
                      return newSet;
                    });
                  }}
                  style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    marginBottom: '6px',
                    cursor: 'pointer',
                    textDecoration: hiddenNodeTypes.has(type) ? 'line-through' : 'none',
                    opacity: hiddenNodeTypes.has(type) ? 0.5 : 1,
                    transition: 'opacity 0.2s',
                  }}
                >
                  <div style={{
                    width: '12px',
                    height: '12px',
                    borderRadius: '50%',
                    backgroundColor: color,
                    marginRight: '8px',
                  }} />
                  <span>{type}</span>
                </div>
              ))}
              <div style={{ marginTop: '8px', fontSize: '10px', color: '#7F8C8D', fontStyle: 'italic' }}>
                💡 Click to show/hide types
              </div>
            </>
          )}
        </div>
      )}

      {/* Bottom Panel for LLM Response */}
      {showBottomPanel && (
        <div style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          background: 'white',
          borderTop: '1px solid #e0e0e0',
          boxShadow: '0 -2px 8px rgba(0,0,0,0.1)',
          zIndex: 999,
          maxHeight: '50vh',
          overflowY: 'auto',
        }}>
          <div style={{
            padding: '12px 20px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: '#f8f9fa',
            borderBottom: '1px solid #e0e0e0',
          }}>
            <span style={{ fontWeight: '600', color: '#333', fontSize: '14px' }}>
              Query Analysis
            </span>
            <button
              onClick={() => setShowBottomPanel(false)}
              style={{
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                fontSize: '20px',
                color: '#666',
                padding: '0 8px',
              }}
            >
              ▼
            </button>
          </div>
          
          <div style={{ padding: '16px 20px' }}>
            {transformError && (
              <div style={{
                padding: '12px',
                background: '#ffebee',
                color: '#c62828',
                borderRadius: '4px',
                fontSize: '14px',
                marginBottom: '12px',
              }}>
                ⚠️ {transformError}
              </div>
            )}
            
            {transformResult && (
              <>
                {transformResult.explanation && (
                  <div style={{ marginBottom: '12px', color: '#666', fontSize: '14px' }}>
                    <strong>Explanation:</strong> {transformResult.explanation}
                  </div>
                )}
                
                <div style={{ marginBottom: '8px', fontSize: '13px', color: '#666', fontWeight: '600' }}>
                  Generated Cypher Query:
                </div>
                <pre style={{
                  background: '#f5f5f5',
                  color: '#333',
                  padding: '12px',
                  borderRadius: '4px',
                  overflow: 'auto',
                  fontSize: '12px',
                  fontFamily: 'Monaco, Courier, monospace',
                  margin: 0,
                  border: '1px solid #e0e0e0',
                }}>
                  {transformResult.cypher}
                </pre>
                
                {transformResult.parameters && Object.keys(transformResult.parameters).length > 0 && (
                  <div style={{ marginTop: '12px' }}>
                    <div style={{ fontSize: '13px', color: '#666', marginBottom: '6px', fontWeight: '600' }}>
                      Parameters:
                    </div>
                    <pre style={{
                      background: '#f5f5f5',
                      color: '#333',
                      padding: '10px',
                      borderRadius: '4px',
                      fontSize: '11px',
                      fontFamily: 'Monaco, Courier, monospace',
                      margin: 0,
                      border: '1px solid #e0e0e0',
                    }}>
                      {JSON.stringify(transformResult.parameters, null, 2)}
                    </pre>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* Navigation Helper */}
      <div style={{
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        zIndex: 1000,
      }}>
        {/* Collapsed icon button */}
        {!showNavHelper && (
          <button
            onClick={() => setShowNavHelper(true)}
            style={{
              width: '48px',
              height: '48px',
              borderRadius: '50%',
              background: 'rgba(0,0,0,0.8)',
              border: '1px solid rgba(255,255,255,0.2)',
              color: 'white',
              cursor: 'pointer',
              fontSize: '20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
              transition: 'all 0.2s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'rgba(25,118,210,0.9)';
              e.currentTarget.style.transform = 'scale(1.1)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'rgba(0,0,0,0.8)';
              e.currentTarget.style.transform = 'scale(1)';
            }}
            title="Navigation Controls"
          >
            🧭
          </button>
        )}

        {/* Expanded navigation panel */}
        {showNavHelper && (
          <div style={{
            background: 'rgba(0,0,0,0.9)',
            borderRadius: '12px',
            padding: '16px',
            boxShadow: '0 4px 16px rgba(0,0,0,0.6)',
            border: '1px solid rgba(255,255,255,0.2)',
            minWidth: '180px',
          }}>
            {/* Header */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '12px',
              paddingBottom: '8px',
              borderBottom: '1px solid rgba(255,255,255,0.1)',
            }}>
              <span style={{ color: 'white', fontSize: '14px', fontWeight: '600' }}>
                🧭 Controls
              </span>
              <button
                onClick={() => setShowNavHelper(false)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#999',
                  cursor: 'pointer',
                  fontSize: '18px',
                  padding: '0',
                  width: '24px',
                  height: '24px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
                onMouseEnter={(e) => e.currentTarget.style.color = 'white'}
                onMouseLeave={(e) => e.currentTarget.style.color = '#999'}
              >
                ×
              </button>
            </div>

            {/* Navigation buttons - Icons only in one row */}
            <div style={{ display: 'flex', gap: '6px', marginBottom: '12px' }}>
              <button
                onClick={handleZoomOut}
                style={{
                  padding: '8px 12px',
                  background: 'rgba(255,255,255,0.1)',
                  color: 'white',
                  border: '1px solid rgba(255,255,255,0.2)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  flex: 1,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.2)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.1)';
                }}
                title="Zoom Out"
              >
                🔍−
              </button>

              <button
                onClick={handleZoomToFit}
                style={{
                  padding: '8px 12px',
                  background: 'rgba(25,118,210,0.3)',
                  color: 'white',
                  border: '1px solid rgba(25,118,210,0.6)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  flex: 1,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(25,118,210,0.5)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(25,118,210,0.3)';
                }}
                title="Zoom to Full Graph"
              >
                🌐
              </button>

              <button
                onClick={handleZoomToCluster}
                disabled={highlightNodes.size === 0}
                style={{
                  padding: '8px 12px',
                  background: highlightNodes.size > 0 ? 'rgba(244,67,54,0.3)' : 'rgba(100,100,100,0.2)',
                  color: highlightNodes.size > 0 ? 'white' : '#666',
                  border: `1px solid ${highlightNodes.size > 0 ? 'rgba(244,67,54,0.6)' : 'rgba(100,100,100,0.4)'}`,
                  borderRadius: '6px',
                  cursor: highlightNodes.size > 0 ? 'pointer' : 'not-allowed',
                  fontSize: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  flex: 1,
                }}
                onMouseEnter={(e) => {
                  if (highlightNodes.size > 0) {
                    e.currentTarget.style.background = 'rgba(244,67,54,0.5)';
                  }
                }}
                onMouseLeave={(e) => {
                  if (highlightNodes.size > 0) {
                    e.currentTarget.style.background = 'rgba(244,67,54,0.3)';
                  }
                }}
                title="Zoom to Cluster"
              >
                🎯
              </button>

              <button
                onClick={handleZoomIn}
                style={{
                  padding: '8px 12px',
                  background: 'rgba(255,255,255,0.1)',
                  color: 'white',
                  border: '1px solid rgba(255,255,255,0.2)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  flex: 1,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.2)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.1)';
                }}
                title="Zoom In"
              >
                🔍+
              </button>
            </div>

            {/* Size Controls - No title */}
            <div style={{
              paddingTop: '12px',
              borderTop: '1px solid rgba(255,255,255,0.1)',
            }}>
              
              {/* Node Size Slider */}
              <div style={{ marginBottom: '12px' }}>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: '6px',
                }}>
                  <span style={{ fontSize: '11px', color: '#ccc' }}>Nodes</span>
                  <span style={{ 
                    fontSize: '11px', 
                    color: '#4CAF50',
                    fontWeight: '600',
                  }}>
                    {nodeSize}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={nodeSize}
                  onChange={(e) => setNodeSize(parseInt(e.target.value))}
                  style={{
                    width: '100%',
                    cursor: 'pointer',
                  }}
                />
              </div>

              {/* Link Size Slider */}
              <div>
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: '6px',
                }}>
                  <span style={{ fontSize: '11px', color: '#ccc' }}>Links</span>
                  <span style={{ 
                    fontSize: '11px', 
                    color: '#4CAF50',
                    fontWeight: '600',
                  }}>
                    {linkSize}%
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={linkSize}
                  onChange={(e) => setLinkSize(parseInt(e.target.value))}
                  style={{
                    width: '100%',
                    cursor: 'pointer',
                  }}
                />
              </div>
            </div>

            {/* Keyboard shortcuts info */}
            <div style={{
              marginTop: '12px',
              paddingTop: '12px',
              borderTop: '1px solid rgba(255,255,255,0.1)',
            }}>
              <div style={{
                fontSize: '12px',
                color: '#999',
                marginBottom: '8px',
                fontWeight: '600',
              }}>
                ⌨️ Shortcuts
              </div>
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '6px',
                fontSize: '11px',
                color: '#ccc',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ opacity: 0.7 }}>Arrow Keys</span>
                  <span style={{ 
                    background: 'rgba(255,255,255,0.1)', 
                    padding: '2px 6px', 
                    borderRadius: '3px',
                    fontSize: '10px',
                  }}>
                    Pan/Rotate
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ opacity: 0.7 }}>+ / -</span>
                  <span style={{ 
                    background: 'rgba(255,255,255,0.1)', 
                    padding: '2px 6px', 
                    borderRadius: '3px',
                    fontSize: '10px',
                  }}>
                    Zoom
                  </span>
                </div>
              </div>
            </div>

            {/* Helper text */}
            {highlightNodes.size > 0 && (
              <div style={{
                marginTop: '12px',
                paddingTop: '8px',
                borderTop: '1px solid rgba(255,255,255,0.1)',
                fontSize: '11px',
                color: '#999',
                textAlign: 'center',
              }}>
                {highlightNodes.size} node{highlightNodes.size !== 1 ? 's' : ''} highlighted
              </div>
            )}
          </div>
        )}
      </div>

      {/* Loading Overlay */}
      {isLoading && (
        <div style={{
          position: 'fixed',
          bottom: '20px',
          left: '50%',
          transform: 'translateX(-50%)',
          background: 'rgba(0,0,0,0.9)',
          padding: '12px 24px',
          borderRadius: '6px',
          color: 'white',
          fontSize: '14px',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
        }}>
          <div style={{ 
            border: '2px solid rgba(255,255,255,0.3)',
            borderTop: '2px solid white',
            borderRadius: '50%',
            width: '16px',
            height: '16px',
            animation: 'spin 1s linear infinite',
          }} />
          Processing query...
        </div>
      )}
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <AppContent />
      </ErrorBoundary>
    </QueryClientProvider>
  );
}

// Simple Error Boundary Component
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Error caught by boundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px',
          background: '#1a1a1a',
          minHeight: '100vh',
          color: 'white',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
        }}>
          <h1 style={{ color: '#E74C3C' }}>⚠️ Something went wrong</h1>
          <p style={{ marginTop: '20px', maxWidth: '600px', textAlign: 'center' }}>
            {this.state.error?.message || 'An unknown error occurred'}
          </p>
          <pre style={{
            marginTop: '20px',
            padding: '20px',
            background: '#2C3E50',
            borderRadius: '8px',
            maxWidth: '800px',
            overflow: 'auto',
          }}>
            {this.state.error?.stack}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{
              marginTop: '30px',
              padding: '12px 24px',
              background: '#3498DB',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '16px',
            }}
          >
            Reload Page
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default App;
