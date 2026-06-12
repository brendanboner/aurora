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

const TOTAL = QUESTIONS.length;

function isAnswered(q, value) {
  if (value === undefined || value === null) return false;
  if (q.type === 'multi') return Array.isArray(value) && value.length > 0;
  if (q.type === 'text')  return typeof value === 'string' && value.trim().length > 0;
  return true;
}

export default function Survey() {
  const [answers, setAnswers] = useState({});
  const [step, setStep] = useState(0); // 0..TOTAL-1
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState(null);
  const mountedAtRef = useRef(Date.now());

  const q = QUESTIONS[step];

  const doSubmit = async (finalAnswers) => {
    setSubmitting(true);
    setError(null);
    try {
      const durationSeconds = Math.round((Date.now() - mountedAtRef.current) / 1000);
      const cleaned = { ...finalAnswers };
      QUESTIONS.forEach(qq => {
        if (!qq.required && !isAnswered(qq, cleaned[qq.key])) {
          delete cleaned[qq.key];
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

  const advance = (nextAnswers) => {
    if (step >= TOTAL - 1) {
      doSubmit(nextAnswers);
      return;
    }
    setStep(s => Math.min(s + 1, TOTAL - 1));
  };

  // Single-answer click — set + auto-advance
  const pickSingle = (value) => {
    const next = { ...answers, [q.key]: value };
    setAnswers(next);
    advance(next);
  };

  // Multi-select toggle (no auto-advance; user clicks Next)
  const toggleMulti = (value) => {
    setAnswers(prev => {
      const current = Array.isArray(prev[q.key]) ? prev[q.key] : [];
      const updated = current.includes(value)
        ? current.filter(v => v !== value)
        : [...current, value];
      return { ...prev, [q.key]: updated };
    });
  };

  const setText = (value) => {
    setAnswers(prev => ({ ...prev, [q.key]: value }));
  };

  const handleNext = () => {
    advance(answers);
  };

  const handleSkip = () => {
    // Drop any partial value for this optional question, then advance.
    const next = { ...answers };
    delete next[q.key];
    setAnswers(next);
    advance(next);
  };

  const handleBack = () => {
    if (step > 0) setStep(s => s - 1);
  };

  if (submitted) {
    return (
      <div className="survey-root">
        <div className="survey-page">
          <div className="survey-stage">
            <div className="survey-thanks">
              <h1>Thanks for the feedback.</h1>
              <p>This goes straight to the Office of the CTO. You can close this tab.</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const currentAnswer = answers[q.key];
  const currentAnswered = isAnswered(q, currentAnswer);
  const isLast = step === TOTAL - 1;
  const progressPct = ((step) / TOTAL) * 100;

  return (
    <div className="survey-root">
      <div className="survey-page">
        <header className="survey-top">
          <img src="/octo_logo.png" alt="Octo" />
          <div className="wordmark">
            <span className="small">Office of the CTO &mdash; Extreme Networks</span>
            <span className="title">Aurora Quick Feedback</span>
          </div>
        </header>

        <div className="survey-stage">
          <div className="survey-card">
            <div className="survey-step">Question {step + 1} of {TOTAL}</div>
            <div className="survey-progress-bar" aria-hidden="true">
              <div style={{ width: `${progressPct}%` }} />
            </div>

            <p className="q-title">{q.title}</p>

            {q.type === 'stars' && (
              <div className="q-options" role="radiogroup" aria-label={q.title}>
                {[1, 2, 3, 4, 5].map(n => (
                  <button
                    key={n}
                    type="button"
                    className={`q-chip star ${currentAnswer === n ? 'selected' : ''}`}
                    aria-pressed={currentAnswer === n}
                    onClick={() => pickSingle(n)}
                    disabled={submitting}
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
                    className={`q-chip ${currentAnswer === o.value ? 'selected' : ''}`}
                    aria-pressed={currentAnswer === o.value}
                    onClick={() => pickSingle(o.value)}
                    disabled={submitting}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            )}

            {q.type === 'multi' && (
              <>
                <div className="q-options">
                  {q.options.map(o => {
                    const checked = Array.isArray(currentAnswer) && currentAnswer.includes(o.value);
                    return (
                      <button
                        key={o.value}
                        type="button"
                        className={`q-chip ${checked ? 'selected' : ''}`}
                        aria-pressed={checked}
                        onClick={() => toggleMulti(o.value)}
                        disabled={submitting}
                      >
                        {o.label}
                      </button>
                    );
                  })}
                </div>
                <div className="q-actions">
                  {!q.required && !currentAnswered && (
                    <button type="button" className="btn btn-ghost" onClick={handleSkip} disabled={submitting}>
                      Skip
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleNext}
                    disabled={submitting || (q.required && !currentAnswered)}
                  >
                    {isLast ? (submitting ? 'Submitting…' : 'Submit') : 'Next'}
                  </button>
                </div>
              </>
            )}

            {q.type === 'text' && (
              <>
                <textarea
                  className="q-textarea"
                  maxLength={q.maxLength}
                  value={currentAnswer || ''}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Optional"
                  disabled={submitting}
                />
                <div className="q-char-count">
                  {(currentAnswer || '').length} / {q.maxLength}
                </div>
                <div className="q-actions">
                  {!q.required && !currentAnswered && (
                    <button type="button" className="btn btn-ghost" onClick={handleSkip} disabled={submitting}>
                      Skip
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleNext}
                    disabled={submitting || (q.required && !currentAnswered)}
                  >
                    {isLast ? (submitting ? 'Submitting…' : 'Submit') : 'Next'}
                  </button>
                </div>
              </>
            )}

            {error && <div className="survey-error">{error}</div>}
          </div>
        </div>

        <button
          type="button"
          className="survey-back"
          onClick={handleBack}
          aria-hidden={step === 0}
          tabIndex={step === 0 ? -1 : 0}
          disabled={step === 0 || submitting}
        >
          ‹ Back
        </button>
      </div>
    </div>
  );
}
