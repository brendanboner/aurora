import React, { useState, useEffect, useCallback } from 'react';
import apiClient from '../api/client';
import './IETFGroupsModal.css';

export default function IETFGroupsModal({ isOpen, onClose }) {
  const [areas, setAreas] = useState([]);
  const [enabledGroups, setEnabledGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [successMsg, setSuccessMsg] = useState('');
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isOpen) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setSuccessMsg('');

    Promise.all([
      apiClient.get('/backend/ietf/enabled-groups'),
      apiClient.get('/backend/ietf/areas'),
    ])
      .then(([enabledRes, areasRes]) => {
        if (cancelled) return;
        setEnabledGroups(enabledRes.data?.enabled_groups ?? []);
        setAreas(areasRes.data?.areas ?? []);
      })
      .catch((err) => {
        if (!cancelled) setError('Failed to load IETF areas. Please try again.');
        console.error('IETFGroupsModal: load error', err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [isOpen]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  const isAreaEnabled = useCallback(
    (acronym) => enabledGroups.includes(`area:${acronym}`),
    [enabledGroups]
  );

  const toggleArea = (acronym) => {
    const key = `area:${acronym}`;
    setEnabledGroups((prev) =>
      prev.includes(key) ? prev.filter((g) => g !== key) : [...prev, key]
    );
  };

  const handleApply = async () => {
    setSaving(true);
    setError(null);
    try {
      await apiClient.post('/backend/admin/ietf/apply-groups', { groups: enabledGroups });
      setSuccessMsg('IETF groups saved successfully.');
      setTimeout(() => {
        setSuccessMsg('');
        onClose();
      }, 1500);
    } catch (err) {
      console.error('IETFGroupsModal: save error', err);
      setError('Failed to save IETF groups. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      className="ietf-overlay"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="ietf-modal" role="dialog" aria-modal="true" aria-labelledby="ietf-modal-title">
        <div className="ietf-header">
          <h2 className="ietf-title" id="ietf-modal-title">Configure IETF Groups</h2>
          <button className="ietf-close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="ietf-body">
          {loading ? (
            <div className="ietf-loading">
              <div className="ietf-spinner" />
              Loading IETF areas…
            </div>
          ) : (
            <>
              <p className="ietf-description">
                Select the IETF areas to scrape from Datatracker. All working groups within a
                selected area will be included.
              </p>

              {areas.length === 0 ? (
                <div className="ietf-empty">No IETF areas available.</div>
              ) : (
                <div className="ietf-area-list">
                  {areas.map((area) => {
                    const enabled = isAreaEnabled(area.acronym);
                    const wgCount = area.wg_count ?? (area.working_groups?.length ?? 0);
                    return (
                      <label key={area.acronym} className={`ietf-area-row${enabled ? ' enabled' : ''}`}>
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={() => toggleArea(area.acronym)}
                          className="ietf-checkbox"
                        />
                        <div className="ietf-area-info">
                          <span className="ietf-area-name">{area.name || area.acronym}</span>
                          <span className="ietf-area-acronym">{area.acronym}</span>
                        </div>
                        {wgCount > 0 && (
                          <span className="ietf-wg-count">{wgCount} working group{wgCount !== 1 ? 's' : ''}</span>
                        )}
                      </label>
                    );
                  })}
                </div>
              )}

              {error && <div className="ietf-error">{error}</div>}
              {successMsg && <div className="ietf-success">{successMsg}</div>}
            </>
          )}
        </div>

        <div className="ietf-footer">
          <button
            className="ietf-btn-cancel"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            className="ietf-btn-apply"
            onClick={handleApply}
            disabled={loading || saving}
          >
            {saving ? 'Saving…' : 'Apply'}
          </button>
        </div>
      </div>
    </div>
  );
}
