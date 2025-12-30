import React, { useEffect, useMemo, useState } from 'react';
import './AgentManagement.css';
import ConfirmModal from '../components/ConfirmModal';
import { PlusIcon, SaveIcon, TrashIcon, WarningIcon, PlayIcon } from '../components/icons';
import {
  getCreatorAgents,
  createCreatorAgent,
  updateCreatorAgent,
  deleteCreatorAgent,
  triggerAgentPost,
  purgeAgentPosts,
  purgeAllPosts,
  parseLinkedInProfile,
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
  discovery_tolerance: 0.5,
  cadence_window_days: 7,
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
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmPending, setConfirmPending] = useState(false);
  const [confirmConfig, setConfirmConfig] = useState({
    title: '',
    message: '',
    confirmLabel: 'Confirm',
    confirmVariant: 'danger',
    requireText: '',
    onConfirm: null,
  });
  const [linkedInModalOpen, setLinkedInModalOpen] = useState(false);
  const [linkedInText, setLinkedInText] = useState('');
  const [linkedInParsing, setLinkedInParsing] = useState(false);
  const [linkedInError, setLinkedInError] = useState(null);

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
      discovery_tolerance: agent.discovery_tolerance ?? 0.5,
      cadence_window_days: agent.cadence_window_days ?? 7,
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

  const openConfirm = (cfg) => {
    setConfirmConfig(cfg);
    setConfirmOpen(true);
  };

  const closeConfirm = () => {
    setConfirmOpen(false);
    setConfirmPending(false);
    setConfirmConfig({ title: '', message: '', confirmLabel: 'Confirm', confirmVariant: 'danger', requireText: '', onConfirm: null });
  };

  const handleConfirm = async () => {
    if (!confirmConfig?.onConfirm) return closeConfirm();
    try {
      setConfirmPending(true);
      await confirmConfig.onConfirm();
      closeConfirm();
    } catch (err) {
      console.error('Confirmation action failed', err);
      setConfirmPending(false);
    }
  };

  const confirmPurgeAgent = (agent) => {
    openConfirm({
      title: `Purge posts for ${agent.name}?`,
      message: "This will permanently delete ALL posts generated by this agent. This cannot be undone.",
      confirmLabel: 'Purge posts',
      confirmVariant: 'danger',
      requireText: agent.name,
      onConfirm: async () => {
        try {
          const res = await purgeAgentPosts(agent.id);
          setStatusMessage(`Purged ${res.deleted || 0} posts for ${agent.name}`);
        } catch (err) {
          console.error('Purge agent posts failed', err);
          setStatusMessage('Unable to purge posts for this agent');
        }
      },
    });
  };

  const handlePurgeAll = () => {
    openConfirm({
      title: 'Purge ALL posts?',
      message: "This will permanently delete ALL posts for ALL agents. This cannot be undone.",
      confirmLabel: 'Purge all posts',
      confirmVariant: 'danger',
      requireText: 'PURGE ALL',
      onConfirm: async () => {
        try {
          const res = await purgeAllPosts();
          setStatusMessage(`Purged ${res.deleted || 0} posts`);
        } catch (err) {
          console.error('Purge all posts failed', err);
          setStatusMessage('Unable to purge all posts');
        }
      },
    });
  };

  const handleTrigger = async (agentId) => {
    try {
      const result = await triggerAgentPost(agentId, true, 1);
      if (result.status === 'success') {
        setStatusMessage(`✓ Post created: ${result.event_title}`);
      } else {
        setStatusMessage(result.message || 'No content generated');
      }
    } catch (err) {
      console.error('Trigger failed', err);
      setStatusMessage('Unable to trigger post generation');
    }
  };

  const openLinkedInModal = () => {
    setLinkedInModalOpen(true);
    setLinkedInText('');
    setLinkedInError(null);
  };

  const closeLinkedInModal = () => {
    setLinkedInModalOpen(false);
    setLinkedInText('');
    setLinkedInError(null);
    setLinkedInParsing(false);
  };

  const handleLinkedInParse = async () => {
    if (!linkedInText.trim()) {
      setLinkedInError('Please paste LinkedIn profile content');
      return;
    }

    setLinkedInParsing(true);
    setLinkedInError(null);

    try {
      const parsed = await parseLinkedInProfile(linkedInText);
      
      // Populate form with parsed data
      setFormState({
        name: parsed.name || '',
        description: parsed.description || '',
        persona: parsed.persona || '',
        expertise_topics: (parsed.expertise_topics || []).join(', '),
        expertise_organisations: (parsed.expertise_organisations || []).join(', '),
        expertise_standards: (parsed.expertise_standards || []).join(', '),
        posting_cadence: parsed.posting_cadence || 'per-event',
        tone_style: parsed.tone_style || 'analytical',
        content_length_preference: parsed.content_length_preference || 'medium',
        importance_threshold: parsed.importance_threshold || 'normal',
        discovery_tolerance: parsed.discovery_tolerance ?? 0.5,
        cadence_window_days: parsed.cadence_window_days ?? 7,
        enabled: parsed.enabled ?? true,
      });
      
      setEditingId(null);
      setStatusMessage('LinkedIn profile parsed - review and save');
      closeLinkedInModal();
    } catch (err) {
      console.error('LinkedIn parse failed', err);
      setLinkedInError(err.response?.data?.detail || 'Failed to parse LinkedIn profile. Please try again.');
    } finally {
      setLinkedInParsing(false);
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
          <div>
            <button className="ghost-btn danger" onClick={handlePurgeAll} title="Purge all posts">
              <TrashIcon size={14} />
              <span>Purge All Posts</span>
            </button>
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
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button className="ghost-btn" onClick={resetForm}>
                <PlusIcon size={16} />
                <span>New agent</span>
              </button>
              <button className="ghost-btn" onClick={openLinkedInModal}>
                <span>📄 From LinkedIn</span>
              </button>
            </div>
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
                  <button className="action-btn trigger-btn" onClick={() => handleTrigger(agent.id)} title="Generate a new post now">
                    <PlayIcon size={16} />
                    <span>Run</span>
                  </button>
                  <button className="action-btn edit-btn" onClick={() => handleEdit(agent)}>
                    <span>Edit</span>
                  </button>
                  <button className="action-btn purge-btn" onClick={() => confirmPurgeAgent(agent)} title="Delete all posts by this agent">
                    <TrashIcon size={16} />
                    <span>Clear</span>
                  </button>
                  <button className="action-btn delete-btn" onClick={() => handleDelete(agent.id)} title="Delete this agent">
                    <TrashIcon size={16} />
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
            <div className="two-col">
              <label>
                Discovery tolerance (0-1)
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={formState.discovery_tolerance}
                  onChange={(e) => setFormState((prev) => ({ ...prev, discovery_tolerance: parseFloat(e.target.value) }))}
                />
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{formState.discovery_tolerance.toFixed(1)}</span>
              </label>
              <label>
                Cadence window (days)
                <input
                  type="number"
                  min="1"
                  max="365"
                  value={formState.cadence_window_days}
                  onChange={(e) => setFormState((prev) => ({ ...prev, cadence_window_days: parseInt(e.target.value) || 7 }))}
                />
              </label>
            </div>
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
      <ConfirmModal
        open={confirmOpen}
        title={confirmConfig.title}
        message={confirmConfig.message}
        confirmLabel={confirmConfig.confirmLabel}
        confirmVariant={confirmConfig.confirmVariant}
        requireText={confirmConfig.requireText}
        pending={confirmPending}
        onCancel={closeConfirm}
        onConfirm={handleConfirm}
      />

      {linkedInModalOpen && (
        <div className="modal-backdrop" onClick={closeLinkedInModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '700px', maxHeight: '80vh' }}>
            <div className="modal-header">
              <h2>Import from LinkedIn</h2>
              <button className="modal-close" onClick={closeLinkedInModal}>&times;</button>
            </div>
            <div className="modal-body">
              <p style={{ marginBottom: '1rem', color: 'var(--text-muted)' }}>
                Paste the content from a LinkedIn profile page (including posts). The AI will analyze it to create an agent configuration.
              </p>
              <textarea
                value={linkedInText}
                onChange={(e) => setLinkedInText(e.target.value)}
                placeholder="Paste LinkedIn profile content here (up to ~800 lines)..."
                rows={15}
                style={{ width: '100%', fontFamily: 'monospace', fontSize: '0.85rem' }}
                disabled={linkedInParsing}
              />
              {linkedInError && (
                <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'var(--error-bg)', border: '1px solid var(--error-border)', borderRadius: '4px', color: 'var(--error-text)' }}>
                  {linkedInError}
                </div>
              )}
            </div>
            <div className="modal-footer" style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button className="ghost-btn" onClick={closeLinkedInModal} disabled={linkedInParsing}>
                Cancel
              </button>
              <button className="primary" onClick={handleLinkedInParse} disabled={linkedInParsing || !linkedInText.trim()}>
                {linkedInParsing ? 'Parsing...' : 'Parse Profile'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AgentManagement;
