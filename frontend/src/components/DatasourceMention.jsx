import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import './DatasourceMention.css';

/**
 * DatasourceMention — @mention autocomplete for chat input.
 *
 * Groups sources by family:
 *   - WBA Extranet programmes/workgroups (with parent hierarchy)
 *   - IETF working groups (collapsed under "IETF")
 *   - WFA, IEEE, public sources (grouped by prefix)
 *
 * Keyboard: ArrowUp/Down navigate, Tab/Enter select, Escape close.
 */

const GROUP_ORDER = ['wba_extranet', 'wfa', 'ietf', 'ieee', 'public', 'other'];
const GROUP_LABELS = {
  wba_extranet: 'WBA Extranet',
  wfa: 'Wi-Fi Alliance',
  ietf: 'IETF',
  ieee: 'IEEE',
  public: 'Public Sources',
  other: 'Other',
};

function classifySource(ds) {
  const id = (ds.datasource_id || '').toLowerCase();
  if (id.startsWith('wba_extranet')) return 'wba_extranet';
  if (id.startsWith('wfa')) return 'wfa';
  if (id.startsWith('ietf')) return 'ietf';
  if (id.startsWith('ieee')) return 'ieee';
  if (['mef', 'nist', 'onf', 'dmtf', 'wba_', 'youtube'].some(p => id.startsWith(p))) return 'public';
  return 'other';
}

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

  // Flat filtered list for keyboard navigation — also searches aliases
  const filteredDatasources = useMemo(() => {
    const search = searchText.toLowerCase();
    return datasources.filter(ds => {
      if (!search) return true;
      if (ds.datasource_id.toLowerCase().includes(search)) return true;
      if (ds.name.toLowerCase().includes(search)) return true;
      if (ds.description && ds.description.toLowerCase().includes(search)) return true;
      // Also match on any alias (e.g. @wba-qos, @wba-l4s)
      if (ds.primary_alias && ds.primary_alias.toLowerCase().includes(search)) return true;
      if (ds.aliases && ds.aliases.some(a => a.toLowerCase().includes(search))) return true;
      return false;
    });
  }, [datasources, searchText]);

  // Grouped structure for display
  const grouped = useMemo(() => {
    const groups = {};
    for (const ds of filteredDatasources) {
      const g = classifySource(ds);
      if (!groups[g]) groups[g] = [];
      groups[g].push(ds);
    }
    // Sort WBA Extranet: parents first, then children indented
    if (groups.wba_extranet) {
      const parents = groups.wba_extranet.filter(ds => !ds.parent_datasource_id || ds.parent_datasource_id === 'wba_extranet');
      const children = groups.wba_extranet.filter(ds => ds.parent_datasource_id && ds.parent_datasource_id !== 'wba_extranet');
      const sorted = [];
      for (const p of parents) {
        sorted.push({ ...p, _indent: false });
        for (const c of children.filter(c => c.parent_datasource_id === p.datasource_id)) {
          sorted.push({ ...c, _indent: true });
        }
      }
      // Add any children whose parent wasn't in list
      for (const c of children.filter(c => !parents.find(p => p.datasource_id === c.parent_datasource_id))) {
        sorted.push({ ...c, _indent: true });
      }
      groups.wba_extranet = sorted;
    }
    return groups;
  }, [filteredDatasources]);

  // Build flat ordered list matching visual order (for keyboard nav)
  const orderedFlat = useMemo(() => {
    const flat = [];
    for (const gKey of GROUP_ORDER) {
      for (const ds of (grouped[gKey] || [])) flat.push(ds);
    }
    return flat;
  }, [grouped]);

  useEffect(() => { setSelectedIndex(0); }, [searchText, datasources]);

  useEffect(() => {
    if (itemRefs.current[selectedIndex]) {
      itemRefs.current[selectedIndex].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selectedIndex]);

  const handleKeyDown = useCallback((e) => {
    if (!isVisible || orderedFlat.length === 0) return;
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(prev => prev < orderedFlat.length - 1 ? prev + 1 : 0);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(prev => prev > 0 ? prev - 1 : orderedFlat.length - 1);
        break;
      case 'Tab':
      case 'Enter':
        e.preventDefault();
        if (orderedFlat[selectedIndex]) onSelect(orderedFlat[selectedIndex]);
        break;
      case 'Escape':
        e.preventDefault();
        onClose();
        break;
      default:
        break;
    }
  }, [isVisible, orderedFlat, selectedIndex, onSelect, onClose]);

  useEffect(() => {
    const input = inputRef?.current;
    if (input && isVisible) {
      input.addEventListener('keydown', handleKeyDown);
      return () => input.removeEventListener('keydown', handleKeyDown);
    }
  }, [inputRef, isVisible, handleKeyDown]);

  useEffect(() => {
    if (!isVisible) return;
    const handleClickOutside = (e) => {
      if (listRef.current && !listRef.current.contains(e.target) &&
          inputRef?.current && !inputRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isVisible, onClose, inputRef]);

  if (!isVisible || orderedFlat.length === 0) return null;

  let flatIdx = 0;

  return (
    <div className="datasource-mention-dropdown" ref={listRef}>
      <div className="mention-header">
        <span className="mention-icon">@</span>
        <span>Filter by source</span>
        <span className="mention-count-total">{orderedFlat.length}</span>
      </div>
      <ul className="mention-list">
        {GROUP_ORDER.map(gKey => {
          const items = grouped[gKey];
          if (!items || items.length === 0) return null;
          return (
            <React.Fragment key={gKey}>
              <li className="mention-group-label">{GROUP_LABELS[gKey]}</li>
              {items.map((ds) => {
                const idx = flatIdx++;
                const isSelected = idx === selectedIndex;
                return (
                  <li
                    key={ds.datasource_id}
                    ref={el => { itemRefs.current[idx] = el; }}
                    className={`mention-item ${isSelected ? 'selected' : ''} ${ds._indent ? 'indented' : ''}`}
                    onClick={() => onSelect(ds)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                  >
                    <div className="mention-item-content">
                      <span className="mention-name">{ds.name}</span>
                      <span className="mention-id">@{ds.primary_alias || ds.datasource_id}</span>
                    </div>
                    {ds.document_count > 0 && (
                      <span className="mention-doc-count">{ds.document_count}</span>
                    )}
                  </li>
                );
              })}
            </React.Fragment>
          );
        })}
      </ul>
      <div className="mention-footer">
        <span>↑↓ navigate</span>
        <span>Tab/Enter select</span>
        <span>Esc close</span>
      </div>
    </div>
  );
};

export default DatasourceMention;
