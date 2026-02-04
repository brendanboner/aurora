import React, { useState, useEffect, useCallback } from 'react';
import {
  UploadIcon,
  FileTextIcon,
  TrashIcon,
  AlertCircleIcon,
  RefreshIcon,
} from './icons';
import { uploadDocuments, getDocumentCategories } from '../services/api';

const SUPPORTED_EXTENSIONS = ['.pdf', '.docx', '.pptx', '.xlsx', '.txt', '.md'];
const MAX_FILE_SIZE_MB = 50;

const DocumentUploadModal = ({ isOpen, onClose, preSelectedEvent, onUploadComplete }) => {
  const [stagedFiles, setStagedFiles] = useState([]);
  const [categories, setCategories] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [dragActive, setDragActive] = useState(false);

  useEffect(() => {
    if (isOpen) {
      fetchCategories();
      setStagedFiles([]);
      setError(null);
    }
  }, [isOpen]);

  const fetchCategories = async () => {
    try {
      const data = await getDocumentCategories();
      setCategories(data.categories || []);
    } catch (err) {
      console.error('Error fetching categories:', err);
    }
  };

  const validateFile = (file) => {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      return `Unsupported file type: ${ext}`;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      return `File too large. Maximum: ${MAX_FILE_SIZE_MB}MB`;
    }
    return null;
  };

  const handleFiles = useCallback((files) => {
    const newStagedFiles = Array.from(files).map(file => {
      const validationError = validateFile(file);
      return {
        file,
        title: file.name.replace(/\.[^/.]+$/, ''),
        category: 'general',
        error: validationError,
        id: Math.random().toString(36).substr(2, 9),
      };
    });
    setStagedFiles(prev => [...prev, ...newStagedFiles]);
    setError(null);
  }, []);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  }, [handleFiles]);

  const updateStagedFile = (id, field, value) => {
    setStagedFiles(prev => prev.map(f => 
      f.id === id ? { ...f, [field]: value } : f
    ));
  };

  const removeStagedFile = (id) => {
    setStagedFiles(prev => prev.filter(f => f.id !== id));
  };

  const handleUpload = async () => {
    const validFiles = stagedFiles.filter(f => !f.error);
    if (validFiles.length === 0) {
      setError('No valid files to upload');
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      
      validFiles.forEach(f => {
        formData.append('files', f.file);
      });
      
      formData.append('titles', JSON.stringify(validFiles.map(f => f.title)));
      formData.append('categories', JSON.stringify(validFiles.map(f => f.category)));
      
      // Link to the pre-selected event
      if (preSelectedEvent) {
        formData.append('related_events', JSON.stringify([preSelectedEvent]));
      }

      const result = await uploadDocuments(formData);
      
      if (result.total_success > 0) {
        onUploadComplete && onUploadComplete();
        onClose();
      }
      
      if (result.total_failed > 0) {
        const failedDocs = result.documents.filter(d => d.status === 'error');
        setError(`${result.total_failed} document(s) failed: ${failedDocs.map(d => d.error).join(', ')}`);
      }
      
    } catch (err) {
      console.error('Upload error:', err);
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content upload-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2><UploadIcon size={24} /> Upload Documents for Event</h2>
          <button className="modal-close" onClick={onClose}>&times;</button>
        </div>

        <div className="modal-body">
          {error && (
            <div className="upload-modal-error">
              <AlertCircleIcon size={16} />
              {error}
            </div>
          )}

          <div
            className={`modal-drop-zone ${dragActive ? 'active' : ''}`}
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
          >
            <UploadIcon size={36} />
            <p>Drag files here or click to browse</p>
            <input
              type="file"
              multiple
              accept={SUPPORTED_EXTENSIONS.join(',')}
              onChange={(e) => handleFiles(e.target.files)}
              className="file-input"
            />
          </div>

          {stagedFiles.length > 0 && (
            <div className="modal-files-list">
              {stagedFiles.map(stagedFile => (
                <div 
                  key={stagedFile.id} 
                  className={`modal-file-item ${stagedFile.error ? 'has-error' : ''}`}
                >
                  <div className="modal-file-header">
                    <FileTextIcon size={20} />
                    <span className="filename">{stagedFile.file.name}</span>
                    <button onClick={() => removeStagedFile(stagedFile.id)}>
                      <TrashIcon size={14} />
                    </button>
                  </div>

                  {stagedFile.error ? (
                    <div className="file-error-text">{stagedFile.error}</div>
                  ) : (
                    <div className="modal-file-form">
                      <input
                        type="text"
                        value={stagedFile.title}
                        onChange={(e) => updateStagedFile(stagedFile.id, 'title', e.target.value)}
                        placeholder="Document title"
                      />
                      <select
                        value={stagedFile.category}
                        onChange={(e) => updateStagedFile(stagedFile.id, 'category', e.target.value)}
                      >
                        {categories.map(cat => (
                          <option key={cat.id} value={cat.id}>{cat.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="modal-btn secondary" onClick={onClose} disabled={uploading}>
            Cancel
          </button>
          <button 
            className="modal-btn primary" 
            onClick={handleUpload}
            disabled={uploading || stagedFiles.length === 0 || stagedFiles.every(f => f.error)}
          >
            {uploading ? (
              <>
                <RefreshIcon size={16} className="spinning" />
                Uploading...
              </>
            ) : (
              <>
                <UploadIcon size={16} />
                Upload
              </>
            )}
          </button>
        </div>
      </div>

      <style>{`
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background-color: rgba(0, 0, 0, 0.5);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }

        .upload-modal {
          background: white;
          border-radius: 12px;
          width: 90%;
          max-width: 600px;
          max-height: 80vh;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .modal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 20px;
          border-bottom: 1px solid #e2e8f0;
        }

        .modal-header h2 {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 18px;
          margin: 0;
        }

        .modal-close {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #94a3b8;
        }

        .modal-body {
          padding: 20px;
          overflow-y: auto;
          flex: 1;
        }

        .upload-modal-error {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 14px;
          background-color: #fff5f5;
          color: #c53030;
          border-radius: 6px;
          font-size: 13px;
          margin-bottom: 16px;
        }

        .modal-drop-zone {
          border: 2px dashed #cbd5e0;
          border-radius: 8px;
          padding: 32px 20px;
          text-align: center;
          cursor: pointer;
          position: relative;
          transition: all 0.2s ease;
        }

        .modal-drop-zone:hover,
        .modal-drop-zone.active {
          border-color: #4f46e5;
          background-color: #eef2ff;
        }

        .modal-drop-zone svg {
          color: #94a3b8;
        }

        .modal-drop-zone p {
          margin: 8px 0 0;
          font-size: 14px;
          color: #64748b;
        }

        .modal-drop-zone .file-input {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          opacity: 0;
          cursor: pointer;
        }

        .modal-files-list {
          margin-top: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .modal-file-item {
          background: #f8fafc;
          border-radius: 6px;
          padding: 12px;
        }

        .modal-file-item.has-error {
          background: #fff5f5;
        }

        .modal-file-header {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .modal-file-header svg {
          color: #4f46e5;
        }

        .modal-file-header .filename {
          flex: 1;
          font-size: 13px;
          font-weight: 500;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .modal-file-header button {
          background: none;
          border: none;
          padding: 4px;
          cursor: pointer;
          color: #94a3b8;
        }

        .modal-file-header button:hover {
          color: #dc2626;
        }

        .file-error-text {
          font-size: 12px;
          color: #dc2626;
          margin-top: 4px;
        }

        .modal-file-form {
          display: flex;
          gap: 8px;
          margin-top: 8px;
        }

        .modal-file-form input,
        .modal-file-form select {
          flex: 1;
          padding: 6px 10px;
          border: 1px solid #e2e8f0;
          border-radius: 4px;
          font-size: 13px;
        }

        .modal-file-form input:focus,
        .modal-file-form select:focus {
          outline: none;
          border-color: #4f46e5;
        }

        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
          padding: 16px 20px;
          border-top: 1px solid #e2e8f0;
        }

        .modal-btn {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          border-radius: 6px;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          border: none;
        }

        .modal-btn.primary {
          background-color: #4f46e5;
          color: white;
        }

        .modal-btn.primary:hover:not(:disabled) {
          background-color: #4338ca;
        }

        .modal-btn.primary:disabled {
          background-color: #c7d2fe;
          cursor: not-allowed;
        }

        .modal-btn.secondary {
          background-color: white;
          color: #475569;
          border: 1px solid #e2e8f0;
        }

        .modal-btn.secondary:hover:not(:disabled) {
          background-color: #f8fafc;
        }

        .spinning {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default DocumentUploadModal;
