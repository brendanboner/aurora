import React from 'react';
import './TopicTree.css';

const TopicTreeNode = ({
  node,
  allNodes,
  filteredNodes,
  selectedIds,
  expandedIds,
  onToggleSelect,
  onToggleExpand,
  level = 0
}) => {
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expandedIds.has(node.topic_id);
  const isSelected = selectedIds.has(node.topic_id);
  
  // Count ALL descendants from the original full hierarchy (not filtered)
  const countAllDescendants = (topicId) => {
    const topic = allNodes[topicId];
    if (!topic || !topic.children || topic.children.length === 0) return 0;
    
    let count = topic.children.length;
    for (const childId of topic.children) {
      count += countAllDescendants(childId);
    }
    return count;
  };
  
  const totalDescendants = countAllDescendants(node.topic_id);
  
  // Calculate selection state (checked, unchecked, or indeterminate)
  const getSelectionState = () => {
    if (isSelected) return 'checked';
    
    // Check if any descendants are selected
    if (hasChildren) {
      const hasSelectedDescendant = checkDescendantsSelected(node.topic_id);
      if (hasSelectedDescendant) return 'indeterminate';
    }
    
    return 'unchecked';
  };
  
  const checkDescendantsSelected = (topicId) => {
    const topic = allNodes[topicId];
    if (!topic || !topic.children) return false;
    
    for (const childId of topic.children) {
      if (selectedIds.has(childId)) return true;
      if (checkDescendantsSelected(childId)) return true;
    }
    return false;
  };
  
  const selectionState = getSelectionState();
  
  const handleExpandClick = (e) => {
    e.stopPropagation();
    if (hasChildren) {
      onToggleExpand(node.topic_id);
    }
  };
  
  const handleCheckboxChange = () => {
    // If indeterminate or unchecked, select. If checked, deselect.
    const shouldSelect = selectionState !== 'checked';
    onToggleSelect(node.topic_id, shouldSelect);
  };
  
  return (
    <div className="topic-tree-node" style={{ '--level': level }}>
      <div className="node-header">
        {/* Expand/collapse icon */}
        {hasChildren ? (
          <button 
            className={`expand-button ${isExpanded ? 'expanded' : ''}`}
            onClick={handleExpandClick}
            aria-label={isExpanded ? 'Collapse' : 'Expand'}
          >
            ▶
          </button>
        ) : (
          <span className="expand-spacer"></span>
        )}
        
        {/* Checkbox */}
        <input
          type="checkbox"
          checked={selectionState === 'checked'}
          ref={(input) => {
            if (input) {
              input.indeterminate = selectionState === 'indeterminate';
            }
          }}
          onChange={handleCheckboxChange}
          className="node-checkbox"
        />
        
        {/* Topic name and info */}
        <span className="node-content">
          <span className="node-name">{node.name}</span>
          {node.relationship_count > 0 && (
            <span className="preference-count">
              {node.relationship_count} {node.relationship_count === 1 ? 'connection' : 'connections'}
            </span>
          )}
          {totalDescendants > 0 && (
            <span className="children-count">
              ({totalDescendants} {totalDescendants === 1 ? 'subtopic' : 'subtopics'})
            </span>
          )}
        </span>
      </div>
      
      {/* Render children recursively if expanded */}
      {hasChildren && isExpanded && (
        <div className="node-children">
          {node.children.map((childId) => {
            // Use filteredNodes if available (for search), otherwise use allNodes
            const childNode = (filteredNodes && filteredNodes[childId]) || allNodes[childId];
            if (!childNode) return null;
            
            return (
              <TopicTreeNode
                key={childId}
                node={childNode}
                allNodes={allNodes}
                filteredNodes={filteredNodes}
                selectedIds={selectedIds}
                expandedIds={expandedIds}
                onToggleSelect={onToggleSelect}
                onToggleExpand={onToggleExpand}
                level={level + 1}
              />
            );
          })}
        </div>
      )}
    </div>
  );
};

export default TopicTreeNode;
