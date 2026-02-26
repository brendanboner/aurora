import React from 'react';
import './FilterPanel.css';

interface FilterPanelProps {
  hiddenNodeTypes: Set<string>;
  onNodeTypeToggle: (nodeType: string) => void;
  importanceThreshold: number;
  onImportanceThresholdChange: (threshold: number) => void;
  curatedOnly: boolean;
  onCuratedOnlyChange: (curatedOnly: boolean) => void;
  onApplyFilters: () => void;
  isLoading: boolean;
}

const ALL_NODE_TYPES = ['Resource', 'Topic', 'Organization', 'Person', 'Event', 'DataSource', 'IngestionBatch'];

const FilterPanel: React.FC<FilterPanelProps> = ({
  hiddenNodeTypes,
  onNodeTypeToggle,
  importanceThreshold,
  onImportanceThresholdChange,
  curatedOnly,
  onCuratedOnlyChange,
  onApplyFilters,
  isLoading,
}) => {
  return (
    <div className="filter-panel">
      <div className="filter-section">
        <h3>Filter Options</h3>
        
        {/* Node Type Toggles */}
        <div className="filter-group">
          <h4>Node Types</h4>
          <div className="node-type-toggles">
            {ALL_NODE_TYPES.map((nodeType) => (
              <label key={nodeType} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={!hiddenNodeTypes.has(nodeType)}
                  onChange={() => onNodeTypeToggle(nodeType)}
                  disabled={isLoading}
                />
                <span>{nodeType}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Importance Threshold Slider */}
        <div className="filter-group">
          <h4>Importance Threshold</h4>
          <div className="slider-container">
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              value={importanceThreshold}
              onChange={(e) => onImportanceThresholdChange(parseFloat(e.target.value))}
              disabled={isLoading}
              className="slider"
            />
            <span className="slider-value">{(importanceThreshold * 100).toFixed(0)}%</span>
          </div>
          <p className="help-text">Shows only nodes with importance score above this threshold</p>
        </div>

        {/* Curated Only Toggle */}
        <div className="filter-group">
          <label className="checkbox-label curated-label">
            <input
              type="checkbox"
              checked={curatedOnly}
              onChange={(e) => onCuratedOnlyChange(e.target.checked)}
              disabled={isLoading}
            />
            <span>Curated Topics Only</span>
          </label>
          <p className="help-text">Show only top-level curated topics (tier 0-1) in searches</p>
        </div>

        {/* Apply Filters Button */}
        <button
          onClick={onApplyFilters}
          disabled={isLoading}
          className="apply-filters-btn"
        >
          {isLoading ? 'Loading...' : 'Apply Filters'}
        </button>

        {/* Info Box */}
        <div className="info-box">
          <p>
            <strong>Tip:</strong> Use these filters to focus on the most important nodes in the graph. 
            Higher importance thresholds reduce clutter, while curated-only mode limits topic search to 
            top-level categories.
          </p>
        </div>
      </div>
    </div>
  );
};

export default FilterPanel;
