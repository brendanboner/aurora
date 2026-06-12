import React, { useMemo, useRef, useState } from 'react';
import { submitSurvey } from '../services/api';
import './Survey.css';

const QUESTIONS = [
  {
    key: 'q1_overall_rating',
    title: 'Overall, how would you rate Aurora?',
    required: true,
    type: 'stars',
  },
  {
    key: 'q2_findability',
    title: 'Was it easy to find what you needed?',
    required: true,
    type: 'single',
    options: [
      { value: 'very_easy', label: 'Very easy' },
      { value: 'easy',      label: 'Easy' },
      { value: 'ok',        label: 'OK' },
      { value: 'hard',      label: 'Hard' },
    ],
  },
  {
    key: 'q3_speed',
    title: 'Speed felt…',
    required: true,
    type: 'single',
    options: [
      { value: 'fast', label: 'Fast' },
      { value: 'ok',   label: 'OK' },
      { value: 'slow', label: 'Slow' },
    ],
  },
  {
    key: 'q4_accuracy',
    title: "How accurate were Aurora's answers?",
    required: true,
    type: 'single',
    options: [
      { value: 'very',        label: 'Very accurate' },
      { value: 'mostly',      label: 'Mostly' },
      { value: 'mixed',       label: 'Mixed' },
      { value: 'often_wrong', label: 'Often wrong' },
    ],
  },
  {
    key: 'q5_citation_accuracy',
    title: 'Did Aurora cite the right sources?',
    required: true,
    type: 'single',
    options: [
      { value: 'yes',       label: 'Yes' },
      { value: 'sometimes', label: 'Sometimes' },
      { value: 'rarely',    label: 'Rarely' },
      { value: 'na',        label: 'N/A' },
    ],
  },
  {
    key: 'q6_hallucination',
    title: "Did Aurora invent things that weren't in the sources?",
    required: true,
    type: 'single',
    options: [
      { value: 'never',         label: 'Never' },
      { value: 'once_or_twice', label: 'Once or twice' },
      { value: 'often',         label: 'Often' },
    ],
  },
  {
    key: 'q7_works_best_for',
    title: 'What kind of question worked best? (pick any)',
    required: true,
    type: 'multi',
    options: [
      { value: 'specs',       label: 'Specs' },
      { value: 'people_orgs', label: 'People/orgs' },
      { value: 'events',      label: 'Events' },
      { value: 'trends',      label: 'Trends' },
      { value: 'other',       label: 'Other' },
    ],
  },
  {
    key: 'q8_source_coverage',
    title: 'Were the sources Aurora used the right ones?',
    required: true,
    type: 'single',
    options: [
      { value: 'yes',           label: 'Yes' },
      { value: 'mostly',        label: 'Mostly' },
      { value: 'missing_some',  label: 'Missing some' },
      { value: 'not_really',    label: 'Not really' },
    ],
  },
  {
    key: 'q9_missing_sources',
    title: 'What sources are missing? (optional, pick any)',
    required: false,
    type: 'multi',
    options: [
      { value: 'ietf',          label: 'IETF' },
      { value: 'ieee',          label: 'IEEE' },
      { value: 'vendor_blogs',  label: 'Vendor blogs' },
      { value: 'internal_docs', label: 'Internal docs' },
      { value: 'other',         label: 'Other' },
    ],
  },
  {
    key: 'q10_one_thing',
    title: 'One thing we should fix or add? (optional)',
    required: false,
    type: 'text',
    maxLength: 500,
  },
  {
    key: 'q11_would_use_again',
    title: 'Would you use Aurora again?',
    required: true,
    type: 'single',
    options: [
      { value: 'web',      label: 'Yes (web)' },
      { value: 'teams',    label: 'Yes (Teams)' },
      { value: 'both',     label: 'Both' },
      { value: 'no',       label: 'No' },
      { value: 'not_sure', label: 'Not sure' },
    ],
  },
];

const REQUIRED_KEYS = QUESTIONS.filter(q => q.required).map(q => q.key);

function isAnswered(q, value) {
  if (value === undefined || value === null) return false;
  if (q.type === 'multi') return Array.isArray(value) && value.length > 0;
  if (q.type === 'text')  return typeof value === 'string' && value.trim().length > 0;
  return true;
}

