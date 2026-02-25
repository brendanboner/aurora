import React from 'react';
import type { GraphNode } from '../types/graph';

interface NodeDetailsProps {
  node: GraphNode | null;
  onClose: () => void;
  onToggle?: () => void;
  onExploreNeighborhood: (nodeId: number, hops: number) => void;
  onHopSelection?: (nodeId: number, hops: number) => void;
  currentHops?: number;
  isLoadingHops?: boolean;
}

const NodeDetails: React.FC<NodeDetailsProps> = ({ 
  node, 
  onClose, 
  onToggle, 
  onExploreNeighborhood: _onExploreNeighborhood,
  onHopSelection,
  currentHops = 0,
  isLoadingHops = false,
}) => {
  if (!node) return null;

  const properties = node.properties || {};
  
  // Format property values
  const formatValue = (value: any): string => {
    if (value === null || value === undefined) return 'N/A';
    if (Array.isArray(value)) return value.join(', ');
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (typeof value === 'number') return value.toLocaleString();
    return String(value);
  };

  // Determine what to display based on node type
  const getNodeTitle = () => {
    if (node.label === 'IngestionBatch') {
      return properties.batch_id || node.name;
    }
    if (node.label === 'DataSource') {
      return properties.name || properties.datasource_id || node.name;
    }
    return properties.title || properties.name || node.name;
  };

  const getKeyProperties = () => {
    if (node.label === 'IngestionBatch') {
      return [
        { label: 'Batch ID', value: properties.batch_id },
        { label: 'DataSource ID', value: properties.datasource_id },
        { label: 'Status', value: properties.status },
        { label: 'Items Scraped', value: properties.items_scraped },
        { label: 'Items Digested', value: properties.items_digested },
        { label: 'Resources', value: properties.resources_count },
        { label: 'Events', value: properties.events_count },
        { label: 'Scrape Started', value: properties.scrape_started_at },
        { label: 'Scrape Completed', value: properties.scrape_completed_at },
        { label: 'Digest Completed', value: properties.digest_completed_at },
        { label: 'Reconciled At', value: properties.reconciled_at },
        { label: 'Error', value: properties.error_message },
      ].filter(p => p.value !== null && p.value !== undefined);
    }

    if (node.label === 'DataSource') {
      return [
        { label: 'Name', value: properties.name },
        { label: 'Source Type', value: properties.source_type },
        { label: 'Fetch URL', value: properties.fetch_url },
        { label: 'Scraper Type', value: properties.scraper_type },
        { label: 'Resource URL', value: properties.resource_url },
        { label: 'Last Scraped', value: properties.last_scraped_at },
        { label: 'Has Events', value: properties.has_events },
        { label: 'Max Resources', value: properties.max_resources },
        { label: 'Schedule', value: properties.scrape_schedule },
        { label: 'Discovery Mode', value: properties.discovery_mode },
      ].filter(p => p.value !== null && p.value !== undefined);
    }

    // Default properties for other node types
    return [
      { label: 'Title', value: properties.title },
      { label: 'Name', value: properties.name },
      { label: 'Summary', value: properties.summary },
      { label: 'Description', value: properties.description },
      { label: 'URL', value: properties.url },
      { label: 'Email', value: properties.email },
      { label: 'Homepage', value: properties.homepage_url },
      { label: 'Importance', value: properties.importance ? `${(properties.importance * 100).toFixed(0)}%` : null },
      { label: 'Confidence', value: properties.confidence ? `${(properties.confidence * 100).toFixed(0)}%` : null },
      { label: 'Classification', value: properties.classification },
      { label: 'Category', value: properties.category },
      { label: 'Type', value: properties.org_type || properties.doc_type || properties.event_type },
      { label: 'Published', value: properties.publish_date },
      { label: 'Start Date', value: properties.start_date },
      { label: 'End Date', value: properties.end_date },
    ].filter(p => p.value !== null && p.value !== undefined && p.value !== '');
  };

  const keyProps = getKeyProperties();
  const nodeTitle = getNodeTitle();

  return (
    <div style={{
      position: 'fixed',
      bottom: '20px',
      left: '20px',
      width: '320px',
      maxHeight: 'calc(100vh - 80px)',
      background: 'rgba(0,0,0,0.95)',
      borderRadius: '8px',
      boxShadow: '0 4px 16px rgba(0,0,0,0.5)',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 100,
      border: '1px solid rgba(255,255,255,0.1)',
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 16px',
        background: 'rgba(25, 118, 210, 0.2)',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: '8px',
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: '10px',
            textTransform: 'uppercase',
            color: '#aaa',
            marginBottom: '4px',
            fontWeight: '600',
          }}>
            {node.label}
          </div>
          <div style={{
            fontSize: '14px',
            fontWeight: '600',
            color: 'white',
            wordBreak: 'break-word',
            lineHeight: '1.3',
          }}>
            {nodeTitle}
          </div>
        </div>
        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
          {onToggle && (
            <button
              onClick={onToggle}
              style={{
                background: 'rgba(255,255,255,0.1)',
                border: 'none',
                borderRadius: '4px',
                width: '28px',
                height: '28px',
                cursor: 'pointer',
                fontSize: '16px',
                color: 'white',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'background 0.2s',
              }}
              onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
              onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
            >
              _
            </button>
          )}
          <button
            onClick={onClose}
            style={{
              background: 'rgba(255,255,255,0.1)',
              border: 'none',
              borderRadius: '4px',
              width: '28px',
              height: '28px',
              cursor: 'pointer',
              fontSize: '18px',
              color: 'white',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background 0.2s',
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
          >
            ×
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '12px 16px',
      }}>
        {/* Properties */}
        {keyProps.length > 0 && (
          <div style={{ marginBottom: '12px' }}>
            {keyProps.map((prop, idx) => (
              <div key={idx} style={{
                marginBottom: '8px',
                paddingBottom: '8px',
                borderBottom: idx < keyProps.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
              }}>
                <div style={{
                  fontSize: '10px',
                  color: '#888',
                  marginBottom: '2px',
                  textTransform: 'uppercase',
                  fontWeight: '600',
                }}>
                  {prop.label}
                </div>
                <div style={{
                  fontSize: '12px',
                  color: '#ddd',
                  wordBreak: 'break-word',
                  lineHeight: '1.4',
                }}>
                  {formatValue(prop.value)}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Neighborhood Exploration */}
        {node.label !== 'IngestionBatch' && node.label !== 'DataSource' && (
          <div style={{
            marginTop: '12px',
            paddingTop: '12px',
            borderTop: '1px solid rgba(255,255,255,0.1)',
          }}>
            <div style={{
              fontSize: '11px',
              color: '#aaa',
              marginBottom: '8px',
              fontWeight: '600',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}>
              <span>EXPLORE CONNECTIONS</span>
              {isLoadingHops && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '10px',
                  color: '#64b5f6',
                }}>
                  <div style={{
                    width: '10px',
                    height: '10px',
                    border: '2px solid rgba(100, 181, 246, 0.3)',
                    borderTop: '2px solid #64b5f6',
                    borderRadius: '50%',
                    animation: 'spin 0.8s linear infinite',
                  }} />
                  <span>Loading...</span>
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: '6px' }}>
              {onHopSelection && (
                <>
                  <button
                    onClick={() => onHopSelection(node.id, 0)}
                    disabled={isLoadingHops}
                    style={{
                      flex: 1,
                      padding: '8px',
                      background: currentHops === 0 ? 'rgba(156, 39, 176, 0.3)' : 'rgba(100, 100, 100, 0.2)',
                      color: currentHops === 0 ? '#ce93d8' : '#999',
                      border: `1px solid ${currentHops === 0 ? 'rgba(206, 147, 216, 0.5)' : 'rgba(100, 100, 100, 0.3)'}`,
                      borderRadius: '4px',
                      cursor: isLoadingHops ? 'wait' : 'pointer',
                      fontSize: '11px',
                      fontWeight: currentHops === 0 ? '600' : '500',
                      transition: 'all 0.2s',
                      opacity: isLoadingHops ? 0.5 : 1,
                    }}
                  >
                    None
                  </button>
                  <button
                    onClick={() => onHopSelection(node.id, 1)}
                    disabled={isLoadingHops}
                    style={{
                      flex: 1,
                      padding: '8px',
                      background: currentHops === 1 ? 'rgba(25, 118, 210, 0.4)' : 'rgba(25, 118, 210, 0.2)',
                      color: currentHops === 1 ? '#ffffff' : '#64b5f6',
                      border: `1px solid ${currentHops === 1 ? 'rgba(100, 181, 246, 0.8)' : 'rgba(100, 181, 246, 0.3)'}`,
                      borderRadius: '4px',
                      cursor: isLoadingHops ? 'wait' : 'pointer',
                      fontSize: '11px',
                      fontWeight: currentHops === 1 ? '600' : '500',
                      transition: 'all 0.2s',
                      opacity: isLoadingHops ? 0.5 : 1,
                    }}
                  >
                    1-Hop
                  </button>
                  <button
                    onClick={() => onHopSelection(node.id, 2)}
                    disabled={isLoadingHops}
                    style={{
                      flex: 1,
                      padding: '8px',
                      background: currentHops === 2 ? 'rgba(25, 118, 210, 0.4)' : 'rgba(25, 118, 210, 0.2)',
                      color: currentHops === 2 ? '#ffffff' : '#64b5f6',
                      border: `1px solid ${currentHops === 2 ? 'rgba(100, 181, 246, 0.8)' : 'rgba(100, 181, 246, 0.3)'}`,
                      borderRadius: '4px',
                      cursor: isLoadingHops ? 'wait' : 'pointer',
                      fontSize: '11px',
                      fontWeight: currentHops === 2 ? '600' : '500',
                      transition: 'all 0.2s',
                      opacity: isLoadingHops ? 0.5 : 1,
                    }}
                  >
                    2-Hop
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default NodeDetails;
