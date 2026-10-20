import ExplanationPanel from './ExplanationPanel';
import { CalendarIcon, StarIcon } from './icons';
import { useFavourites } from '../hooks/useFavourites';
import { explanationContent } from '../lib/explain';
import { MAX_FAVOURITES } from '../lib/favourites';
import { formatKickoff, outcomeLabel, pct } from '../lib/matches';
import { teamSnapshot } from '../lib/dashboard';
import { teamHref } from '../lib/teams';
import '../styles/favourites.css';

const SEGMENTS = [
  { key: 'home', field: 'home_win', label: 'Home win' },
  { key: 'draw', field: 'draw', label: 'Draw' },
  { key: 'away', field: 'away_win', label: 'Away win' },
];

// Segments narrower than this don't have room for an in-bar percentage; the
// chips underneath always carry the text.
const MIN_LABEL_SHARE = 0.14;

/** Star toggle for one team. Full list: stays focusable but explains the limit. */
function FavouriteStar({ name, on, full, onToggle }) {
  const blocked = !on && full;
  const label = on
    ? `Remove ${name} from my teams`
    : blocked
      ? `Add ${name} to my teams (limit of ${MAX_FAVOURITES} teams reached)`
      : `Add ${name} to my teams`;
  return (
    <button
      type="button"
      className={`fav-star ${on ? 'on' : ''}`}
      aria-pressed={on}
      aria-label={label}
      aria-disabled={blocked || undefined}
      title={blocked ? `You can follow up to ${MAX_FAVOURITES} teams` : undefined}
      onClick={() => {
        if (!blocked) onToggle(name);
      }}
    >
      <StarIcon filled={on} size={22} />
    </button>
  );
}

function TeamTools({ match, side, name, favourites }) {
  const snapshot = teamSnapshot(match, side);
  const on = favourites.isFavourite(name);
  return (
    <div className={`team-tools ${side}`}>
      <FavouriteStar
        name={name}
        on={on}
        full={favourites.teams.length >= MAX_FAVOURITES}
        onToggle={favourites.toggle}
      />
      {snapshot ? (
        <span className="team-snapshot">
          <span aria-hidden="true">{snapshot.text}</span>
          <span className="sr-only">
            {name}: {snapshot.label}
          </span>
        </span>
      ) : null}
    </div>
  );
}

/**
 * One fixture. The "why this prediction" disclosure renders in the details
 * region when the API supplied top_factors / details; `children` render after it.
 * `id` (optional) is set on the article so other controls can scroll to it.
 * `index` (optional) is the card's position in its grid; it staggers the
 * entrance animation (capped in CSS).
 */
function MatchCard({ match, headingLevel = 4, id, index, children }) {
  const favourites = useFavourites();
  const kickoff = formatKickoff(match);
  const Heading = `h${headingLevel}`;
  const explanation = explanationContent(match);

  const homeFav = favourites.isFavourite(match.home_team);
  const awayFav = favourites.isFavourite(match.away_team);
  const isFav = homeFav || awayFav;

  const barDescription = SEGMENTS.map(
    ({ label, field }) => `${label} ${pct(match[field])}`,
  ).join(', ');

  return (
    <article
      className={`match-card ${isFav ? 'is-favourite' : ''}`}
      data-has-prediction={match.hasPrediction}
      data-favourite={isFav || undefined}
      id={id}
      tabIndex={id ? -1 : undefined}
      style={Number.isInteger(index) ? { '--i': index } : undefined}
    >
      <div className="match-card-top">
        <div className="match-date">
          <CalendarIcon size={15} className="date-icon" />
          <time dateTime={kickoff.iso}>{kickoff.text}</time>
        </div>
        {isFav ? (
          <span className="fav-badge">
            <StarIcon filled size={13} /> {homeFav && awayFav ? 'Your teams' : 'Your team'}
          </span>
        ) : null}
      </div>

      <Heading className="teams">
        <span className="team">
          <a className="team-link" href={teamHref(match.home_team)}>{match.home_team}</a>
        </span>
        <span className="vs-badge" aria-hidden="true">VS</span>
        <span className="sr-only"> versus </span>
        <span className="team">
          <a className="team-link" href={teamHref(match.away_team)}>{match.away_team}</a>
        </span>
      </Heading>

      <div className="team-tools-row">
        <TeamTools match={match} side="home" name={match.home_team} favourites={favourites} />
        <TeamTools match={match} side="away" name={match.away_team} favourites={favourites} />
      </div>

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
