import React, { useState, useEffect, useMemo } from 'react';
import TopicTreeNode from './TopicTreeNode';
import './TopicTree.css';

const TopicTree = ({
  hierarchyData,
  selectedIds,
  onSelectionChange,
  isLoading,
  searchTerm = ''
}) => {
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState(searchTerm);
  
  // Debounce search term to avoid expensive filtering on every keystroke
  useEffect(() => {
    const timeout = setTimeout(() => {
      setDebouncedSearchTerm(searchTerm);
    }, 300);
    return () => clearTimeout(timeout);
  }, [searchTerm]);
  
  // Filter nodes based on DEBOUNCED search term - memoized to avoid recalculation
  const { filteredRoots, filteredNodes } = useMemo(() => {
    const roots = hierarchyData?.roots || [];
    const nodes = hierarchyData?.nodes || {};
    
    if (!hierarchyData || !hierarchyData.nodes || !hierarchyData.roots) {
      return { filteredRoots: [], filteredNodes: {}, matchingIds: new Set() };
    }
    
    if (!debouncedSearchTerm || debouncedSearchTerm.trim() === '') {
      return { filteredRoots: roots, filteredNodes: nodes, matchingIds: new Set() };
    }
    
    const search = debouncedSearchTerm.toLowerCase();
    const matchingIds = new Set();
    
    // Step 1: Find all topics that match the search
    Object.keys(nodes).forEach(topicId => {
      const topic = nodes[topicId];
      if (topic.name.toLowerCase().includes(search)) {
        matchingIds.add(topicId);
      }
    });
    
    // Step 2: Show ONLY matching topics as top-level nodes (no ancestors)
    // This keeps the tree simple and fast - matching topics appear as roots
    // Include all descendants so they can be expanded if user wants
    const filteredNodes = {};
    const addNodeAndDescendants = (topicId, visited = new Set()) => {
      if (visited.has(topicId) || visited.size > 1000) return; // Safety limit
      visited.add(topicId);
      
      const node = nodes[topicId];
      if (node) {
        filteredNodes[topicId] = { ...node };
        
        // Recursively add all children
        if (node.children && node.children.length > 0) {
          node.children.forEach(childId => {
            if (childId) addNodeAndDescendants(childId, visited);
          });
        }
      }
    };
    
    matchingIds.forEach(topicId => addNodeAndDescendants(topicId));
    
    // Use matching topics as the roots
    const filteredRoots = Array.from(matchingIds);
    
    return { filteredRoots, filteredNodes, matchingIds };
  }, [hierarchyData, debouncedSearchTerm]);
  
  // Clear expanded state when searching (keep everything collapsed)
  useEffect(() => {
    if (debouncedSearchTerm) {
      setExpandedIds(new Set());
    }
  }, [debouncedSearchTerm]);
  
  // Early returns AFTER all hooks
  if (isLoading) {
    return <div className="topic-tree-loading">Loading hierarchy...</div>;
  }
  
  if (!hierarchyData || !hierarchyData.nodes || !hierarchyData.roots) {
    return <div className="topic-tree-empty">No topics available</div>;
  }
  
  const nodes = hierarchyData.nodes;
  
  // Helper function to get all descendants of a topic
  const getAllDescendants = (topicId) => {
    const descendants = new Set();
    const queue = [topicId];
    
    while (queue.length > 0) {
      const currentId = queue.shift();
      const topic = nodes[currentId]; // Use original nodes, not filtered
      
      if (topic && topic.children) {
        topic.children.forEach(childId => {
          if (!descendants.has(childId)) {
            descendants.add(childId);
            queue.push(childId);
          }
        });
      }
    }
    
    return Array.from(descendants);
  };
  
  // Helper function to check if a topic should remain selected due to other parents
  const hasOtherSelectedParent = (topicId, excludeParentId) => {
    const topic = nodes[topicId];
    if (!topic || !topic.parents) return false;
    
    return topic.parents.some(parentId => 
      parentId !== excludeParentId && selectedIds.has(parentId)
    );
  };
  
  const handleToggleSelect = (topicId, shouldSelect) => {
    const newSelectedIds = new Set(selectedIds);
    
    if (shouldSelect) {
      // Select this topic and all descendants
      newSelectedIds.add(topicId);
      const descendants = getAllDescendants(topicId);
      descendants.forEach(id => newSelectedIds.add(id));
    } else {
      // Deselect this topic and descendants (unless kept by other parents)
      const toRemove = new Set([topicId]);
      const descendants = getAllDescendants(topicId);
      
      descendants.forEach(descId => {
        // Only mark for removal if no other selected parent wants it
        if (!hasOtherSelectedParent(descId, topicId)) {
          toRemove.add(descId);
        }
      });
      
      toRemove.forEach(id => newSelectedIds.delete(id));
    }
    
    onSelectionChange(newSelectedIds);
  };
  
  const handleToggleExpand = (topicId) => {
    const newExpandedIds = new Set(expandedIds);
    if (newExpandedIds.has(topicId)) {
      newExpandedIds.delete(topicId);
    } else {
      newExpandedIds.add(topicId);
    }
    setExpandedIds(newExpandedIds);
  };
  
  const handleCollapseAll = () => {
    setExpandedIds(new Set());
  };
  
  if (filteredRoots.length === 0) {
    return <div className="topic-tree-empty">
      {debouncedSearchTerm ? `No topics found matching "${debouncedSearchTerm}"` : 'No root topics found'}
    </div>;
  }
  
  const visibleTopicCount = Object.keys(filteredNodes).length;
  const isFiltering = searchTerm && searchTerm !== debouncedSearchTerm;
  
  return (
    <div className="topic-tree-container">
      <div className="topic-tree-controls">
        <button onClick={handleCollapseAll} className="tree-control-button">
          Collapse All
        </button>
        <span className="topic-tree-stats">
          {isFiltering && <span style={{ color: '#999' }}>Filtering... • </span>}
          {debouncedSearchTerm 
            ? `Showing ${visibleTopicCount} of ${hierarchyData.total_topics} topics`
            : `${hierarchyData.total_topics} total topics`
          } • {selectedIds.size} selected
        </span>
      </div>
      
      <div className="topic-tree">
        {filteredRoots.map((rootId) => {
          const rootNode = filteredNodes[rootId];
          if (!rootNode) return null;
          
          return (
            <TopicTreeNode
              key={rootId}
              node={rootNode}
              allNodes={nodes}
              filteredNodes={filteredNodes}
              selectedIds={selectedIds}
              expandedIds={expandedIds}
              onToggleSelect={handleToggleSelect}
              onToggleExpand={handleToggleExpand}
              level={0}
            />
          );
        })}
      </div>
    </div>
  );
};

export default TopicTree;
