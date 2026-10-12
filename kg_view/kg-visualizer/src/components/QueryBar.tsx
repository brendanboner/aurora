import React, { useState, useCallback, useEffect } from 'react';
import { graphApi } from '../services/api';
import type { QueryTransformResult } from '../types/graph';

interface QueryBarProps {
  onQueryExecute: (cypher: string, params: Record<string, any>) => void;
  onEntitiesExtracted: (entities: any[]) => void;
  onTransformResult: (result: QueryTransformResult | null, error: string | null) => void;
  isLoading: boolean;
}

const QueryBar: React.FC<QueryBarProps> = ({ onQueryExecute: _onQueryExecute, onEntitiesExtracted, onTransformResult, isLoading }) => {
  const [query, setQuery] = useState('');
  const [transformedResult, setTransformedResult] = useState<QueryTransformResult | null>(null);

  // Load recent queries from localStorage
  const [recentQueries, setRecentQueries] = useState<string[]>(() => {
    const saved = localStorage.getItem('recentQueries');
    return saved ? JSON.parse(saved) : [];
  });

  // Save to recent queries
  const saveToRecent = useCallback((q: string) => {
    const updated = [q, ...recentQueries.filter(item => item !== q)].slice(0, 10);
    setRecentQueries(updated);
    localStorage.setItem('recentQueries', JSON.stringify(updated));
  }, [recentQueries]);

  // Handle query submission
  const handleSubmit = useCallback(async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim() || isLoading) return;

    try {
      // Extract entities from the query
      const result = await graphApi.extractEntities(query);
      setTransformedResult({ 
        cypher: '', 
        parameters: {}, 
        entities: result,
        explanation: `Found ${result.length} entities to explore` 
      });
      onTransformResult({ 
        cypher: '', 
        parameters: {}, 
        entities: result,
        explanation: `Found ${result.length} entities: ${result.map(e => e.name).join(', ')}` 
      }, null);

      // Save to recent queries
      saveToRecent(query);

      // Pass entities to parent to trigger subgraph fetch
      if (result && result.length > 0) {
        onEntitiesExtracted(result);
      } else {
        onTransformResult(null, 'No entities found in query. Try mentioning specific people, organizations, or topics.');
      }
    } catch (err: any) {
      const errorMsg = err.message || 'Failed to extract entities';
      onTransformResult(null, errorMsg);
    }
  }, [query, isLoading, onEntitiesExtracted, onTransformResult, saveToRecent]);

  // Handle Enter key
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  // Clear transformation when query changes
  useEffect(() => {
    if (transformedResult) {
      setTransformedResult(null);
      onTransformResult(null, null);
    }
  }, [query]);

  return (
    <div style={{
      padding: '16px 20px',
      background: 'transparent',
    }}>
      <form onSubmit={handleSubmit}>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter entities to explore... (e.g., 'David Coleman from Extreme Networks', 'Wi-Fi 6 and IEEE')"
              disabled={isLoading}
              style={{
                width: '100%',
                padding: '12px 16px',
                fontSize: '15px',
                border: '1px solid #444',
                borderRadius: '6px',
                background: 'rgba(255,255,255,0.1)',
                color: 'white',
                outline: 'none',
                boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
              }}
              autoFocus
            />
            {recentQueries.length > 0 && query === '' && (
              <div style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                marginTop: '5px',
                background: 'white',
                borderRadius: '8px',
                boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
                maxHeight: '200px',
                overflowY: 'auto',
                zIndex: 1000,
              }}>
                <div style={{ padding: '10px', fontSize: '12px', color: '#666', fontWeight: 'bold' }}>
                  Recent Queries
                </div>
                {recentQueries.map((rq, idx) => (
                  <div
                    key={idx}
                    onClick={() => setQuery(rq)}
                    style={{
                      padding: '10px 20px',
                      cursor: 'pointer',
                      borderTop: '1px solid #eee',
                      fontSize: '14px',
                      transition: 'background 0.2s',
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.background = '#f5f5f5'}
                    onMouseLeave={(e) => e.currentTarget.style.background = 'white'}
                  >
                    {rq}
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            style={{
              padding: '12px 28px',
              fontSize: '15px',
              fontWeight: '500',
              background: isLoading ? '#9e9e9e' : '#1976d2',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: isLoading ? 'not-allowed' : 'pointer',
              transition: 'all 0.2s',
              boxShadow: '0 1px 3px rgba(0,0,0,0.12)',
            }}
          >
            {isLoading ? 'Searching...' : 'Search'}
          </button>
        </div>
      </form>
    </div>
  );
};

export default QueryBar;
