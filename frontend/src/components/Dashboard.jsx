import { useEffect, useMemo, useRef } from 'react';
import MatchCard from './MatchCard';
import LeagueBadge from './icons/LeagueBadge';
import { AlertIcon, GlobeIcon, InboxIcon, SearchIcon, StarIcon } from './icons';
import { useUpcoming } from '../hooks/useUpcoming';
import { useFavourites } from '../hooks/useFavourites';
import { replaceHash } from '../hooks/useHashRoute';
import { describeError } from '../api';
import {
  ALL_LEAGUES,
  filterMatches,
  formatDateHeading,
  groupByDate,
  leagueInfo,
  leaguesPresent,
  normalizeMatches,
  pct,
  sortMatches,
} from '../lib/matches';
import {
  MY_TEAMS,
  dashboardStats,
  favouriteFixtures,
  leagueForPrimary,
  matchElementId,
  myTeamsFixtures,
} from '../lib/dashboard';
import { shortTeamName, teamHref } from '../lib/teams';
import { dashboardHash, parseDashboardFilters } from '../lib/routes.js';
import '../styles/favourites.css';

const SORT_OPTIONS = [
  { value: 'kickoff', label: 'Kickoff time' },
  { value: 'confidence', label: 'Confidence (high to low)' },
];

// Pinned "My teams" list shows this many cards; the rest are one click away.
const PINNED_LIMIT = 4;

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
});

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** Scroll a card into view and move focus to it (cards with an id are focusable). */
function jumpToCard(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  el.focus({ preventScroll: true });
}

function StatsBar({ stats, hasFavourites }) {
  const { shown, predicted, unavailable, favouritesThisWeek, closest } = stats;
  return (
    <dl className="stats-bar fav-stats">
      <div className="stat-item">
        <dt className="stat-label">Fixtures shown</dt>
        <dd className="stat-value accent">{shown}</dd>
      </div>
      <div className="stat-item">
        <dt className="stat-label">Your teams · next 7 days</dt>
        <dd className="stat-value">
          {hasFavourites ? favouritesThisWeek : <span aria-label="No teams followed">—</span>}
        </dd>
      </div>
      <div className="stat-item">
        <dt className="stat-label">Closest call</dt>
        <dd className="stat-value">
          {closest ? (
            <button
              type="button"
              className="closest-call"
              onClick={() => jumpToCard(matchElementId(closest.key))}
              aria-label={`${closest.home_team} versus ${closest.away_team}: most likely outcome only ${pct(closest.confidence)}. Go to fixture`}
            >
              <span className="closest-teams">
                {shortTeamName(closest.home_team)} v {shortTeamName(closest.away_team)}
              </span>
              <span className="closest-pct">top outcome {pct(closest.confidence)}</span>
            </button>
          ) : (
            <span aria-label="No predictions">—</span>
          )}
        </dd>
      </div>
      <div className="stat-item">
        <dt className="stat-label">Predictions available</dt>
        <dd className={`stat-value ${unavailable ? 'muted' : ''}`}>
          {predicted}
          <span className="stat-of"> of {shown}</span>
        </dd>
      </div>
    </dl>
  );
}

