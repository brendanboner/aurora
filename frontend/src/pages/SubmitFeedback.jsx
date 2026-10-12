import React, { useState } from 'react';
import { FeedbackIcon, CheckIcon, WarningIcon } from '../components/icons';
import { submitFeedback } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import './SubmitFeedback.css';

const SubmitFeedback = () => {
  useAuth();
  const [feedbackText, setFeedbackText] = useState('');
  const [category, setCategory] = useState('feedback');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState('');

  const categories = [
    { value: 'feedback', label: 'General Feedback', description: 'Suggestions, comments, or general thoughts' },
    { value: 'bug', label: 'Bug Report', description: 'Something not working as expected' },
    { value: 'accessibility', label: 'Accessibility Issue', description: 'Problems with accessibility or usability' },
    { value: 'styling', label: 'Styling/UI Issue', description: 'Visual or layout problems' }
  ];

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!feedbackText.trim()) {
      setError('Please enter your feedback');
      return;
    }

    setSubmitting(true);
    setError(null);
    setSuccessMessage('');

    try {
      await submitFeedback(feedbackText, category);
      setSuccessMessage('Thank you! Your feedback has been submitted successfully.');
      setFeedbackText('');
      setCategory('feedback');
      
      // Clear success message after 5 seconds
      setTimeout(() => {
        setSuccessMessage('');
      }, 5000);
    } catch (err) {
      console.error('Error submitting feedback:', err);
      setError(err.response?.data?.detail || 'Failed to submit feedback. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="submit-feedback-container">
      <div className="submit-feedback-header">
        <h1>
          <FeedbackIcon size={32} />
          Submit Feedback
        </h1>
        <p>Help us improve Aurora by sharing your feedback, reporting bugs, or suggesting enhancements</p>
      </div>

      {successMessage && (
        <div className="feedback-success-message">
          <CheckIcon size={20} />
          <span>{successMessage}</span>
        </div>
      )}

      {error && (
        <div className="feedback-error-message">
          <WarningIcon size={20} />
          <span>{error}</span>
        </div>
      )}

      <div className="feedback-form-card">
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="category">
              Category <span className="required">*</span>
            </label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              disabled={submitting}
              className="feedback-select"
            >
              {categories.map(cat => (
                <option key={cat.value} value={cat.value}>
                  {cat.label}
                </option>
              ))}
            </select>
            <div className="category-description">
              {categories.find(c => c.value === category)?.description}
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="feedbackText">
              Your Feedback <span className="required">*</span>
            </label>
            <textarea
              id="feedbackText"
              value={feedbackText}
              onChange={(e) => setFeedbackText(e.target.value)}
              placeholder="Please describe your feedback in detail..."
              disabled={submitting}
              className="feedback-textarea"
              rows={8}
              maxLength={5000}
            />
            <div className="character-count">
              {feedbackText.length} / 5000 characters
            </div>
          </div>

          <div className="form-actions">
            <button
              type="submit"
              disabled={submitting || !feedbackText.trim()}
              className="btn-submit-feedback"
            >
              {submitting ? 'Submitting...' : 'Submit Feedback'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default SubmitFeedback;
