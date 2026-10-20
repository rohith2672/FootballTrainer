import { MAX_FAVOURITES } from '../../lib/favourites.js';
import { leagueInfo } from '../../lib/matches.js';
import { DASH, formatAverage, formatElo, formatEloChange, formatRank } from '../../lib/teams.js';
import { fmtDate, plural } from '../../lib/teamPage.js';
import StarToggle from './StarToggle';
import { FormDots } from './common';

function Stat({ label, value, note }) {
  return (
    <div className="team-stat">
      <dt className="team-stat-label">{label}</dt>
      <dd className="team-stat-value">{value}</dd>
      {note ? <dd className="team-stat-note">{note}</dd> : null}
    </div>
  );
}

function PrimaryControl({ name, favourites }) {
  if (favourites.primary === name) {
    return (
      <span className="tp-primary-tag">
        <span aria-hidden="true">★ </span>Your primary team
      </span>
    );
  }
  const full = !favourites.isFavourite(name) && favourites.teams.length >= MAX_FAVOURITES;
  return (
    <button
      type="button"
      className="btn btn-small"
      onClick={() => favourites.setPrimary(name)}
      disabled={full}
    >
      Make primary team
    </button>
  );
}

/** Name, league, favourite controls and the headline numbers for a team. */
function TeamHeader({ profile, favourites, onOpenPicker }) {
  const { name, league, elo = {}, form = {}, rest_days: restDays, last_match_date: lastMatch } = profile;
  const info = league ? leagueInfo(league) : null;
  const change = elo?.change_last_5;
  const changeClass = typeof change === 'number' ? (change > 0 ? 'up' : change < 0 ? 'down' : '') : '';

  return (
    <header className="team-header">
      <div className="team-title-row">
        <div className="team-title-block">
          <h2 className="team-name">{name}</h2>
          <div className="team-meta">
            <span className="league-badge">
              {info ? <span aria-hidden="true">{info.emoji}</span> : null}
              {info ? info.name : 'No domestic league on record'}
            </span>
            {lastMatch ? (
              <span className="team-meta-item">
                Last match {fmtDate(lastMatch)}
                {Number.isInteger(restDays) ? ` · ${plural(restDays, 'day')} ago` : ''}
              </span>
            ) : null}
          </div>
        </div>
        <div className="team-actions">
          <StarToggle name={name} favourites={favourites} label />
          <PrimaryControl name={name} favourites={favourites} />
          {onOpenPicker ? (
            <button type="button" className="btn btn-small" onClick={onOpenPicker}>
              Choose teams
            </button>
          ) : null}
        </div>
      </div>

      <dl className="team-stats">
        <Stat label="Elo rating" value={formatElo(elo?.rating)} note="After the latest match" />
        <Stat
          label="League rank"
          value={formatRank(elo?.rank_in_league, elo?.league_size)}
          note={league ? 'By Elo rating' : 'No domestic league'}
        />
        <Stat
          label="Elo change"
          value={<span className={`elo-change ${changeClass}`}>{formatEloChange(change)}</span>}
          note="Over the last 5 matches"
        />
        <div className="team-stat team-stat-form">
          <dt className="team-stat-label">Form</dt>
          <dd className="team-stat-value">
            <FormDots last5={form?.last5} />
          </dd>
          <dd className="team-stat-note">
            {Number.isInteger(form?.n) && form.n > 0
              ? `${formatAverage(form.pts_pg, 2)} points per game · oldest first`
              : DASH}
          </dd>
        </div>
      </dl>
    </header>
  );
}

export default TeamHeader;
