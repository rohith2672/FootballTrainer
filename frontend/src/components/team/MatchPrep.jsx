import { useMemo } from 'react';
import ExplanationPanel from '../ExplanationPanel';
import { isTeamNotFound } from '../../api';
import { useH2H } from '../../hooks/useH2H';
import { explanationContent } from '../../lib/explain.js';
import { formatKickoff, leagueInfo, normalizeMatches, outcomeLabel, pct } from '../../lib/matches.js';
import { shortTeamName } from '../../lib/teams.js';
import {
  fixtureSides,
  fmtDate,
  h2hRecordText,
  meetingResult,
  noFixtureMessage,
  restGapText,
} from '../../lib/teamPage.js';
import { Card, ResultChip, Skeleton, TeamLink } from './common';

// Same thresholds and classes as the fixture cards on the Upcoming page.
const MIN_LABEL_SHARE = 0.14;

function ProbabilityBar({ match }) {
  const segments = [
    { key: 'home', field: 'home_win', label: `${shortTeamName(match.home_team)} win` },
    { key: 'draw', field: 'draw', label: 'Draw' },
    { key: 'away', field: 'away_win', label: `${shortTeamName(match.away_team)} win` },
  ];
  const description = segments.map((s) => `${s.label} ${pct(match[s.field])}`).join(', ');
  return (
    <div className="prediction-section prep-prediction">
      <p className="outcome-headline">
        <span className={`outcome-dot ${match.outcome}`} aria-hidden="true" />
        <span>
          {outcomeLabel(match)}
          <span className="outcome-confidence"> · {pct(match.confidence)}</span>
        </span>
      </p>
      <div className="probability-bar-track" role="img" aria-label={description}>
        {segments.map(({ key, field }) =>
          match[field] > 0 ? (
            <div key={key} className={`prob-segment ${key}`} style={{ flexGrow: match[field] }}>
              {match[field] >= MIN_LABEL_SHARE ? pct(match[field]) : ''}
            </div>
          ) : null,
        )}
      </div>
      <div className="prob-chips">
        {segments.map(({ key, field, label }) => (
          <div key={key} className={`prob-chip ${key} ${match.outcome === key ? 'highest' : ''}`}>
            <span className="chip-label">
              <span className={`chip-swatch ${key}`} aria-hidden="true" />
              {label}
            </span>
            <span className="chip-value">{pct(match[field])}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function HeadToHead({ team, opponent }) {
  const { data, loading, error, reload } = useH2H(team, opponent, { limit: 5 });
  let body;
  if (error) {
    body = isTeamNotFound(error) ? (
      <p className="tp-muted">No match history on record for {opponent}, so there is no head-to-head.</p>
    ) : (
      <p className="tp-muted">
        Head-to-head record unavailable right now.{' '}
        <button type="button" className="link-btn" onClick={reload}>Retry</button>
      </p>
    );
  } else if (!data || loading) {
    body = <Skeleton lines={2} />;
  } else {
    body = (
      <>
        <p className="prep-h2h-summary">{h2hRecordText(data)}</p>
        {data.meetings.length ? (
          <ul className="h2h-list">
            {data.meetings.map((m, i) => (
              <li key={`${m.date}-${i}`} className="h2h-row">
                <span className="h2h-date">{fmtDate(m.date)}</span>
                <span className="h2h-score">
                  {shortTeamName(m.home_team)} {m.home_goals}–{m.away_goals} {shortTeamName(m.away_team)}
                </span>
                <ResultChip result={meetingResult(m, team)} />
              </li>
            ))}
          </ul>
        ) : null}
      </>
    );
  }
  return (
    <div className="prep-block">
      <h4 className="prep-subtitle">Head-to-head</h4>
      {body}
    </div>
  );
}

/** The team's next fixture: prediction, rest, head-to-head and model factors. */
function MatchPrep({ profile }) {
  const { name, next_fixture: fixture, next_fixture_status: status, as_of: asOf } = profile;
  const match = useMemo(
    () => (fixture && typeof fixture === 'object' ? normalizeMatches([fixture])[0] : null),
    [fixture],
  );
  const sides = useMemo(() => fixtureSides(match, name), [match, name]);

  if (status !== 'ok' || !match || !sides) {
    const { title, message } = noFixtureMessage(status === 'ok' ? 'unavailable' : status, name, asOf);
    return (
      <Card title="Match preparation" wide className="prep-card">
        <div className="prep-empty">
          <p>
            <strong>{title}.</strong> {message}
          </p>
        </div>
      </Card>
    );
  }

  const kickoff = formatKickoff(match);
  const explanation = explanationContent(match);
  const rest = restGapText(sides, name);
  const competition = leagueInfo(match.league);

  return (
    <Card title="Match preparation" wide className="prep-card">
      <div className="prep-fixture">
        <p className="prep-when">
          <time dateTime={kickoff.iso}>{kickoff.text}</time>
          <span aria-hidden="true"> · </span>
          <span>
            <span aria-hidden="true">{competition.emoji} </span>
            {competition.name}
          </span>
        </p>
        <p className="prep-teams">
          <span className={`venue-chip ${sides.venue}`}>{sides.isHome ? 'Home' : 'Away'}</span>
          <span>
            {sides.isHome ? 'vs ' : 'at '}
            <TeamLink name={sides.opponent} className="prep-opponent" />
          </span>
        </p>
      </div>

      {match.hasPrediction ? (
        <ProbabilityBar match={match} />
      ) : (
        <p className="no-prediction">
          <strong>No prediction</strong> — {match.noPredictionReason}
        </p>
      )}

      <div className="prep-grid">
        <div className="prep-block">
          <h4 className="prep-subtitle">Rest before kickoff</h4>
          <p>{rest ?? 'Days since the last match aren’t known for this fixture.'}</p>
        </div>
        <HeadToHead team={name} opponent={sides.opponent} />
      </div>

      {explanation.any ? (
        <div className="match-details">
          <ExplanationPanel match={match} factors={explanation.factors} details={explanation.details} />
        </div>
      ) : null}
      {match.model_version ? <p className="team-note">Model: {match.model_version}</p> : null}
    </Card>
  );
}

export default MatchPrep;
