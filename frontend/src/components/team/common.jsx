import { useId } from 'react';
import { formDots, formSummary, teamHref } from '../../lib/teams.js';
import { RESULT_LABELS } from '../../lib/teamPage.js';

/** Card with an h3 heading; `wide` spans both columns of the team grid. */
export function Card({ title, actions = null, wide = false, busy = false, className = '', children }) {
  const id = useId();
  return (
    <section
      className={`team-card ${wide ? 'wide' : ''} ${className}`.trim()}
      aria-labelledby={id}
      aria-busy={busy || undefined}
    >
      <div className="team-card-head">
        <h3 id={id} className="team-card-title">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Inline notice for a section that failed while the rest of the page loaded. */
export function SectionNotice({ title, message, onRetry, busy = false }) {
  return (
    <div className="section-notice" role="alert">
      <p>
        <strong>{title}.</strong> {message}
      </p>
      {onRetry ? (
        <button type="button" className="btn btn-small" onClick={onRetry} disabled={busy}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

/** Grey placeholder blocks while a section loads. */
export function Skeleton({ lines = 3, tall = false }) {
  return (
    <div className={`skeleton ${tall ? 'tall' : ''}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton-line" />
      ))}
    </div>
  );
}

/** W / D / L chip; the letter and a hidden word carry the meaning, not colour. */
export function ResultChip({ result }) {
  const label = RESULT_LABELS[result];
  if (!label) return <span className="result-chip none">–</span>;
  return (
    <span className={`result-chip r-${result}`} title={label}>
      <span aria-hidden="true">{result}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

/** Last-five form as lettered dots, oldest first, with a spoken summary. */
export function FormDots({ last5 }) {
  const dots = formDots(last5);
  if (!dots.length) return <span className="tp-muted">No recent matches</span>;
  return (
    <ol className="form-dots" aria-label={formSummary(last5)}>
      {dots.map((d, i) => (
        <li key={i} className={`form-dot r-${d.result}`} title={d.label}>
          <span aria-hidden="true">{d.result}</span>
        </li>
      ))}
    </ol>
  );
}

/** Link to a team's page. */
export function TeamLink({ name, className = '', children }) {
  if (!name) return <span className={className}>{children ?? 'Unknown'}</span>;
  return (
    <a className={`tp-team-link ${className}`.trim()} href={teamHref(name)}>
      {children ?? name}
    </a>
  );
}
