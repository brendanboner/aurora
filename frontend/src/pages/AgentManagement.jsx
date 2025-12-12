import React, { useEffect, useMemo, useState } from 'react';
import './AgentManagement.css';
import { PlusIcon, SaveIcon, TrashIcon, WarningIcon } from '../components/icons';
import {
  getCreatorAgents,
  createCreatorAgent,
  updateCreatorAgent,
  deleteCreatorAgent,
} from '../services/api';

const initialForm = {
  name: '',
  description: '',
  persona: '',
  expertise_topics: '',
  expertise_organisations: '',
  expertise_standards: '',
  posting_cadence: 'per-event',
  tone_style: 'analytical',
  content_length_preference: 'medium',
  importance_threshold: 'normal',
  enabled: true,
};

const cadenceOptions = [
  { value: 'per-event', label: 'Per Event' },
  { value: 'daily-digest', label: 'Daily Digest' },
  { value: 'weekly-digest', label: 'Weekly Digest' },
  { value: 'important-only', label: 'Only high-importance' },
];

const lengthOptions = [
  { value: 'brief', label: 'Brief' },
  { value: 'medium', label: 'Medium' },
  { value: 'longform', label: 'Longform' },
];

const AgentManagement = () => {
  const [agents, setAgents] = useState([]);
  const [formState, setFormState] = useState(initialForm);
  const [editingId, setEditingId] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState(null);
  const [error, setError] = useState(null);

  const loadAgents = async () => {
    try {
      const data = await getCreatorAgents(true);
      setAgents(data);
    } catch (err) {
      console.error('Failed to load agents', err);
      setError('Unable to load CreatorAgents');
    }
  };

  useEffect(() => {
    loadAgents();
  }, []);

  const resetForm = (preserveStatus = false) => {
    setEditingId(null);
    setFormState(initialForm);
    if (!preserveStatus) {
      setStatusMessage(null);
    }
  };

  const parseCommaList = (value) =>
    value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean);

  const buildPayload = () => ({
    ...formState,
    expertise_topics: parseCommaList(formState.expertise_topics),
    expertise_organisations: parseCommaList(formState.expertise_organisations),
    expertise_standards: parseCommaList(formState.expertise_standards),
  });

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsLoading(true);
    setStatusMessage(null);
    try {
      const payload = buildPayload();
      if (editingId) {
        await updateCreatorAgent(editingId, payload);
        setStatusMessage('Agent updated successfully');
      } else {
        await createCreatorAgent(payload);
        setStatusMessage('Agent created successfully');
      }
      resetForm(true);
      await loadAgents();
    } catch (err) {
      console.error('Agent save failed', err);
      setStatusMessage('Unable to save agent');
    } finally {
      setIsLoading(false);
    }
  };

  const handleEdit = (agent) => {
    setEditingId(agent.id);
    setFormState({
      ...agent,
      expertise_topics: (agent.expertise_topics || []).join(', '),
      expertise_organisations: (agent.expertise_organisations || []).join(', '),
      expertise_standards: (agent.expertise_standards || []).join(', '),
    });
  };

  const handleDelete = async (agentId) => {
    if (!window.confirm('Delete this agent?')) {
      return;
    }
    try {
      await deleteCreatorAgent(agentId);
      if (editingId === agentId) {
        resetForm();
      }
      await loadAgents();
    } catch (err) {
      console.error('Delete failed', err);
      setStatusMessage('Unable to delete agent');
    }
  };

  const activeAgents = useMemo(() => agents.filter((agent) => agent.enabled), [agents]);

  return (
    <div className="agent-admin-shell">
      <div className="agent-admin-header">
        <div>
          <h1>CreatorAgents</h1>
          <p>Craft dedicated personas that watch the graph and publish autonomous updates.</p>
        </div>
        <div className="agent-metrics">
          <div>
            <span>Enabled</span>
            <strong>{activeAgents.length}</strong>
          </div>
          <div>
            <span>Total</span>
            <strong>{agents.length}</strong>
          </div>
        </div>
      </div>

      {error && (
        <div className="agent-error">
          <WarningIcon size={18} />
          <span>{error}</span>
        </div>
      )}

      <div className="agent-admin-grid">
        <section className="agent-list">
          <header>
            <h2>Existing personas</h2>
            <button className="ghost-btn" onClick={resetForm}>
              <PlusIcon size={16} />
              <span>New agent</span>
            </button>
          </header>
          {agents.length === 0 && <p className="empty-copy">No agents yet. Create one to get started.</p>}
          <div className="agent-table">
            {agents.map((agent) => (
              <div key={agent.id} className={`agent-row ${agent.enabled ? '' : 'disabled'}`}>
                <div>
                  <h3>{agent.name}</h3>
                  <p>{agent.description || 'No description set.'}</p>
                  <div className="agent-meta-line">
                    <span>Cadence: {agent.posting_cadence}</span>
                    <span>Length: {agent.content_length_preference}</span>
                    <span>Status: {agent.enabled ? 'Enabled' : 'Disabled'}</span>
                  </div>
                </div>
                <div className="row-actions">
                  <button className="ghost-btn" onClick={() => handleEdit(agent)}>Edit</button>
                  <button className="ghost-btn danger" onClick={() => handleDelete(agent.id)}>
                    <TrashIcon size={14} />
                    <span>Delete</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="agent-form">
          <header>
            <h2>{editingId ? 'Edit persona' : 'New persona'}</h2>
            {statusMessage && <span className="status-pill">{statusMessage}</span>}
          </header>
          <form onSubmit={handleSubmit}>
            <label>
              Agent handle
              <input
                type="text"
                value={formState.name}
                onChange={(e) => setFormState((prev) => ({ ...prev, name: e.target.value }))}
                required
              />
            </label>
            <label>
              Short description
              <textarea
                value={formState.description}
                onChange={(e) => setFormState((prev) => ({ ...prev, description: e.target.value }))}
                rows={2}
              />
            </label>
            <label>
              Persona / instructions
              <textarea
                value={formState.persona}
                onChange={(e) => setFormState((prev) => ({ ...prev, persona: e.target.value }))}
                placeholder="Explain how this agent should reason, cite sources, and speak."
                rows={4}
              />
            </label>
            <div className="two-col">
              <label>
                Topics (comma separated)
                <textarea
                  value={formState.expertise_topics}
                  onChange={(e) => setFormState((prev) => ({ ...prev, expertise_topics: e.target.value }))}
                  rows={2}
                />
              </label>
              <label>
                Organisations (comma separated)
                <textarea
                  value={formState.expertise_organisations}
                  onChange={(e) =>
                    setFormState((prev) => ({ ...prev, expertise_organisations: e.target.value }))
                  }
                  rows={2}
                />
              </label>
            </div>
            <label>
              Standards / programmes (comma separated)
              <textarea
                value={formState.expertise_standards}
                onChange={(e) => setFormState((prev) => ({ ...prev, expertise_standards: e.target.value }))}
                rows={2}
              />
            </label>
            <div className="two-col">
              <label>
                Posting cadence
                <select
                  value={formState.posting_cadence}
                  onChange={(e) => setFormState((prev) => ({ ...prev, posting_cadence: e.target.value }))}
                >
                  {cadenceOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Content length
                <select
                  value={formState.content_length_preference}
                  onChange={(e) =>
                    setFormState((prev) => ({ ...prev, content_length_preference: e.target.value }))
                  }
                >
                  {lengthOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              Tone / style keywords
              <input
                type="text"
                value={formState.tone_style}
                onChange={(e) => setFormState((prev) => ({ ...prev, tone_style: e.target.value }))}
              />
            </label>
            <label>
              Importance threshold
              <input
                type="text"
                value={formState.importance_threshold}
                onChange={(e) => setFormState((prev) => ({ ...prev, importance_threshold: e.target.value }))}
                placeholder="normal | important | critical"
              />
            </label>
            <label className="checkbox-field">
              <input
                type="checkbox"
                checked={formState.enabled}
                onChange={(e) => setFormState((prev) => ({ ...prev, enabled: e.target.checked }))}
              />
              <span>Enabled</span>
            </label>
            <div className="form-actions">
              <button type="submit" className="primary" disabled={isLoading}>
                <SaveIcon size={16} />
                <span>{editingId ? 'Update agent' : 'Create agent'}</span>
              </button>
              <button type="button" className="ghost-btn" onClick={resetForm}>
                Reset
              </button>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
};

export default AgentManagement;
