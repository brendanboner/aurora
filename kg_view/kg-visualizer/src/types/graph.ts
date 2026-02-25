export interface GraphNode {
  id: number | string;  // Support both number and string (Neo4j elementId format)
  label: string;
  name: string;
  properties: Record<string, any>;
  x?: number;
  y?: number;
  z?: number;
  vx?: number;
  vy?: number;
  vz?: number;
}

export interface GraphLink {
  source: number | string | GraphNode;  // Support elementId strings
  target: number | string | GraphNode;
  type: string;
  properties: Record<string, any>;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  total_returned?: number;
}

export interface GraphStats {
  nodes: Record<string, number>;
  relationships: number;
  relationship_types?: Record<string, number>;
  timestamp: string;
}

export interface Entity {
  type: 'topic' | 'organization' | 'person' | 'event';
  name: string;
  id: string;
  classification?: string;
  email?: string;
}

export interface AutocompleteItem {
  value: string;
  label: string;
  data: Entity;
}

export interface QueryTransformResult {
  cypher: string;
  parameters: Record<string, any>;
  entities: Entity[];
  explanation: string;
  error?: string;
}

export interface SearchResult {
  id: number | string;  // Support Neo4j elementId format
  label: string;
  name: string;
  properties: Record<string, any>;
}

export type RenderMode = 'precomputed' | 'hierarchical' | 'dynamic';

export interface VisualizerConfig {
  renderMode: RenderMode;
  showLabels: boolean;
  nodeSize: number;
  linkWidth: number;
  particleSize: number;
  enablePhysics: boolean;
}
