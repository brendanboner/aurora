import React, { useState, useCallback, useEffect, useRef } from 'react';
import { graphApi } from '../services/api';
import type { AutocompleteItem, Entity } from '../types/graph';

interface TopicSelectorProps {
  selectedEntities: Entity[];
  onEntityAdd: (entity: Entity) => void;
  onEntityRemove: (entity: Entity) => void;
  onEntityClick: (entity: Entity) => void;
  onHighlight: (entityIds: string[]) => void;
  onEntityMouseDown?: (entity: Entity) => void;
  onEntityMouseUp?: (entity: Entity) => void; // Pass entity to mouse up
}

const TopicSelector: React.FC<TopicSelectorProps> = ({
  selectedEntities,
  onEntityAdd,
  onEntityRemove,
  onEntityClick,
  onHighlight: _onHighlight,
  onEntityMouseDown,
  onEntityMouseUp,
}) => {
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState<AutocompleteItem[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceTimer = useRef<number | undefined>(undefined);

  // Load cached entities from localStorage
  useEffect(() => {
    const cached = localStorage.getItem('cachedEntities');
    if (cached) {
      try {
        const entities = JSON.parse(cached);
        // Pre-populate suggestions with cached items
        setSuggestions(entities.slice(0, 20));
      } catch (e) {
        console.error('Failed to load cached entities', e);
      }
    }
  }, []);

  // Save selected entities to cache
  useEffect(() => {
    if (selectedEntities.length > 0) {
      const cached = localStorage.getItem('cachedEntities');
      const existing = cached ? JSON.parse(cached) : [];
      
      const updated = [
        ...selectedEntities.map(e => ({
          value: `${e.type}:${e.name}`,
          label: `${e.type}: ${e.name}`,
          data: e,
        })),
        ...existing.filter((item: AutocompleteItem) => 
          !selectedEntities.find(e => e.id === item.data.id)
        ),
      ].slice(0, 100);
      
      localStorage.setItem('cachedEntities', JSON.stringify(updated));
    }
  }, [selectedEntities]);

  // Fetch suggestions with debounce
  const fetchSuggestions = useCallback(async (searchText: string) => {
    if (!searchText.trim()) {
      setSuggestions([]);
      return;
    }

    setIsLoading(true);
    try {
      const results = await graphApi.autocompleteAll(searchText, 50);
      setSuggestions(results);
      setShowSuggestions(true);
    } catch (error) {
      console.error('Failed to fetch suggestions:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Handle input change with debounce
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setInput(value);
    setActiveSuggestionIndex(0);

    // Debounce API calls
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    debounceTimer.current = window.setTimeout(() => {
      fetchSuggestions(value);
    }, 300);
  }, [fetchSuggestions]);

  // Handle entity selection
  const selectEntity = useCallback((item: AutocompleteItem) => {
    onEntityAdd(item.data);
    setInput('');
    setSuggestions([]);
    setShowSuggestions(false);
    setShowSuggestions(false);
    inputRef.current?.focus();
  }, [onEntityAdd]);

  // Handle keyboard navigation
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (showSuggestions && suggestions.length > 0) {
        selectEntity(suggestions[activeSuggestionIndex]);
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveSuggestionIndex(prev => 
        prev < suggestions.length - 1 ? prev + 1 : prev
      );
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveSuggestionIndex(prev => prev > 0 ? prev - 1 : 0);
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
    }
  }, [showSuggestions, suggestions, activeSuggestionIndex, selectEntity]);

  // Handle entity removal
  const handleRemove = useCallback((entity: Entity) => {
    onEntityRemove(entity);
  }, [onEntityRemove]);

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = () => {
      setShowSuggestions(false);
    };

    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, []);

  return (
    <div style={{
      padding: '12px 20px',
      background: 'transparent',
    }} onClick={() => setShowSuggestions(false)}>
      {/* Selected entities */}
      {selectedEntities.length > 0 && (
        <div style={{
          marginBottom: '15px',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '8px',
        }}>
          {selectedEntities.map((entity) => (
            <div
              key={entity.id}
              onMouseDown={(e) => {
                // Mouse down: show neighborhood highlight
                if ((e.target as HTMLElement).tagName !== 'BUTTON' && onEntityMouseDown) {
                  onEntityMouseDown(entity);
                }
              }}
              onMouseUp={() => {
                // Mouse up: center with zoom and keep highlights
                if (onEntityMouseUp) {
                  onEntityMouseUp(entity);
                }
              }}
              onMouseLeave={() => {
                // Also trigger on mouse leave
                if (onEntityMouseUp) {
                  onEntityMouseUp(entity);
                }
              }}
              onClick={(e) => {
                // Click: center camera on entity
                if ((e.target as HTMLElement).tagName !== 'BUTTON') {
                  onEntityClick(entity);
                }
              }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '8px 12px',
                background: 'rgba(255,255,255,0.15)',
                borderRadius: '20px',
                fontSize: '14px',
                boxShadow: '0 2px 4px rgba(0,0,0,0.3)',
                transition: 'all 0.2s',
                cursor: 'pointer',
                border: '1px solid rgba(255,255,255,0.2)',
              }}
            >
              <span style={{
                fontSize: '10px',
                textTransform: 'uppercase',
                fontWeight: 'bold',
                color: entity.type === 'topic' ? '#ce93d8' :
                       entity.type === 'organization' ? '#81c784' :
                       entity.type === 'person' ? '#ef5350' : '#bdbdbd',
              }}>
                {entity.type}
              </span>
              <span style={{ color: 'white' }}>{entity.name}</span>
              <button
                onClick={() => handleRemove(entity)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: '16px',
                  color: '#E74C3C',
                  padding: 0,
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input field */}
      <div style={{ position: 'relative' }} onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => input && setShowSuggestions(true)}
          placeholder="Search entities by name or use prefixes (topic:, organization:, person:)..."
          style={{
            width: '100%',
            padding: '10px 16px',
            fontSize: '14px',
            border: '1px solid #444',
            borderRadius: '6px',
            outline: 'none',
            background: 'rgba(255,255,255,0.1)',
            color: 'white',
          }}
        />

        {/* Loading indicator */}
        {isLoading && (
          <div style={{
            position: 'absolute',
            right: '20px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: '#7F8C8D',
          }}>
            Loading...
          </div>
        )}

        {/* Suggestions dropdown */}
        {showSuggestions && suggestions.length > 0 && (
          <div style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: '5px',
            background: 'white',
            borderRadius: '8px',
            boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
            maxHeight: '300px',
            overflowY: 'auto',
            zIndex: 1000,
          }}>
            {suggestions.map((suggestion, idx) => (
              <div
                key={`${suggestion.data.type}-${suggestion.data.id}`}
                onClick={(e) => {
                  e.stopPropagation();
                  selectEntity(suggestion);
                }}
                style={{
                  padding: '12px 20px',
                  cursor: 'pointer',
                  borderTop: idx > 0 ? '1px solid #eee' : 'none',
                  background: idx === activeSuggestionIndex ? '#f5f5f5' : 'white',
                  transition: 'background 0.2s',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                }}
                onMouseEnter={() => setActiveSuggestionIndex(idx)}
              >
                <span style={{
                  fontSize: '10px',
                  textTransform: 'uppercase',
                  fontWeight: 'bold',
                  color: suggestion.data.type === 'topic' ? '#9B59B6' :
                         suggestion.data.type === 'organization' ? '#2ECC71' :
                         suggestion.data.type === 'person' ? '#E74C3C' : '#95A5A6',
                  minWidth: '80px',
                }}>
                  {suggestion.data.type}
                </span>
                <span style={{ flex: 1, color: '#2C3E50' }}>
                  {suggestion.data.name}
                </span>
                {suggestion.data.classification && (
                  <span style={{ fontSize: '12px', color: '#7F8C8D' }}>
                    {suggestion.data.classification}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Hint text */}
      <div style={{
        marginTop: '8px',
        fontSize: '11px',
        color: '#aaa',
      }}>
        💡 Press Enter to select. Select multiple entities to see connections.
      </div>
    </div>
  );
};

export default TopicSelector;
