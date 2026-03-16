import React, { useEffect, useMemo, useState } from 'react';
import './MyAgents.css';
import ConfirmModal from '../components/ConfirmModal';
import { useAuth } from '../contexts/AuthContext';
import { PlayIcon, PlusIcon, SaveIcon, TrashIcon, WarningIcon } from '../components/icons';
import {
  getMyAgents,
  createMyAgent,
  updateMyAgent,
  deleteMyAgent,
  triggerMyAgentGeneration,
} from '../services/api';

const initialForm = {
  name: '',
  project_description: '',
  scope_notes: '',
  cadence: 'daily-digest',
  show_in_feed: true,
  enabled: true,
};

const cadenceOptions = [
  { value: 'daily-digest', label: 'Daily updates' },
  { value: 'weekly-digest', label: 'Weekly updates' },
];

const MyAgents = () => {
  const { user } = useAuth();
  const [agents, setAgents] = useState([]);
  const [formState, setFormState] = useState(initialForm);
  const [editingId, setEditingId] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState(null);
  const [error, setError] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmPending, setConfirmPending] = useState(false);
  const [generatingAgentId, setGeneratingAgentId] = useState(null);
  const [togglingFeedAgentId, setTogglingFeedAgentId] = useState(null);
  const [confirmConfig, setConfirmConfig] = useState({
    title: '',
    message: '',
    confirmLabel: 'Delete',
    confirmVariant: 'danger',
    requireText: '',
    onConfirm: null,
  });

  const loadAgents = async () => {
    if (!user) {
      setAgents([]);
      return;
    }
    try {
      setError(null);
      const data = await getMyAgents();
      setAgents(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load personal agents', err);
      setError('Unable to load your agents. They will appear here once created.');
    }
  };

  useEffect(() => {
    loadAgents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  const resetForm = (preserveStatus = false) => {
    setEditingId(null);
    setFormState(initialForm);
    if (!preserveStatus) {
      setStatusMessage(null);
    }
  };

  const handleEdit = (agent) => {
    setEditingId(agent.id);
    setFormState({
      name: agent.name || '',
      project_description: agent.project_description || '',
      scope_notes: agent.scope_notes || '',
      cadence: agent.cadence || 'daily-digest',
      show_in_feed: agent.show_in_feed !== false,
      enabled: agent.enabled !== false,
    });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!user) return;

    setIsLoading(true);
    setStatusMessage(null);
    setError(null);

    const payload = {
      name: formState.name,
      project_description: formState.project_description,
      scope_notes: formState.scope_notes,
      cadence: formState.cadence,
      show_in_feed: formState.show_in_feed,
      enabled: formState.enabled,
    };

    try {
      if (editingId) {
        await updateMyAgent(editingId, payload);
        setStatusMessage('Agent updated');
      } else {
        await createMyAgent(payload);
        setStatusMessage('Agent created and added to your Creator Feed');
      }
      resetForm(true);
      await loadAgents();
    } catch (err) {
      console.error('Save personal agent failed', err);
      setError('Unable to save this agent. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const openDeleteConfirm = (agent) => {
    setConfirmConfig({
      title: `Delete ${agent.name}?`,
      message: 'This will remove the agent and stop future updates for this project.',
      confirmLabel: 'Delete agent',
      confirmVariant: 'danger',
      requireText: agent.name,
      onConfirm: async () => {
        await deleteMyAgent(agent.id);
        if (editingId === agent.id) {
          resetForm();
        }
        await loadAgents();
      },
    });
    setConfirmOpen(true);
  };

  const closeConfirm = () => {
    setConfirmOpen(false);
    setConfirmPending(false);
    setConfirmConfig({
      title: '',
      message: '',
      confirmLabel: 'Delete',
      confirmVariant: 'danger',
      requireText: '',
      onConfirm: null,
    });
  };

  const handleConfirm = async () => {
    if (!confirmConfig.onConfirm) {
      closeConfirm();
      return;
    }
    try {
      setConfirmPending(true);
      await confirmConfig.onConfirm();
      closeConfirm();
    } catch (err) {
      console.error('Delete personal agent failed', err);
      setConfirmPending(false);
      setError('Unable to delete this agent.');
    }
  };

  const handleGenerate = async (agent) => {
    setGeneratingAgentId(agent.id);
    setStatusMessage(null);
    setError(null);
    try {
      const result = await triggerMyAgentGeneration(agent.id);
      if (result?.status === 'success') {
        setStatusMessage(`Generated an update for ${agent.name}.`);
      } else if (result?.status === 'no_content') {
        setStatusMessage(`No fresh content found for ${agent.name} yet.`);
      } else {
        setStatusMessage(`Generation finished for ${agent.name}.`);
      }
      await loadAgents();
    } catch (err) {
      console.error('Generate personal agent content failed', err);
      setError(`Unable to generate an update for ${agent.name} right now.`);
    } finally {
      setGeneratingAgentId(null);
    }
  };

  const handleFeedVisibilityToggle = async (agent) => {
    setTogglingFeedAgentId(agent.id);
    setStatusMessage(null);
    setError(null);
    try {
      await updateMyAgent(agent.id, { show_in_feed: agent.show_in_feed === false });
      setStatusMessage(
        agent.show_in_feed === false
          ? `You are now following ${agent.name} in your Creator Feed.`
          : `You unfollowed ${agent.name} from your Creator Feed.`
      );
      await loadAgents();
    } catch (err) {
      console.error('Toggle personal agent feed visibility failed', err);
      setError(`Unable to update feed visibility for ${agent.name}.`);
    } finally {
      setTogglingFeedAgentId(null);
    }
  };

  const activeAgents = useMemo(
    () => agents.filter((agent) => agent.enabled !== false),
    [agents]
  );

  return (
    <div className="my-agents-shell">
      <div className="my-agents-header">
        <div>
          <h1>My Agents</h1>
          <p>
            Create personal project partners that stay focused on a single investigation
            and keep you updated with tailored summaries.
          </p>
        </div>
        <div className="my-agents-metrics">
          <div>
            <span>Active</span>
            <strong>{activeAgents.length}</strong>
          </div>
          <div>
            <span>Total</span>
            <strong>{agents.length}</strong>
          </div>
        </div>
      </div>

      {error && (
        <div className="my-agents-error">
          <WarningIcon size={18} />
          <span>{error}</span>
        </div>
      )}

      <div className="my-agents-grid">
        <section className="my-agents-list">
          <header>
            <h2>Your project agents</h2>
            <button className="ghost-btn" onClick={() => resetForm()}>
              <PlusIcon size={16} />
              <span>New agent</span>
            </button>
          </header>
          {agents.length === 0 && (
            <p className="empty-copy">
              You don&apos;t have any agents yet. Create one for each key project
              or investigation you&apos;re running.
            </p>
          )}
          <div className="my-agents-list-items">
            {agents.map((agent) => (
              <div
                key={agent.id}
                className={`my-agent-row ${agent.enabled === false ? 'disabled' : ''}`}
              >
                <div className="my-agent-main">
                  <h3>{agent.name}</h3>
                  <p className="my-agent-project">{agent.project_description}</p>
                  <div className="my-agent-meta">
                    <span>Cadence: {agent.cadence || 'daily-digest'}</span>
                    <span>
                      Feed: {agent.show_in_feed === false ? 'Not followed' : 'Following'}
                    </span>
                    <span>Status: {agent.enabled === false ? 'Paused' : 'Active'}</span>
                  </div>
                </div>
                <div className="my-agent-actions">
                  <button
                    className="action-btn generate-btn"
                    onClick={() => handleGenerate(agent)}
                    disabled={generatingAgentId === agent.id || agent.enabled === false}
                    title={agent.enabled === false ? 'Enable this agent before generating' : 'Generate an update now'}
                  >
                    <PlayIcon size={14} />
                    <span>{generatingAgentId === agent.id ? 'Running...' : 'Run now'}</span>
                  </button>
                  <button
                    className="action-btn visibility-btn"
                    onClick={() => handleFeedVisibilityToggle(agent)}
                    disabled={togglingFeedAgentId === agent.id}
                    title={
                      agent.show_in_feed === false
                        ? 'Show this agent in your Creator Feed again'
                        : 'Hide this agent from your Creator Feed'
                    }
                  >
                      <span>
                        {togglingFeedAgentId === agent.id
                          ? 'Saving...'
                          : agent.show_in_feed === false
                            ? 'Follow'
                            : 'Unfollow'}
                      </span>
                    </button>
                  <button
                    className="action-btn edit-btn"
                    onClick={() => handleEdit(agent)}
                  >
                    Edit
                  </button>
                  <button
                    className="action-btn delete-btn"
                    onClick={() => openDeleteConfirm(agent)}
                  >
                    <TrashIcon size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="my-agents-form">
          <header>
            <h2>{editingId ? 'Edit project agent' : 'New project agent'}</h2>
            {statusMessage && <span className="status-pill">{statusMessage}</span>}
          </header>
          <form onSubmit={handleSubmit}>
            <label>
              Agent name
              <input
                type="text"
                value={formState.name}
                onChange={(e) =>
                  setFormState((prev) => ({ ...prev, name: e.target.value }))
                }
                placeholder="e.g. Sticky Clients Wi-Fi Investigator"
                required
              />
            </label>
            <label>
              Project / workspace description
              <textarea
                value={formState.project_description}
                onChange={(e) =>
                  setFormState((prev) => ({
                    ...prev,
                    project_description: e.target.value,
                  }))
                }
                rows={4}
                placeholder="Describe what you are working on, for example: I am working on an investigation into sticky clients for the next generation of Wi-Fi, and I would like to keep updated with anything related to this."
                required
              />
            </label>
            <label>
              Focus and lane guidance (optional)
              <textarea
                value={formState.scope_notes}
                onChange={(e) =>
                  setFormState((prev) => ({ ...prev, scope_notes: e.target.value }))
                }
                rows={3}
                placeholder="Add any specific topics, organisations, or constraints that help this agent stay in its lane."
              />
            </label>
            <div className="two-col">
              <label>
                Update cadence
                <select
                  value={formState.cadence}
                  onChange={(e) =>
                    setFormState((prev) => ({ ...prev, cadence: e.target.value }))
                  }
                >
                  {cadenceOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={formState.show_in_feed}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      show_in_feed: e.target.checked,
                    }))
                  }
                />
                <span>Show this agent&apos;s updates in my Creator Feed</span>
              </label>
            </div>
            <label className="checkbox-field">
              <input
                type="checkbox"
                checked={formState.enabled}
                onChange={(e) =>
                  setFormState((prev) => ({ ...prev, enabled: e.target.checked }))
                }
              />
              <span>Agent is active</span>
            </label>
            <div className="form-actions">
              <button type="submit" className="primary" disabled={isLoading}>
                <SaveIcon size={16} />
                <span>{editingId ? 'Update agent' : 'Create agent'}</span>
              </button>
              <button
                type="button"
                className="ghost-btn"
                onClick={() => resetForm()}
              >
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
    </div>
  );
};

export default MyAgents;
