import React, { useState, useEffect, useRef, useCallback } from 'react';
import './DatasourceMention.css';

/**
 * DatasourceMention - Autocomplete dropdown for @mentions in chat input
 * 
 * Features:
 * - Shows when user types @ in the input
 * - Filters datasources as user types
 * - Keyboard navigation (up/down arrows, Tab/Enter to select, Escape to close)
 * - Mouse selection support
 * - Positioned relative to cursor/input
 */
const DatasourceMention = ({
  datasources = [],
  searchText = '',
  onSelect,
  onClose,
  isVisible = false,
  inputRef,
}) => {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const listRef = useRef(null);
  const itemRefs = useRef({});

  // Filter datasources based on search text (text after @)
  const filteredDatasources = datasources.filter(ds => {
    const search = searchText.toLowerCase();
    return (
      ds.datasource_id.toLowerCase().includes(search) ||
      ds.name.toLowerCase().includes(search) ||
      (ds.description && ds.description.toLowerCase().includes(search))
    );
  });

  // Reset selection when filtered list changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [searchText, datasources]);

  // Scroll selected item into view
  useEffect(() => {
    if (itemRefs.current[selectedIndex]) {
      itemRefs.current[selectedIndex].scrollIntoView({
        block: 'nearest',
        behavior: 'smooth',
      });
    }
  }, [selectedIndex]);

  // Handle keyboard navigation
  const handleKeyDown = useCallback((e) => {
    if (!isVisible || filteredDatasources.length === 0) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(prev => 
          prev < filteredDatasources.length - 1 ? prev + 1 : 0
        );
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(prev => 
          prev > 0 ? prev - 1 : filteredDatasources.length - 1
        );
        break;
      case 'Tab':
      case 'Enter':
        e.preventDefault();
        if (filteredDatasources[selectedIndex]) {
          onSelect(filteredDatasources[selectedIndex]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        onClose();
        break;
      default:
        break;
    }
  }, [isVisible, filteredDatasources, selectedIndex, onSelect, onClose]);

  // Attach keyboard listener to input
  useEffect(() => {
    const input = inputRef?.current;
    if (input && isVisible) {
      input.addEventListener('keydown', handleKeyDown);
      return () => input.removeEventListener('keydown', handleKeyDown);
    }
  }, [inputRef, isVisible, handleKeyDown]);

  // Click outside to close
  useEffect(() => {
    if (!isVisible) return;
    
    const handleClickOutside = (event) => {
      const dropdown = listRef.current;
      const input = inputRef?.current;
      
      // Close if click is outside both dropdown and input
      if (dropdown && !dropdown.contains(event.target) && 
          input && !input.contains(event.target)) {
        onClose();
      }
    };
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isVisible, onClose, inputRef]);

  if (!isVisible || filteredDatasources.length === 0) {
    return null;
  }

  return (
    <div className="datasource-mention-dropdown" ref={listRef}>
      <div className="mention-header">
        <span className="mention-icon">@</span>
        <span>Select a datasource</span>
      </div>
      <ul className="mention-list">
        {filteredDatasources.map((ds, index) => (
          <li
            key={ds.datasource_id}
            ref={el => itemRefs.current[index] = el}
            className={`mention-item ${index === selectedIndex ? 'selected' : ''}`}
            onClick={() => onSelect(ds)}
            onMouseEnter={() => setSelectedIndex(index)}
          >
            <div className="mention-item-content">
              <span className="mention-id">@{ds.datasource_id}</span>
              <span className="mention-name">{ds.name}</span>
            </div>
            {ds.document_count > 0 && (
              <span className="mention-count">{ds.document_count} docs</span>
            )}
          </li>
        ))}
      </ul>
      <div className="mention-footer">
        <span>↑↓ Navigate</span>
        <span>Tab/Enter Select</span>
        <span>Esc Close</span>
      </div>
    </div>
  );
};

export default DatasourceMention;
