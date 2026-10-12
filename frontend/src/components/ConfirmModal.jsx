import React, { useEffect, useState } from 'react';

const ConfirmModal = ({
  open,
  title = 'Are you sure?',
  message = '',
  confirmLabel = 'Confirm',
  confirmVariant = 'danger',
  requireText = '',
  pending = false,
  onCancel,
  onConfirm,
}) => {
  const [input, setInput] = useState('');

  useEffect(() => {
    if (open) setInput('');
  }, [open]);

  if (!open) return null;

  const requiresMatch = Boolean(requireText);
  const disabled = pending || (requiresMatch && input !== requireText);

  const handleBackdrop = (e) => {
    if (e.target.classList.contains('modal-backdrop')) onCancel?.();
  };

  return (
    <div className="modal-backdrop" onClick={handleBackdrop} role="dialog" aria-modal="true">
      <div className="modal">
        <header className="modal-header">
          <h3>{title}</h3>
        </header>
        <div className="modal-body">
          {typeof message === 'string' ? <p>{message}</p> : message}
          {requiresMatch && (
            <div className="confirm-input">
              <label>
                Type '{requireText}' to confirm
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={requireText}
                  autoFocus
                />
              </label>
            </div>
          )}
        </div>
        <footer className="modal-footer">
          <button className="ghost-btn" onClick={onCancel} disabled={pending}>
            Cancel
          </button>
          <button
            className={`ghost-btn ${confirmVariant}`}
            onClick={onConfirm}
            disabled={disabled}
          >
            {confirmLabel}
          </button>
        </footer>
      </div>
    </div>
  );
};

export default ConfirmModal;
