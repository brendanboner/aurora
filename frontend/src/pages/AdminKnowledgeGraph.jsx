import React, { useState, useEffect, useCallback } from 'react';
import { getGraphStatistics, getTopics, getOrganisations, getPeople } from '../services/api';
import './Admin.css';
import { BookIcon, BuildingIcon, ProfileIcon, WarningIcon } from '../components/icons';

const AdminKnowledgeGraph = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [topics, setTopics] = useState([]);
  const [organisations, setOrganisations] = useState([]);
  const [people, setPeople] = useState([]);
  const [activeTab, setActiveTab] = useState('topics');

  const normalize = (data, key) => {
    if (Array.isArray(data)) return data;
    if (key && Array.isArray(data?.[key])) return data[key];
    return [];
  };

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, tRaw, oRaw, pRaw] = await Promise.all([
        getGraphStatistics(),
        getTopics(),
        getOrganisations(),
        getPeople()
      ]);
      setStats(s || null);
      setTopics(normalize(tRaw, 'topics'));
      setOrganisations(normalize(oRaw, 'organisations'));
      setPeople(normalize(pRaw, 'people'));
    } catch (err) {
      console.error('Knowledge graph load error:', err);
      setError(err.response?.data?.detail || err.message);
      setTopics([]);
      setOrganisations([]);
      setPeople([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // Pagination state for tables
  const [page, setPage] = useState(0);
  const pageSize = 25;

  const totalPages = (items) => Array.isArray(items) ? Math.ceil(items.length / pageSize) : 0;
  const paginate = (items) => {
    if (!Array.isArray(items)) return [];
    const start = page * pageSize;
    return items.slice(start, start + pageSize);
  };

  const renderTable = (items, type) => {
    if (!Array.isArray(items)) {
      return <div className="kg-empty"><WarningIcon size={14} /> No {type.toLowerCase()} data available.</div>;
    }
    if (items.length === 0) {
      return <div className="kg-empty">No {type.toLowerCase()} entries found.</div>;
    }
    const paged = paginate(items);
    return (
      <>
        <table className="kg-entity-table">
          <thead>
            <tr>
              <th>Name</th>
              {type === 'Topic' && <th>Classification</th>}
              {type === 'Organisation' && <th>Type</th>}
              {type === 'Person' && <th>Email</th>}
              <th>Aliases</th>
            </tr>
          </thead>
          <tbody>
            {paged.map(item => (
              <tr key={item.id || item.uuid || item.name}>
                <td className="cell-name">{item.name || item.title}</td>
                {type === 'Topic' && <td>{item.classification || '-'}</td>}
                {type === 'Organisation' && <td>{item.org_type || '-'}</td>}
                {type === 'Person' && <td>{item.email || '-'}</td>}
                <td>{Array.isArray(item.aliases) ? item.aliases.slice(0,3).join(', ') : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="kg-pagination">
          <div className="kg-pagination-info">Page {page + 1} / {totalPages(items)}</div>
          <div className="kg-pagination-controls">
            <button className="btn btn-secondary" disabled={page === 0} onClick={() => setPage(p => p - 1)}>‹ Prev</button>
            <button className="btn btn-secondary" disabled={page + 1 >= totalPages(items)} onClick={() => setPage(p => p + 1)}>Next ›</button>
          </div>
        </div>
      </>
    );
  };

  return (
    <div className="admin-container">
      <div className="admin-header">
        <h1>Knowledge Graph</h1>
        <p>Explore and manage graph entities</p>
      </div>
      {error && <div className="admin-error">{error}</div>}
      {loading && <div className="spinner" />}
      {!loading && (
        <div className="admin-content">
          {/* Horizontal stats row */}
          <div className="kg-stats-row">
            {stats ? (
              <>
                <div className="kg-stat-card">
                  <div className="kg-stat-value">{stats.topics}</div>
                  <div className="kg-stat-label"><BookIcon size={14} /> Topics</div>
                </div>
                <div className="kg-stat-card">
                  <div className="kg-stat-value">{stats.organisations}</div>
                  <div className="kg-stat-label"><BuildingIcon size={14} /> Organisations</div>
                </div>
                <div className="kg-stat-card">
                  <div className="kg-stat-value">{stats.people}</div>
                  <div className="kg-stat-label"><ProfileIcon size={14} /> People</div>
                </div>
                <div className="kg-stat-card">
                  <div className="kg-stat-value">{stats.relationships}</div>
                  <div className="kg-stat-label">Relationships</div>
                </div>
              </>
            ) : (
              <div className="kg-stat-empty">No statistics available.</div>
            )}
          </div>

          {/* Tab bar */}
          <div className="kg-tab-bar">
            <button className={`tab ${activeTab==='topics'?'active':''}`} onClick={()=>{setActiveTab('topics'); setPage(0);}}>Topics ({Array.isArray(topics)?topics.length:0})</button>
            <button className={`tab ${activeTab==='organisations'?'active':''}`} onClick={()=>{setActiveTab('organisations'); setPage(0);}}>Organisations ({Array.isArray(organisations)?organisations.length:0})</button>
            <button className={`tab ${activeTab==='people'?'active':''}`} onClick={()=>{setActiveTab('people'); setPage(0);}}>People ({Array.isArray(people)?people.length:0})</button>
          </div>

          {/* Entity table */}
          <div className="kg-table-wrapper">
            {activeTab === 'topics' && renderTable(topics, 'Topic')}
            {activeTab === 'organisations' && renderTable(organisations, 'Organisation')}
            {activeTab === 'people' && renderTable(people, 'Person')}
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminKnowledgeGraph;