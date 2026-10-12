import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import './DocumentUpload.css';
import {
  UploadIcon,
  FileTextIcon,
  TrashIcon,
  CheckIcon,
  AlertCircleIcon,
  RefreshIcon,
} from '../components/icons';
import {
  uploadDocuments,
  getDocumentCategories,
  getUserUploads,
} from '../services/api';

const SUPPORTED_EXTENSIONS = ['.pdf', '.docx', '.pptx', '.xlsx', '.txt', '.md'];
const MAX_FILE_SIZE_MB = 50;

const DocumentUpload = () => {
  const navigate = useNavigate();
  
  // Staged files for upload
  const [stagedFiles, setStagedFiles] = useState([]);
  
  // Available options
  const [categories, setCategories] = useState([]);
  
  // Previously uploaded documents
  const [userUploads, setUserUploads] = useState([]);
  
  // UI state
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [dragActive, setDragActive] = useState(false);

  // Fetch initial data
  useEffect(() => {
    fetchCategories();
    fetchUserUploads();
  }, []);

  const fetchCategories = async () => {
    try {
      const data = await getDocumentCategories();
      setCategories(data.categories || []);
    } catch (err) {
      console.error('Error fetching categories:', err);
    }
  };

  const fetchUserUploads = async () => {
    try {
      const data = await getUserUploads();
      setUserUploads(data.documents || []);
    } catch (err) {
      console.error('Error fetching user uploads:', err);
    }
  };

  // File validation
  const validateFile = (file) => {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      return `Unsupported file type: ${ext}. Supported: ${SUPPORTED_EXTENSIONS.join(', ')}`;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      return `File too large. Maximum size: ${MAX_FILE_SIZE_MB}MB`;
    }
    return null;
  };

  // Handle file selection
  const handleFiles = useCallback((files) => {
    const newStagedFiles = Array.from(files).map(file => {
      const validationError = validateFile(file);
      return {
        file,
        title: file.name.replace(/\.[^/.]+$/, ''), // Remove extension
        category: 'general',
        error: validationError,
        id: Math.random().toString(36).substr(2, 9),
      };
    });
    setStagedFiles(prev => [...prev, ...newStagedFiles]);
    setError(null);
    setSuccess(null);
  }, []);

  // Drag and drop handlers
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

  // Update staged file
  const updateStagedFile = (id, field, value) => {
    setStagedFiles(prev => prev.map(f => 
      f.id === id ? { ...f, [field]: value } : f
    ));
  };

  // Remove staged file
  const removeStagedFile = (id) => {
    setStagedFiles(prev => prev.filter(f => f.id !== id));
  };

  // Handle upload
  const handleUpload = async () => {
    const validFiles = stagedFiles.filter(f => !f.error);
    if (validFiles.length === 0) {
      setError('No valid files to upload');
      return;
    }

    setUploading(true);
    setError(null);
    setSuccess(null);

    try {
      const formData = new FormData();
      
      // Add files
      validFiles.forEach(f => {
        formData.append('files', f.file);
      });
      
      // Add titles and categories as JSON arrays
      formData.append('titles', JSON.stringify(validFiles.map(f => f.title)));
      formData.append('categories', JSON.stringify(validFiles.map(f => f.category)));

      const result = await uploadDocuments(formData);
      
      if (result.total_success > 0) {
        // If all files uploaded successfully, redirect to My Documents
        if (result.total_failed === 0) {
          navigate('/my-documents', { 
            state: { message: `Successfully uploaded ${result.total_success} document(s)` } 
          });
          return;
        }
        
        // Partial success - stay on page and show which succeeded
        setSuccess(`Successfully uploaded ${result.total_success} document(s)`);
        // Clear successfully uploaded files
        const successfulFilenames = result.documents
          .filter(d => d.status === 'queued')
          .map(d => d.original_filename);
        setStagedFiles(prev => prev.filter(f => !successfulFilenames.includes(f.file.name)));
        // Refresh user uploads
        fetchUserUploads();
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

  return (
    <div className="document-upload-container">
      <div className="upload-header">
        <h1><UploadIcon size={32} /> Upload Documents</h1>
        <p>Upload documents to add to the Aurora knowledge graph. Supported formats: PDF, Word, PowerPoint, Excel, Text, Markdown</p>
      </div>

      {error && (
        <div className="upload-message error">
          <AlertCircleIcon size={20} />
          {error}
        </div>
      )}

      {success && (
        <div className="upload-message success">
          <CheckIcon size={20} />
          {success}
        </div>
      )}

      {/* Drag and Drop Zone */}
      <div
        className={`drop-zone ${dragActive ? 'active' : ''}`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <UploadIcon size={48} />
        <p>Drag and drop files here, or click to browse</p>
        <input
          type="file"
          multiple
          accept={SUPPORTED_EXTENSIONS.join(',')}
          onChange={(e) => handleFiles(e.target.files)}
          className="file-input"
        />
        <span className="supported-formats">
          Supported: {SUPPORTED_EXTENSIONS.join(', ')}
        </span>
      </div>

      {/* Staged Files */}
      {stagedFiles.length > 0 && (
        <div className="staged-files-section">
          <h2>Documents to Upload ({stagedFiles.length})</h2>
          
          <div className="staged-files-list">
            {stagedFiles.map(stagedFile => (
              <div 
                key={stagedFile.id} 
                className={`staged-file-item ${stagedFile.error ? 'has-error' : ''}`}
              >
                <div className="staged-file-header">
                  <FileTextIcon size={24} />
                  <span className="filename">{stagedFile.file.name}</span>
                  <span className="filesize">
                    {(stagedFile.file.size / 1024 / 1024).toFixed(2)} MB
                  </span>
                  <button 
                    className="remove-button"
                    onClick={() => removeStagedFile(stagedFile.id)}
                  >
                    <TrashIcon size={16} />
                  </button>
                </div>

                {stagedFile.error ? (
                  <div className="file-error">
                    <AlertCircleIcon size={16} />
                    {stagedFile.error}
                  </div>
                ) : (
                  <div className="staged-file-details">
                    <div className="form-row">
                      <label>Title:</label>
                      <input
                        type="text"
                        value={stagedFile.title}
                        onChange={(e) => updateStagedFile(stagedFile.id, 'title', e.target.value)}
                        placeholder="Document title"
                      />
                    </div>

                    <div className="form-row">
                      <label>Category:</label>
                      <select
                        value={stagedFile.category}
                        onChange={(e) => updateStagedFile(stagedFile.id, 'category', e.target.value)}
                      >
                        {categories.map(cat => (
                          <option key={cat.id} value={cat.id}>
                            {cat.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="upload-actions">
            <button
              className="upload-button primary"
              onClick={handleUpload}
              disabled={uploading || stagedFiles.every(f => f.error)}
            >
              {uploading ? (
                <>
                  <RefreshIcon size={20} className="spinning" />
                  Uploading...
                </>
              ) : (
                <>
                  <UploadIcon size={20} />
                  Upload {stagedFiles.filter(f => !f.error).length} Document(s)
                </>
              )}
            </button>
            <button
              className="upload-button secondary"
              onClick={() => setStagedFiles([])}
              disabled={uploading}
            >
              Clear All
            </button>
          </div>
        </div>
      )}

      {/* Previously Uploaded Documents */}
      {userUploads.length > 0 && (
        <div className="previous-uploads-section">
          <h2>Your Previously Uploaded Documents</h2>
          <div className="uploads-list">
            {userUploads.map(doc => (
              <div key={doc.url_hash} className="upload-item">
                <FileTextIcon size={20} />
                <div className="upload-info">
                  <span className="upload-title">{doc.title}</span>
                  <span className="upload-category">{doc.category}</span>
                </div>
                <span className="upload-date">
                  {doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString() : 'N/A'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default DocumentUpload;