function MyTeamsSection({ teams, primary, fixtures, filtersActive, onOpenPicker, onShowAll }) {
  const shown = fixtures.slice(0, PINNED_LIMIT);
  const more = fixtures.length - shown.length;
  return (
    <section className="my-teams-section" aria-labelledby="my-teams-heading">
      <div className="my-teams-header">
        <div>
          <h2 id="my-teams-heading" className="with-icon">
            <StarIcon filled size={20} className="star-icon" />
            My teams
          </h2>
          {teams.length ? (
            <p className="my-teams-list">
              Following{' '}
              {teams.map((name, i) => (
                <span key={name}>
                  {i ? ', ' : ''}
                  <a href={teamHref(name)}>{shortTeamName(name)}</a>
                  {name === primary && teams.length > 1 ? <span className="primary-tag"> (main)</span> : null}
                </span>
              ))}
            </p>
          ) : null}
        </div>
        {onOpenPicker && teams.length ? (
          <button type="button" className="btn" onClick={onOpenPicker}>
            Edit teams
          </button>
        ) : null}
      </div>

      {!teams.length ? (
        <div className="my-teams-empty">
          <p>
            Follow teams to pin their fixtures here and filter the news. Tap the{' '}
            <StarIcon size={16} className="inline-icon" />
            <span className="sr-only">star</span> next to a team on any match card
            {onOpenPicker ? ', or choose from the full list.' : '.'}
          </p>
          {onOpenPicker ? (
            <button type="button" className="btn btn-primary" onClick={onOpenPicker}>
              Choose teams
            </button>
          ) : null}
        </div>
      ) : fixtures.length === 0 ? (
        <div className="my-teams-empty">
          <p>
            {filtersActive
              ? 'None of your teams have fixtures matching the current team and date filters.'
              : 'None of your teams have upcoming fixtures in the covered window.'}
          </p>
        </div>
      ) : (
        <>
          <div className="matches-grid">
            {shown.map((m, i) => (
              <MatchCard key={m.key} match={m} headingLevel={3} index={i} />
            ))}
          </div>
          {more > 0 ? (
            <div className="my-teams-more">
              <button type="button" className="btn" onClick={onShowAll}>
                Show all {plural(fixtures.length, 'fixture')} for your teams
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

/**
 * Filters live in the hash query ("#/?league=PL&q=ars&mine=1&sort=confidence")
 * so they survive a reload and can be shared. `routeHash` is the last Upcoming
 * hash (App keeps it while another view is shown); changes replace the
 * current history entry instead of adding one per keystroke.
 *
 * `onOpenPicker` (optional): opens the team picker. Without it, "Choose teams"
 * buttons are hidden and the empty state points at the stars on match cards.
 */
function Dashboard({ routeHash = '', onOpenPicker }) {
  const { matches: rawMatches, loading, error, updatedAt, reload } = useUpcoming();
  const { teams, primary } = useFavourites();
  const hasFavourites = teams.length > 0;
  const selectorRef = useRef(null);

  const filters = useMemo(() => parseDashboardFilters(routeHash), [routeHash]);
  const { q: query, from, to, sort } = filters;
  const selectedLeague = filters.mine ? MY_TEAMS : filters.league;

  // Read the live hash at call time so quick successive edits never use a stale copy.
  const update = (patch) =>
    replaceHash(dashboardHash({ ...parseDashboardFilters(window.location.hash), ...patch }));
  const setSelectedLeague = (code) =>
    update(code === MY_TEAMS ? { mine: true, league: null } : { mine: false, league: code });
  const setQuery = (q) => update({ q });
  const setFrom = (value) => update({ from: value });
  const setTo = (value) => update({ to: value });
  const setSort = (value) => update({ sort: value });

  const matches = useMemo(() => normalizeMatches(rawMatches), [rawMatches]);
  const leagueCodes = useMemo(() => leaguesPresent(matches), [matches]);
  const fallbackLeague = useMemo(
    () => leagueForPrimary(matches, primary, leagueCodes),
    [matches, primary, leagueCodes],
  );

  // Derived, so a stale or missing selection falls back without an effect.
  // With no explicit choice the primary favourite's league opens first.
  const activeLeague =
    selectedLeague === ALL_LEAGUES ||
    leagueCodes.includes(selectedLeague) ||
    (selectedLeague === MY_TEAMS && hasFavourites)
      ? selectedLeague
      : fallbackLeague;
  const myTeamsMode = activeLeague === MY_TEAMS;

  const filtersActive = Boolean(query.trim() || from || to);

  // Search/date filters apply to every league so pill counts stay meaningful.
  const filtered = useMemo(
    () => filterMatches(matches, { query, from, to }),
    [matches, query, from, to],
  );
  const favFiltered = useMemo(() => favouriteFixtures(filtered, teams), [filtered, teams]);
  const leagueCounts = useMemo(() => {
    const counts = {};
    for (const m of filtered) counts[m.league || 'Other'] = (counts[m.league || 'Other'] ?? 0) + 1;
    return counts;
  }, [filtered]);

  const visible = useMemo(() => {
    let list = filtered;
    if (myTeamsMode) list = favFiltered;
    else if (activeLeague !== ALL_LEAGUES) list = filtered.filter((m) => (m.league || 'Other') === activeLeague);
    return sortMatches(list, sort);
  }, [filtered, favFiltered, myTeamsMode, activeLeague, sort]);

  const pinned = useMemo(
    () => myTeamsFixtures(sortMatches(filtered, 'kickoff'), teams, primary),
    [filtered, teams, primary],
  );

  const sections = useMemo(() => {
    const codes = activeLeague === ALL_LEAGUES || myTeamsMode ? leagueCodes : [activeLeague];
    return codes
      .map((code) => {
        const items = visible.filter((m) => (m.league || 'Other') === code);
        return {
          code,
          items,
          // Date groups only make sense when ordered by time.
          groups: sort === 'kickoff' ? groupByDate(items) : null,
        };
      })
      .filter((s) => s.items.length > 0);
  }, [visible, activeLeague, myTeamsMode, leagueCodes, sort]);

  // `updatedAt` is when the fixtures were loaded: "next 7 days" counts from then.
  const stats = useMemo(() => dashboardStats(visible, teams, updatedAt), [visible, teams, updatedAt]);

  const clearFilters = () => update({ q: '', from: '', to: '' });

  // Keep the active pill visible in the horizontally scrolling selector.
  useEffect(() => {
    const row = selectorRef.current;
    const pill = row?.querySelector('[aria-pressed="true"]');
    if (!row || !pill || row.scrollWidth <= row.clientWidth) return;
    const left = pill.offsetLeft - row.offsetLeft;
    if (left < row.scrollLeft || left + pill.offsetWidth > row.scrollLeft + row.clientWidth) {
      row.scrollLeft = Math.max(0, left - 16);
    }
  }, [activeLeague, leagueCodes.length]);

  // --- Initial load / hard failure -----------------------------------------
  if (!updatedAt && loading) {
    return (
      <div className="loader-container" role="status" aria-live="polite">
        <div className="spinner-ring" aria-hidden="true"></div>
        <p className="loader-text">Loading upcoming fixtures and predictions…</p>
      </div>
    );
  }

  if (!updatedAt && error) {
    const { title, message } = describeError(error);
    return (
      <div className="error-card" role="alert">
        <div className="error-icon"><AlertIcon size={40} /></div>
        <h2>{title}</h2>
        <p>{message}</p>
        <button type="button" className="btn btn-primary" onClick={reload}>
          Retry
        </button>
      </div>
    );
  }

  // --- Loaded ----------------------------------------------------------------
  const refreshBar = (
    <div className="refresh-bar">
      <span className="updated-at">
        {updatedAt ? `Last updated ${timeFormatter.format(updatedAt)}` : ''}
      </span>
      <button
        type="button"
        className="btn"
        onClick={reload}
        disabled={loading}
        aria-busy={loading}
      >
        {loading ? 'Refreshing…' : 'Refresh'}
      </button>
    </div>
  );

  const staleBanner = error ? (
    <div className="inline-alert" role="alert">
      <span>
        <strong>{describeError(error).title}.</strong> Showing the data from the last successful
        update.
      </span>
      <button type="button" className="btn" onClick={reload} disabled={loading}>
        Retry
      </button>
    </div>
  ) : null;

  if (matches.length === 0) {
    return (
      <div className="dashboard-container">
        {staleBanner}
        {refreshBar}
        <div className="empty-state">
          <div className="empty-icon"><InboxIcon size={44} /></div>
          <h2>No fixtures scheduled</h2>
          <p>
            The service responded but returned no upcoming fixtures. That usually means none are
            scheduled in the covered window. If you expected some, the data provider may have been
            unavailable — try refreshing in a minute.
          </p>
        </div>
      </div>
    );
  }

  const summary = myTeamsMode
    ? `Showing ${plural(visible.length, 'fixture')} involving your teams`
    : `Showing ${plural(visible.length, 'fixture')}`;

  return (
    <div className="dashboard-container">
      {staleBanner}

      <div className="league-selector" id="league-selector" role="group" aria-label="League" ref={selectorRef}>
        <button
          type="button"
          id="league-ALL"
          className={`league-pill ${activeLeague === ALL_LEAGUES ? 'active' : ''}`}
          aria-pressed={activeLeague === ALL_LEAGUES}
          aria-label={`All leagues, ${plural(filtered.length, 'fixture')}`}
          onClick={() => setSelectedLeague(ALL_LEAGUES)}
        >
          <span className="pill-icon"><GlobeIcon size={18} /></span>
          <span className="league-name">All leagues</span>
          <span className="match-count" aria-hidden="true">{filtered.length}</span>
        </button>
        {hasFavourites ? (
          <button
            type="button"
            id="league-MINE"
            className={`league-pill my-teams-pill ${myTeamsMode ? 'active' : ''}`}
            aria-pressed={myTeamsMode}
            aria-label={`My teams, ${plural(favFiltered.length, 'fixture')}`}
            onClick={() => setSelectedLeague(MY_TEAMS)}
          >
            <span className="pill-icon"><StarIcon filled size={18} /></span>
            <span className="league-name">My teams</span>
            <span className="match-count" aria-hidden="true">{favFiltered.length}</span>
          </button>
        ) : null}
        {leagueCodes.map((code) => {
          const info = leagueInfo(code);
          const count = leagueCounts[code] ?? 0;
          return (
            <button
              type="button"
              key={code}
              id={`league-${code}`}
              className={`league-pill ${activeLeague === code ? 'active' : ''}`}
              aria-pressed={activeLeague === code}
              aria-label={`${info.name}, ${plural(count, 'fixture')}`}
              onClick={() => setSelectedLeague(code)}
            >
              <LeagueBadge code={code} size="sm" />
              <span className="league-name">{info.name}</span>
              <span className="match-count" aria-hidden="true">{count}</span>
            </button>
          );
        })}
      </div>

      <form className="filters" role="search" aria-label="Filter fixtures" onSubmit={(e) => e.preventDefault()}>
        <div className="field field-search">
          <label htmlFor="team-search">Team</label>
          <input
            id="team-search"
            type="search"
            placeholder="Search home or away team"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="date-from">From</label>
          <input id="date-from" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="date-to">To</label>
          <input id="date-to" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="sort-by">Sort by</label>
          <select id="sort-by" value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        {filtersActive ? (
          <button type="button" className="btn field-action" onClick={clearFilters}>
            Clear filters
          </button>
        ) : null}
      </form>

      {refreshBar}

      {/* In the My teams view the sections below already are the pinned list. */}
      {myTeamsMode ? null : (
        <MyTeamsSection
          teams={teams}
          primary={primary}
          fixtures={pinned}
          filtersActive={filtersActive}
          onOpenPicker={onOpenPicker}
          onShowAll={() => setSelectedLeague(MY_TEAMS)}
        />
      )}

      <p className="results-summary" role="status">
        {summary}
        {sort === 'confidence' ? ', most confident predictions first' : ''}
      </p>

      {visible.length > 0 ? (
        <div className="league-content" key={activeLeague}>
          <StatsBar stats={stats} hasFavourites={hasFavourites} />

          {sections.map(({ code, items, groups }) => {
            const info = leagueInfo(code);
            const headingId = `league-heading-${code}`;
            return (
              <section key={code} className="league-section" aria-labelledby={headingId}>
                <div className="league-header">
                  <LeagueBadge code={code} size="lg" className="league-header-icon" />
                  <div className="league-header-info">
                    <h2 id={headingId}>{info.name}</h2>
                    <span>
                      {plural(items.length, 'upcoming fixture')}
                      {myTeamsMode ? ' with your teams' : ''}
                    </span>
                  </div>
                </div>

                {groups ? (
                  groups.map((group) => (
                    <div className="date-group" key={group.dateKey}>
                      <h3 className="date-heading">{formatDateHeading(group.dateKey)}</h3>
                      <div className="matches-grid">
                        {group.matches.map((m, i) => (
                          <MatchCard key={m.key} match={m} headingLevel={4} id={matchElementId(m.key)} index={i} />
                        ))}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="matches-grid">
                    {items.map((m, i) => (
                      <MatchCard key={m.key} match={m} headingLevel={3} id={matchElementId(m.key)} index={i} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      ) : myTeamsMode ? (
        <div className="empty-state">
          <div className="empty-icon"><StarIcon size={44} /></div>
          <h2>No fixtures for your teams</h2>
          <p>
            {filtersActive
              ? 'None of your teams have fixtures matching the current team and date filters.'
              : 'None of your teams have upcoming fixtures in the covered window.'}
          </p>
          <button type="button" className="btn btn-primary" onClick={() => setSelectedLeague(ALL_LEAGUES)}>
            Show all leagues
          </button>
        </div>
      ) : (
        <div className="empty-state">
          <div className="empty-icon"><SearchIcon size={44} /></div>
          <h2>No fixtures match</h2>
          <p>
            {filtersActive
              ? 'Nothing matches the current team and date filters in this league.'
              : 'There are no fixtures in this league.'}
          </p>
          {filtersActive ? (
            <button type="button" className="btn btn-primary" onClick={clearFilters}>
              Clear filters
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

export default Dashboard;
