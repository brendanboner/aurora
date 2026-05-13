/**
 * WorkgroupPreferencesModal — thin wrapper around PreferencesPanel.
 *
 * Preserved for backward-compatibility with the Chatbot quick-access button.
 * Opens the Groups tab by default. All logic lives in PreferencesPanel.
 */
import React from 'react';
import PreferencesPanel from './PreferencesPanel';
import './WorkgroupPreferencesModal.css';

/**
 * WorkgroupPreferencesModal
 *
 * Lets users join (boost) or ignore (hard-exclude) data sources.
 * Changes are saved instantly on toggle — no submit button needed.
 *
 * Rules:
 *   - Joined  → results from this source are boosted
 *   - Ignored → results from this source are completely excluded
 *   - Ignore overrides Join (when Ignore is on, Join is disabled)
 *   - Default (neither) → standard behaviour, nothing changes
 */
export default function WorkgroupPreferencesModal({ userId, onClose }) {
  return (
    <div className="wgp-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="wgp-modal" role="dialog" aria-modal="true" aria-labelledby="wgp-title"
           style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', height: '80vh' }}>
        <PreferencesPanel userId={userId} defaultTab="group" onClose={onClose} />
      </div>
    </div>
  );
}

