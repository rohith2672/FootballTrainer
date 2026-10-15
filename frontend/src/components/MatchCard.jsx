import ExplanationPanel from './ExplanationPanel';
import { explanationContent } from '../lib/explain';
import { formatKickoff, outcomeLabel, pct } from '../lib/matches';

const SEGMENTS = [
  { key: 'home', field: 'home_win', label: 'Home win' },
  { key: 'draw', field: 'draw', label: 'Draw' },
  { key: 'away', field: 'away_win', label: 'Away win' },
];

// Segments narrower than this don't have room for an in-bar percentage; the
// chips underneath always carry the text.
const MIN_LABEL_SHARE = 0.14;

/**
 * One fixture. The "why this prediction" disclosure renders in the details
 * region when the API supplied top_factors / details; `children` render after it.
 */
function MatchCard({ match, headingLevel = 4, children }) {
  const kickoff = formatKickoff(match);
  const Heading = `h${headingLevel}`;
  const explanation = explanationContent(match);

  const barDescription = SEGMENTS.map(
    ({ label, field }) => `${label} ${pct(match[field])}`,
  ).join(', ');

  return (
    <article className="match-card" data-has-prediction={match.hasPrediction}>
      <div className="match-date">
        <span className="date-icon" aria-hidden="true">{'\u{1F4C5}'}</span>
        <time dateTime={kickoff.iso}>{kickoff.text}</time>
      </div>

      <Heading className="teams">
        <span className="team">{match.home_team}</span>
        <span className="vs-badge" aria-hidden="true">VS</span>
        <span className="sr-only"> versus </span>
        <span className="team">{match.away_team}</span>
      </Heading>

      {match.hasPrediction ? (
        <div className="prediction-section">
          <p className="outcome-headline">
            <span className={`outcome-dot ${match.outcome}`} aria-hidden="true" />
            <span>
              {outcomeLabel(match)}
              <span className="outcome-confidence"> · {pct(match.confidence)}</span>
            </span>
          </p>

          <div className="probability-bar-track" role="img" aria-label={barDescription}>
            {SEGMENTS.map(({ key, field }) =>
              match[field] > 0 ? (
                <div
                  key={key}
                  className={`prob-segment ${key}`}
                  style={{ flexGrow: match[field] }}
                >
                  {match[field] >= MIN_LABEL_SHARE ? pct(match[field]) : ''}
                </div>
              ) : null,
            )}
          </div>

          <div className="prob-chips">
            {SEGMENTS.map(({ key, field, label }) => (
              <div
                key={key}
                className={`prob-chip ${key} ${match.outcome === key ? 'highest' : ''}`}
              >
                <span className="chip-label">
                  <span className={`chip-swatch ${key}`} aria-hidden="true" />
                  {label}
                </span>
                <span className="chip-value">{pct(match[field])}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="prediction-section">
          <p className="no-prediction">
            <strong>No prediction</strong> — {match.noPredictionReason}
          </p>
        </div>
      )}

      {explanation.any || children ? (
        <div className="match-details">
          {explanation.any ? (
            <ExplanationPanel match={match} factors={explanation.factors} details={explanation.details} />
          ) : null}
          {children}
        </div>
      ) : null}
    </article>
  );
}

export default MatchCard;
