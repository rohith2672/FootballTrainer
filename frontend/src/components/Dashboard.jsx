import { useMemo, useState } from 'react';
import MatchCard from './MatchCard';
import { useUpcoming } from '../hooks/useUpcoming';
import { describeError } from '../api';
import {
  ALL_LEAGUES,
  defaultLeague,
  filterMatches,
  formatDateHeading,
  groupByDate,
  leagueInfo,
  leaguesPresent,
  normalizeMatches,
  sortMatches,
} from '../lib/matches';

const SORT_OPTIONS = [
  { value: 'kickoff', label: 'Kickoff time' },
  { value: 'confidence', label: 'Confidence (high to low)' },
];

const timeFormatter = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
});

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function Dashboard() {
  const { matches: rawMatches, loading, error, updatedAt, reload } = useUpcoming();

  const [selectedLeague, setSelectedLeague] = useState(null);
  const [query, setQuery] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [sort, setSort] = useState('kickoff');

  const matches = useMemo(() => normalizeMatches(rawMatches), [rawMatches]);
  const leagueCodes = useMemo(() => leaguesPresent(matches), [matches]);

  // Derived, so a stale or missing selection falls back without an effect.
  const activeLeague =
    selectedLeague === ALL_LEAGUES || leagueCodes.includes(selectedLeague)
      ? selectedLeague
      : defaultLeague(leagueCodes);

  const filtersActive = Boolean(query.trim() || from || to);

  // Search/date filters apply to every league so pill counts stay meaningful.
  const filtered = useMemo(
    () => filterMatches(matches, { query, from, to }),
    [matches, query, from, to],
  );
  const leagueCounts = useMemo(() => {
    const counts = {};
    for (const m of filtered) counts[m.league || 'Other'] = (counts[m.league || 'Other'] ?? 0) + 1;
    return counts;
  }, [filtered]);

  const visible = useMemo(
    () =>
      sortMatches(
        activeLeague === ALL_LEAGUES
          ? filtered
          : filtered.filter((m) => (m.league || 'Other') === activeLeague),
        sort,
      ),
    [filtered, activeLeague, sort],
  );

  const sections = useMemo(() => {
    const codes = activeLeague === ALL_LEAGUES ? leagueCodes : [activeLeague];
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
  }, [visible, activeLeague, leagueCodes, sort]);

  const predicted = visible.filter((m) => m.hasPrediction);
  const unavailable = visible.length - predicted.length;
  const avgConfidence = predicted.length
    ? Math.round((predicted.reduce((sum, m) => sum + m.confidence, 0) / predicted.length) * 100)
    : null;
  const homeFavoured = predicted.filter((m) => m.outcome === 'home').length;

  const clearFilters = () => {
    setQuery('');
    setFrom('');
    setTo('');
  };

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
        <div className="error-icon" aria-hidden="true">{'⚠️'}</div>
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
          <div className="empty-icon" aria-hidden="true">{'\u{1F4ED}'}</div>
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

  return (
    <div className="dashboard-container">
      {staleBanner}

      <div className="league-selector" id="league-selector" role="group" aria-label="League">
        <button
          type="button"
          id="league-ALL"
          className={`league-pill ${activeLeague === ALL_LEAGUES ? 'active' : ''}`}
          aria-pressed={activeLeague === ALL_LEAGUES}
          aria-label={`All leagues, ${plural(filtered.length, 'fixture')}`}
          onClick={() => setSelectedLeague(ALL_LEAGUES)}
        >
          <span className="league-emoji" aria-hidden="true">{'\u{1F30D}'}</span>
          <span className="league-name">All leagues</span>
          <span className="match-count" aria-hidden="true">{filtered.length}</span>
        </button>
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
              <span className="league-emoji" aria-hidden="true">{info.emoji}</span>
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

      <p className="results-summary" role="status">
        Showing {plural(visible.length, 'fixture')}
        {sort === 'confidence' ? ', most confident predictions first' : ''}
      </p>

      {visible.length > 0 ? (
        <div className="league-content" key={activeLeague}>
          <div className="stats-bar">
            <div className="stat-item">
              <div className="stat-value accent">{visible.length}</div>
              <div className="stat-label">Fixtures</div>
            </div>
            <div className="stat-item">
              <div className="stat-value">{avgConfidence === null ? '—' : `${avgConfidence}%`}</div>
              <div className="stat-label">Avg Confidence</div>
            </div>
            <div className="stat-item">
              <div className="stat-value">{predicted.length ? homeFavoured : '—'}</div>
              <div className="stat-label">Home Favoured</div>
            </div>
            {unavailable > 0 ? (
              <div className="stat-item">
                <div className="stat-value muted">{unavailable}</div>
                <div className="stat-label">No Prediction</div>
              </div>
            ) : null}
          </div>
          {predicted.length !== visible.length ? (
            <p className="stats-note">
              Confidence and home-favoured figures only include fixtures with a model prediction.
            </p>
          ) : null}

          {sections.map(({ code, items, groups }) => {
            const info = leagueInfo(code);
            const headingId = `league-heading-${code}`;
            return (
              <section key={code} className="league-section" aria-labelledby={headingId}>
                <div className="league-header">
                  <span className="league-header-icon" aria-hidden="true">{info.emoji}</span>
                  <div className="league-header-info">
                    <h2 id={headingId}>{info.name}</h2>
                    <span>{plural(items.length, 'upcoming fixture')}</span>
                  </div>
                </div>

                {groups ? (
                  groups.map((group) => (
                    <div className="date-group" key={group.dateKey}>
                      <h3 className="date-heading">{formatDateHeading(group.dateKey)}</h3>
                      <div className="matches-grid">
                        {group.matches.map((m) => (
                          <MatchCard key={m.key} match={m} headingLevel={4} />
                        ))}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="matches-grid">
                    {items.map((m) => (
                      <MatchCard key={m.key} match={m} headingLevel={3} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">{'\u{1F50D}'}</div>
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
