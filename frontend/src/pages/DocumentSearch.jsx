import React, { useState, useEffect, useCallback, useRef } from 'react';
import './DocumentSearch.css';
import { useAuth } from '../contexts/AuthContext';
import { 
  SearchIcon, 
  RefreshIcon, 
  CalendarIcon, 
  BookIcon, 
  BuildingIcon,
  LinkIcon,
  PlusIcon,
  TrashIcon
} from '../components/icons';
import { 
  getDatasources, 
  getFilterOptions,
  searchDocuments,
  getDocumentCount
} from '../services/api';

const DocumentSearch = () => {
  const { user } = useAuth();
  
  // Ref to prevent infinite loop when updating filter options
  const isUpdatingFilters = useRef(false);
  
  // Helper function to compare arrays
  const arraysEqual = (a, b) => {
    if (a.length !== b.length) return false;
    const sortedA = [...a].sort();
    const sortedB = [...b].sort();
    return sortedA.every((val, index) => val === sortedB[index]);
  };
  
  // Filter options (loaded from APIs)
  const [datasources, setDatasources] = useState([]);
  const [categories, setCategories] = useState([]);
  const [topics, setTopics] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  
  // Selected filters
  const [keywords, setKeywords] = useState([]);
  const [keywordInput, setKeywordInput] = useState('');
  const [keywordMatchMode, setKeywordMatchMode] = useState('any');
  const [selectedDatasources, setSelectedDatasources] = useState([]);
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [selectedTopics, setSelectedTopics] = useState([]);
  const [selectedOrganizations, setSelectedOrganizations] = useState([]);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [sortBy, setSortBy] = useState('publish_date');
  const [sortOrder, setSortOrder] = useState('desc');
  
  // Results and pagination
  const [results, setResults] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(25);
  
  // Document count for search button
  const [documentCount, setDocumentCount] = useState(null);
  const [isLoadingCount, setIsLoadingCount] = useState(false);
  
  // UI state
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingFilters, setIsLoadingFilters] = useState(true);
  const [isLoadingFilterOptions, setIsLoadingFilterOptions] = useState(false);
  const [error, setError] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);

  // Load initial filter options on mount
  useEffect(() => {
    const loadInitialOptions = async () => {
      setIsLoadingFilters(true);
      try {
        // Load all filter options with no filters applied
        const optionsResponse = await getFilterOptions({});
        setDatasources(optionsResponse.datasources || []);
        setCategories(optionsResponse.categories || []);
        setTopics(optionsResponse.topics || []);
        setOrganizations(optionsResponse.organizations || []);
      } catch (err) {
        console.error('Failed to load filter options:', err);
        setError('Failed to load filter options');
      } finally {
        setIsLoadingFilters(false);
      }
    };
    
    loadInitialOptions();
  }, []);

  // Reload filter options when ANY filter selection changes (bidirectional filtering)
  useEffect(() => {
    const loadFilteredOptions = async () => {
      // Skip if initial load hasn't completed
      if (isLoadingFilters) return;
      
      // Skip if already updating to prevent infinite loop
      if (isUpdatingFilters.current) return;
      
      // Skip if no filters are selected
      const hasFilters = selectedDatasources.length > 0 || 
                        selectedCategories.length > 0 || 
                        selectedTopics.length > 0 || 
                        selectedOrganizations.length > 0;
      
      if (!hasFilters) {
        // If all filters are cleared, reload all options
        setIsLoadingFilterOptions(true);
        try {
          const optionsResponse = await getFilterOptions({});
          setDatasources(optionsResponse.datasources || []);
          setCategories(optionsResponse.categories || []);
          setTopics(optionsResponse.topics || []);
          setOrganizations(optionsResponse.organizations || []);
        } catch (err) {
          console.error('Failed to load filter options:', err);
        } finally {
          setIsLoadingFilterOptions(false);
        }
        return;
      }
      
      isUpdatingFilters.current = true;
      setIsLoadingFilterOptions(true);
      try {
        const filters = {
          datasourceIds: selectedDatasources.length > 0 ? selectedDatasources : null,
          categories: selectedCategories.length > 0 ? selectedCategories : null,
          topicIds: selectedTopics.length > 0 ? selectedTopics : null,
          organizationIds: selectedOrganizations.length > 0 ? selectedOrganizations : null,
        };
        
        const optionsResponse = await getFilterOptions(filters);
        
        // Update all filter options based on the current selection
        setDatasources(optionsResponse.datasources || []);
        setCategories(optionsResponse.categories || []);
        setTopics(optionsResponse.topics || []);
        setOrganizations(optionsResponse.organizations || []);
        
        // Clear any selections that are no longer valid
        const validDatasourceIds = new Set((optionsResponse.datasources || []).map(ds => ds.datasource_id));
        const validCategoryIds = new Set((optionsResponse.categories || []).map(c => c.category_id));
        const validTopicIds = new Set((optionsResponse.topics || []).map(t => t.topic_id));
        const validOrgIds = new Set((optionsResponse.organizations || []).map(o => o.org_id));
        
        // Only update selections if they actually changed (to prevent infinite loop)
        const newDatasources = selectedDatasources.filter(id => validDatasourceIds.has(id));
        const newCategories = selectedCategories.filter(id => validCategoryIds.has(id));
        const newTopics = selectedTopics.filter(id => validTopicIds.has(id));
        const newOrgs = selectedOrganizations.filter(id => validOrgIds.has(id));
        
        if (!arraysEqual(newDatasources, selectedDatasources)) {
          setSelectedDatasources(newDatasources);
        }
        if (!arraysEqual(newCategories, selectedCategories)) {
          setSelectedCategories(newCategories);
        }
        if (!arraysEqual(newTopics, selectedTopics)) {
          setSelectedTopics(newTopics);
        }
        if (!arraysEqual(newOrgs, selectedOrganizations)) {
          setSelectedOrganizations(newOrgs);
        }
      } catch (err) {
        console.error('Failed to load filtered options:', err);
      } finally {
        setIsLoadingFilterOptions(false);
        // Reset the flag after a short delay to allow state updates to complete
        setTimeout(() => {
          isUpdatingFilters.current = false;
        }, 100);
      }
    };
    
    loadFilteredOptions();
  }, [selectedDatasources, selectedCategories, selectedTopics, selectedOrganizations, isLoadingFilters]);

  // Fetch document count when filters change
  useEffect(() => {
    const fetchDocumentCount = async () => {
      // Skip if initial load hasn't completed
      if (isLoadingFilters) return;
      
      setIsLoadingCount(true);
      try {
        const filters = {
          keywords: keywords.length > 0 ? keywords : null,
          keywordMatchMode,
          datasourceIds: selectedDatasources.length > 0 ? selectedDatasources : null,
          categories: selectedCategories.length > 0 ? selectedCategories : null,
          topicIds: selectedTopics.length > 0 ? selectedTopics : null,
          organizationIds: selectedOrganizations.length > 0 ? selectedOrganizations : null,
          dateFrom: dateFrom || null,
          dateTo: dateTo || null,
        };
        
        const response = await getDocumentCount(filters);
        setDocumentCount(response.count);
      } catch (err) {
        console.error('Failed to fetch document count:', err);
        setDocumentCount(null);
      } finally {
        setIsLoadingCount(false);
      }
    };
    
    fetchDocumentCount();
  }, [keywords, keywordMatchMode, selectedDatasources, selectedCategories, 
      selectedTopics, selectedOrganizations, dateFrom, dateTo, isLoadingFilters]);

  // Add keyword
  const addKeyword = () => {
    const trimmed = keywordInput.trim();
    if (trimmed && !keywords.includes(trimmed)) {
      setKeywords([...keywords, trimmed]);
      setKeywordInput('');
    }
  };

  const handleKeywordKeyPress = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addKeyword();
    }
  };

  const removeKeyword = (keyword) => {
    setKeywords(keywords.filter(k => k !== keyword));
  };

  // Multi-select handlers
  const handleMultiSelect = (e, setter, current) => {
    const value = e.target.value;
    if (value && !current.includes(value)) {
      setter([...current, value]);
    }
    e.target.value = ''; // Reset select
  };

  const removeFromSelection = (item, setter, current) => {
    setter(current.filter(i => i !== item));
  };

  // Search
  const handleSearch = useCallback(async (page = 1) => {
    setIsLoading(true);
    setError(null);
    setHasSearched(true);
    
    try {
      const filters = {
        keywords: keywords.length > 0 ? keywords : null,
        keywordMatchMode,
        datasourceIds: selectedDatasources.length > 0 ? selectedDatasources : null,
        categories: selectedCategories.length > 0 ? selectedCategories : null,
        topicIds: selectedTopics.length > 0 ? selectedTopics : null,
        organizationIds: selectedOrganizations.length > 0 ? selectedOrganizations : null,
        dateFrom: dateFrom || null,
        dateTo: dateTo || null,
        sortBy,
        sortOrder,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      };
      
      const response = await searchDocuments(filters);
      setResults(response.documents || []);
      setTotalCount(response.total_count || 0);
      setCurrentPage(page);
    } catch (err) {
      console.error('Search failed:', err);
      setError('Search failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [keywords, keywordMatchMode, selectedDatasources, selectedCategories, 
      selectedTopics, selectedOrganizations, dateFrom, dateTo, sortBy, sortOrder, pageSize]);

  // Clear all filters
  const clearFilters = () => {
    setKeywords([]);
    setKeywordInput('');
    setKeywordMatchMode('any');
    setSelectedDatasources([]);
    setSelectedCategories([]);
    setSelectedTopics([]);
    setSelectedOrganizations([]);
    setDateFrom('');
    setDateTo('');
    setSortBy('publish_date');
    setSortOrder('desc');
    setResults([]);
    setTotalCount(0);
    setHasSearched(false);
  };

  // Format date for display
  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown';
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric' 
      });
    } catch {
      return dateString;
    }
  };

  // Get display name for datasource
  const getDatasourceName = (id) => {
    const ds = datasources.find(d => d.datasource_id === id);
    return ds ? ds.name : id;
  };

  // Get display name for topic
  const getTopicName = (id) => {
    const topic = topics.find(t => t.topic_id === id);
    return topic ? topic.name : id;
  };

  // Get display name for organization
  const getOrgName = (id) => {
    const org = organizations.find(o => o.org_id === id);
    return org ? org.name : id;
  };

  // Pagination
  const totalPages = Math.ceil(totalCount / pageSize);

  if (!user) {
    return (
      <div className="document-search-container">
        <div className="empty-state">
          <p>Please log in to search documents.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="document-search-container">
      {/* Filters Panel */}
      <div className="filters-panel">
        <div className="filters-header">
          <div className="filters-title">
            <SearchIcon size={20} />
            <h2>Document Search</h2>
          </div>
          <button className="clear-filters-btn" onClick={clearFilters}>
            Clear All
          </button>
        </div>

          {isLoadingFilters ? (
            <div className="filters-loading">
              <div className="loading-spinner small"></div>
              <span>Loading filters...</span>
            </div>
          ) : (
            <>
              {/* Keywords */}
              <div className="filter-group">
                <label>Keywords</label>
                <div className="keyword-input-row">
                  <input
                    type="text"
                    value={keywordInput}
                    onChange={(e) => setKeywordInput(e.target.value)}
                    onKeyPress={handleKeywordKeyPress}
                    placeholder="Add keyword..."
                    className="keyword-input"
                  />
                  <button onClick={addKeyword} className="add-keyword-btn" title="Add keyword">
                    <PlusIcon size={16} />
                  </button>
                </div>
                {keywords.length > 0 && (
                  <div className="keyword-chips">
                    {keywords.map(kw => (
                      <span key={kw} className="chip">
                        {kw}
                        <button onClick={() => removeKeyword(kw)} className="chip-remove">×</button>
                      </span>
                    ))}
                  </div>
                )}
                {keywords.length > 1 && (
                  <div className="keyword-match-mode">
                    <label>
                      <input
                        type="radio"
                        name="matchMode"
                        value="any"
                        checked={keywordMatchMode === 'any'}
                        onChange={(e) => setKeywordMatchMode(e.target.value)}
                      />
                      Match any (OR)
                    </label>
                    <label>
                      <input
                        type="radio"
                        name="matchMode"
                        value="all"
                        checked={keywordMatchMode === 'all'}
                        onChange={(e) => setKeywordMatchMode(e.target.value)}
                      />
                      Match all (AND)
                    </label>
                  </div>
                )}
              </div>

              {/* Datasources */}
              <div className="filter-group">
                <label>Datasources</label>
                <select 
                  onChange={(e) => handleMultiSelect(e, setSelectedDatasources, selectedDatasources)}
                  className="filter-select"
                >
                  <option value="">Select datasource...</option>
                  {datasources.map(ds => (
                    <option key={ds.datasource_id} value={ds.datasource_id}>
                      {ds.name} ({ds.document_count})
                    </option>
                  ))}
                </select>
                {selectedDatasources.length > 0 && (
                  <div className="selected-chips">
                    {selectedDatasources.map(id => (
                      <span key={id} className="chip">
                        {getDatasourceName(id)}
                        <button onClick={() => removeFromSelection(id, setSelectedDatasources, selectedDatasources)} className="chip-remove">×</button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Categories */}
              <div className="filter-group">
                <label>
                  Categories
                  {isLoadingFilterOptions && <span className="loading-indicator">...</span>}
                </label>
                <select 
                  onChange={(e) => handleMultiSelect(e, setSelectedCategories, selectedCategories)}
                  className="filter-select"
                  disabled={isLoadingFilterOptions}
                >
                  <option value="">{categories.length === 0 ? 'No categories available' : 'Select category...'}</option>
                  {categories.map(cat => (
                    <option key={cat.category_id} value={cat.category_id}>
                      {cat.name} ({cat.document_count})
                    </option>
                  ))}
                </select>
                {selectedCategories.length > 0 && (
                  <div className="selected-chips">
                    {selectedCategories.map(id => (
                      <span key={id} className="chip category-chip">
                        {categories.find(c => c.category_id === id)?.name || id}
                        <button onClick={() => removeFromSelection(id, setSelectedCategories, selectedCategories)} className="chip-remove">×</button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Topics */}
              <div className="filter-group">
                <label>
                  Topics
                  {isLoadingFilterOptions && <span className="loading-indicator">...</span>}
                </label>
                <select 
                  onChange={(e) => handleMultiSelect(e, setSelectedTopics, selectedTopics)}
                  className="filter-select"
                  disabled={isLoadingFilterOptions}
                >
                  <option value="">{topics.length === 0 ? 'No topics available' : 'Select topic...'}</option>
                  {topics.slice(0, 100).map(topic => (
                    <option key={topic.topic_id} value={topic.topic_id}>
                      {topic.name} ({topic.document_count})
                    </option>
                  ))}
                </select>
                {selectedTopics.length > 0 && (
                  <div className="selected-chips">
                    {selectedTopics.map(id => (
                      <span key={id} className="chip topic-chip">
                        {getTopicName(id)}
                        <button onClick={() => removeFromSelection(id, setSelectedTopics, selectedTopics)} className="chip-remove">×</button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Organizations */}
              <div className="filter-group">
                <label>
                  Organizations
                  {isLoadingFilterOptions && <span className="loading-indicator">...</span>}
                </label>
                <select 
                  onChange={(e) => handleMultiSelect(e, setSelectedOrganizations, selectedOrganizations)}
                  className="filter-select"
                  disabled={isLoadingFilterOptions}
                >
                  <option value="">{organizations.length === 0 ? 'No organizations available' : 'Select organization...'}</option>
                  {organizations.slice(0, 100).map(org => (
                    <option key={org.org_id} value={org.org_id}>
                      {org.name} ({org.document_count})
                    </option>
                  ))}
                </select>
                {selectedOrganizations.length > 0 && (
                  <div className="selected-chips">
                    {selectedOrganizations.map(id => (
                      <span key={id} className="chip org-chip">
                        {getOrgName(id)}
                        <button onClick={() => removeFromSelection(id, setSelectedOrganizations, selectedOrganizations)} className="chip-remove">×</button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Date Range */}
              <div className="filter-group">
                <label>Date Range</label>
                <div className="date-range-inputs">
                  <div className="date-input-wrapper">
                    <span className="date-label">From:</span>
                    <input
                      type="date"
                      value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)}
                      className="date-input"
                    />
                  </div>
                  <div className="date-input-wrapper">
                    <span className="date-label">To:</span>
                    <input
                      type="date"
                      value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)}
                      className="date-input"
                    />
                  </div>
                </div>
              </div>

              {/* Sort Options */}
              <div className="filter-group">
                <label>Sort By</label>
                <div className="sort-options">
                  <select 
                    value={sortBy} 
                    onChange={(e) => setSortBy(e.target.value)}
                    className="sort-select"
                  >
                    <option value="publish_date">Publish Date</option>
                    <option value="title">Title</option>
                  </select>
                  <select 
                    value={sortOrder} 
                    onChange={(e) => setSortOrder(e.target.value)}
                    className="sort-select"
                  >
                    <option value="desc">Newest First</option>
                    <option value="asc">Oldest First</option>
                  </select>
                </div>
              </div>

              {/* Search Button */}
              <button 
                onClick={() => handleSearch(1)} 
                className="search-btn"
                disabled={isLoading}
              >
                {isLoading ? (
                  <>
                    <div className="loading-spinner small"></div>
                    Searching...
                  </>
                ) : (
                  <>
                    <SearchIcon size={18} />
                    {isLoadingCount ? (
                      'Loading count...'
                    ) : documentCount !== null ? (
                      `Search (${documentCount.toLocaleString()}) Document${documentCount !== 1 ? 's' : ''}`
                    ) : (
                      'Search Documents'
                    )}
                  </>
                )}
              </button>
            </>
          )}
        </div>

        {/* Results Panel */}
        <div className="results-panel">
          {error && (
            <div className="error-message">
              <p>{error}</p>
            </div>
          )}

          {!hasSearched && !isLoading && (
            <div className="empty-state">
              <SearchIcon size={48} />
              <h3>Search Documents</h3>
              <p>Use the filters on the left to search for documents in the knowledge graph.</p>
            </div>
          )}

          {hasSearched && !isLoading && results.length === 0 && (
            <div className="empty-state">
              <BookIcon size={48} />
              <h3>No Documents Found</h3>
              <p>Try adjusting your filters or search terms.</p>
            </div>
          )}

          {hasSearched && (results.length > 0 || isLoading) && (
            <>
              <div className="results-header">
                <span className="results-count">
                  {isLoading ? 'Searching...' : `${totalCount.toLocaleString()} documents found`}
                </span>
                {totalPages > 1 && (
                  <span className="page-info">
                    Page {currentPage} of {totalPages}
                  </span>
                )}
              </div>

              <div className="results-list">
                {results.map((doc, index) => (
                  <div key={doc.url_hash || index} className="document-card">
                    <div className="document-header">
                      <a 
                        href={doc.url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="document-title"
                      >
                        {doc.title || 'Untitled Document'}
                        <LinkIcon size={14} />
                      </a>
                      {doc.publish_date && (
                        <span className="document-date">
                          <CalendarIcon size={12} />
                          {formatDate(doc.publish_date)}
                        </span>
                      )}
                    </div>
                    
                    <div className="document-meta">
                      {doc.datasource_name && (
                        <span className="meta-tag datasource">
                          {doc.datasource_name}
                        </span>
                      )}
                      {doc.category && (
                        <span className="meta-tag category">
                          {doc.category}
                        </span>
                      )}
                    </div>

                    {doc.summary && (
                      <p className="document-summary">
                        {doc.summary.length > 300 
                          ? doc.summary.substring(0, 300) + '...' 
                          : doc.summary}
                      </p>
                    )}

                    {(doc.topics?.length > 0 || doc.organizations?.length > 0) && (
                      <div className="document-tags">
                        {doc.topics?.slice(0, 5).map(topic => (
                          <span key={topic} className="tag topic-tag">{topic}</span>
                        ))}
                        {doc.organizations?.slice(0, 3).map(org => (
                          <span key={org} className="tag org-tag">{org}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="pagination">
                  <button 
                    onClick={() => handleSearch(currentPage - 1)}
                    disabled={currentPage === 1 || isLoading}
                    className="pagination-btn"
                  >
                    Previous
                  </button>
                  
                  <div className="pagination-pages">
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      let pageNum;
                      if (totalPages <= 5) {
                        pageNum = i + 1;
                      } else if (currentPage <= 3) {
                        pageNum = i + 1;
                      } else if (currentPage >= totalPages - 2) {
                        pageNum = totalPages - 4 + i;
                      } else {
                        pageNum = currentPage - 2 + i;
                      }
                      
                      return (
                        <button
                          key={pageNum}
                          onClick={() => handleSearch(pageNum)}
                          disabled={isLoading}
                          className={`pagination-btn page-num ${currentPage === pageNum ? 'active' : ''}`}
                        >
                          {pageNum}
                        </button>
                      );
                    })}
                  </div>

                  <button 
                    onClick={() => handleSearch(currentPage + 1)}
                    disabled={currentPage === totalPages || isLoading}
                    className="pagination-btn"
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
  );
};

export default DocumentSearch;
