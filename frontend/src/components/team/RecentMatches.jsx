import { describeTeamError } from '../../api';
import { leagueInfo } from '../../lib/matches.js';
import { formatEloChange } from '../../lib/teams.js';
import {
  MATCH_LIMITS,
  VENUE_LABELS,
  VENUE_OPTIONS,
  canShowMore,
  eloDelta,
  fmtDate,
  fmtScore,
  plural,
} from '../../lib/teamPage.js';
import { Card, ResultChip, SectionNotice, Skeleton, TeamLink } from './common';

function VenueFilter({ venue, onChange, disabled }) {
  return (
    <div className="tp-segmented" role="group" aria-label="Venue">
      {VENUE_OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          className={`tp-segmented-btn ${venue === o.value ? 'active' : ''}`}
          aria-pressed={venue === o.value}
          onClick={() => onChange(o.value)}
          disabled={disabled && venue !== o.value}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function MatchRow({ row }) {
  const delta = eloDelta(row);
  const competition = leagueInfo(row.league);
  const venue = VENUE_LABELS[row.venue];
  return (
    <li className="match-row">
      <div className="match-row-meta">
        <time dateTime={row.date}>{fmtDate(row.date)}</time>
        <span className="match-row-comp" title={competition.name}>
          <span aria-hidden="true">{competition.emoji} </span>
          {competition.name}
        </span>
      </div>
      <div className="match-row-main">
        <span className={`venue-chip ${row.venue}`} title={venue}>
          <span aria-hidden="true">{venue ? venue[0] : '?'}</span>
          <span className="sr-only">{venue ?? 'Venue unknown'}</span>
        </span>
        <span className="match-row-opp">
          <span className="sr-only">{row.venue === 'away' ? 'at ' : 'vs '}</span>
          <TeamLink name={row.opponent} />
        </span>
        <span className="match-row-score">{fmtScore(row)}</span>
        <ResultChip result={row.result} />
        <span
          className={`match-row-elo ${delta > 0 ? 'up' : delta < 0 ? 'down' : ''}`}
          title="Elo rating change from this match"
        >
          <span className="sr-only">Elo change </span>
          {formatEloChange(delta)}
        </span>
      </div>
    </li>
  );
}

/** Newest-first match list with a venue filter and "show more". */
function RecentMatches({ matches, error, venue, onVenueChange, limit, onShowMore, loading, onRetry }) {
  const rows = Array.isArray(matches) ? matches : null;
  const venueText = venue === 'all' ? '' : ` ${venue}`;
  const noun = venue === 'all' ? 'match' : `${venue} match`;

  let body;
  if (!rows && error) {
    const { title, message } = describeTeamError(error);
    body = <SectionNotice title={title} message={message} onRetry={onRetry} busy={loading} />;
  } else if (!rows) {
    body = <Skeleton lines={6} />;
  } else if (!rows.length) {
    body = <p className="tp-muted">No{venueText} matches on record.</p>;
  } else {
    body = (
      <>
        <ol className="match-rows">
          {rows.map((row, i) => (
            <MatchRow key={`${row.date}-${row.opponent}-${i}`} row={row} />
          ))}
        </ol>
        <div className="match-rows-foot">
          <span className="team-note" aria-live="polite">
            Showing the latest {plural(rows.length, `${noun}`, `${noun}es`)}
          </span>
          {canShowMore(rows, limit) ? (
            <button type="button" className="btn btn-small" onClick={onShowMore} disabled={loading}>
              {loading ? 'Loading…' : `Show more (up to ${MATCH_LIMITS.more})`}
            </button>
          ) : null}
        </div>
      </>
    );
  }

  return (
    <Card
      title="Recent matches"
      wide
      busy={loading}
      actions={<VenueFilter venue={venue} onChange={onVenueChange} disabled={false} />}
    >
      {rows && error ? (
        <SectionNotice
          title="Couldn’t update the match list"
          message="Showing the last loaded matches."
          onRetry={onRetry}
          busy={loading}
        />
      ) : null}
      <div className={loading && rows ? 'is-stale' : undefined}>{body}</div>
    </Card>
  );
}

export default RecentMatches;