export default function Survey() {
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState(null);
  const mountedAtRef = useRef(Date.now());

  const setAnswer = (key, value) => {
    setAnswers(prev => ({ ...prev, [key]: value }));
  };

  const toggleMulti = (key, value) => {
    setAnswers(prev => {
      const current = Array.isArray(prev[key]) ? prev[key] : [];
      const next = current.includes(value)
        ? current.filter(v => v !== value)
        : [...current, value];
      return { ...prev, [key]: next };
    });
  };

  const answeredCount = useMemo(
    () => QUESTIONS.filter(q => isAnswered(q, answers[q.key])).length,
    [answers]
  );

  const allRequiredAnswered = useMemo(
    () => REQUIRED_KEYS.every(k => isAnswered(QUESTIONS.find(q => q.key === k), answers[k])),
    [answers]
  );

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const durationSeconds = Math.round((Date.now() - mountedAtRef.current) / 1000);
      const cleaned = { ...answers };
      QUESTIONS.forEach(q => {
        if (!q.required && !isAnswered(q, cleaned[q.key])) {
          delete cleaned[q.key];
        }
      });
      await submitSurvey(cleaned, durationSeconds);
      setSubmitted(true);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Survey submit failed:', err);
      setError(
        err?.response?.data?.detail
        ?? 'Could not submit. Please try again in a moment.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="survey-root">
        <div className="survey-shell survey-thanks">
          <h1>Thanks for the feedback.</h1>
          <p>This goes straight to the Office of the CTO. You can close this tab.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="survey-root">
      <div className="survey-shell">
        <header className="survey-header">
          <img src="/octo_logo.png" alt="Octo" />
          <div className="wordmark">
            <span className="small">Office of the CTO &mdash; Extreme Networks</span>
            <span className="title">Aurora Quick Feedback</span>
          </div>
        </header>

        <div className="survey-progress" aria-live="polite">
          <span>{answeredCount} of {QUESTIONS.length} answered &middot; takes ~2 minutes</span>
          <div className="survey-progress-bar">
            <div style={{ width: `${(answeredCount / QUESTIONS.length) * 100}%` }} />
          </div>
        </div>

        {QUESTIONS.map(q => (
          <div className="q-card" key={q.key}>
            <p className="q-title">
              {q.title}
              {q.required && <span className="req" aria-hidden="true">*</span>}
            </p>

            {q.type === 'stars' && (
              <div className="q-options" role="radiogroup" aria-label={q.title}>
                {[1, 2, 3, 4, 5].map(n => (
                  <button
                    key={n}
                    type="button"
                    className={`q-chip star ${answers[q.key] === n ? 'selected' : ''}`}
                    aria-pressed={answers[q.key] === n}
                    onClick={() => setAnswer(q.key, n)}
                  >
                    {'★'.repeat(n)}{'☆'.repeat(5 - n)}
                  </button>
                ))}
              </div>
            )}

            {q.type === 'single' && (
              <div className="q-options" role="radiogroup" aria-label={q.title}>
                {q.options.map(o => (
                  <button
                    key={o.value}
                    type="button"
                    className={`q-chip ${answers[q.key] === o.value ? 'selected' : ''}`}
                    aria-pressed={answers[q.key] === o.value}
                    onClick={() => setAnswer(q.key, o.value)}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            )}

            {q.type === 'multi' && (
              <div className="q-options">
                {q.options.map(o => {
                  const checked = Array.isArray(answers[q.key]) && answers[q.key].includes(o.value);
                  return (
                    <button
                      key={o.value}
                      type="button"
                      className={`q-chip ${checked ? 'selected' : ''}`}
                      aria-pressed={checked}
                      onClick={() => toggleMulti(q.key, o.value)}
                    >
                      {o.label}
                    </button>
                  );
                })}
              </div>
            )}

            {q.type === 'text' && (
              <>
                <textarea
                  className="q-textarea"
                  maxLength={q.maxLength}
                  value={answers[q.key] || ''}
                  onChange={(e) => setAnswer(q.key, e.target.value)}
                  placeholder="Optional"
                />
                <div className="q-char-count">
                  {(answers[q.key] || '').length} / {q.maxLength}
                </div>
              </>
            )}
          </div>
        ))}

        {error && <div className="survey-error">{error}</div>}

        <div className="survey-submit">
          <button
            type="button"
            disabled={!allRequiredAnswered || submitting}
            onClick={handleSubmit}
          >
            {submitting ? 'Submitting…' : 'Submit feedback'}
          </button>
        </div>
      </div>
    </div>
  );
}
