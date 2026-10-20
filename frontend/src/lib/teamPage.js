// Pure helpers for the team page: Elo chart points, match preparation text,
// season/averages rows and the team-filtered track record summary.
// Explicit .js imports so Node tests can load this module.
import { DASH, formatAverage, formatElo, formatEloChange, formatRate } from './teams.js';
import { parseLocalDate } from './matches.js';

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isInt = Number.isInteger;

export const RESULT_LABELS = { W: 'Win', D: 'Draw', L: 'Loss' };
export const VENUE_LABELS = { home: 'Home', away: 'Away' };
export const VENUE_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'home', label: 'Home' },
  { value: 'away', label: 'Away' },
];
export const MATCH_LIMITS = { initial: 20, more: 50 };
/** Document title for a team name the API does not know. */
export const NOT_FOUND_TITLE = 'Team not found — Match Predictor';

export const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;

// ---- Dates -------------------------------------------------------------------

/** "12 Oct" (no year) for a YYYY-MM-DD string; the input itself if unparseable. */
export function fmtDay(value) {
  const d = parseLocalDate(value);
  if (!d) return String(value ?? DASH);
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' }).format(d);
}

/** "12 Oct 2026". */
export function fmtDate(value) {
  const d = parseLocalDate(value);
  if (!d) return String(value ?? DASH);
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
}

/** Season start year → "2026/27". */
export function fmtSeason(season) {
  if (!isInt(season)) return DASH;
  return `${season}/${String((season + 1) % 100).padStart(2, '0')}`;
}

/**
 * Start year of the season in progress on `today` (1 July rollover, as in the
 * backend's season_start_year): 2026-06-30 → 2025, 2026-07-01 → 2026.
 */
export function currentSeasonStart(today = new Date()) {
  const d = today instanceof Date ? today : new Date(today);
  if (Number.isNaN(d.getTime())) return null;
  return d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1;
}

/** True when `season` (a start year) is the season in progress on `today`. */
export function isCurrentSeason(season, today = new Date()) {
  return isInt(season) && season === currentSeasonStart(today);
}

/**
 * A team whose last domestic league is known but which is not in that league's
 * current season (relegated, or otherwise left): the profile has a league and
 * `elo.league_size`, but no `elo.rank_in_league`. Returns null otherwise, else
 * {lastSeason: "2025/26" | null} (from `profile.season`, when it is not the
 * current season).
 */
export function formerLeagueInfo(profile, today = new Date()) {
  if (!profile || typeof profile !== 'object' || !profile.league) return null;
  const elo = profile.elo && typeof profile.elo === 'object' ? profile.elo : {};
  if (isInt(elo.rank_in_league) || !isInt(elo.league_size) || elo.league_size <= 0) return null;
  const season = profile.season && typeof profile.season === 'object' ? profile.season.season : null;
  return { lastSeason: isInt(season) && !isCurrentSeason(season, today) ? fmtSeason(season) : null };
}

/** Caption for the season card's home/away table. */
export function seasonTableCaption(season, today = new Date()) {
  if (!isInt(season)) return 'Home and away record';
  return isCurrentSeason(season, today) ? 'Home and away record this season' : `${fmtSeason(season)} home and away record`;
}

// ---- Elo history ---------------------------------------------------------------

/**
 * `/teams/{name}/elo-history` points → chart points, ascending by date.
 * Invalid rows are dropped. Each point: {key, date, elo, result|null,
 * opponent|null, xLabel, tooltip}.
 */
export function eloChartPoints(points) {
  if (!Array.isArray(points)) return [];
  const seen = new Map();
  return points
    .filter((p) => p && typeof p === 'object' && isNum(p.elo) && typeof p.date === 'string' && p.date)
    .map((p, i) => ({ p, i }))
    .sort((a, b) => a.p.date.localeCompare(b.p.date) || a.i - b.i)
    .map(({ p }) => {
      const result = p.result in RESULT_LABELS ? p.result : null;
      const opponent = typeof p.opponent === 'string' && p.opponent ? p.opponent : null;
      const count = seen.get(p.date) ?? 0;
      seen.set(p.date, count + 1);
      const parts = [fmtDate(p.date)];
      if (result || opponent) {
        parts.push(`${result ? RESULT_LABELS[result] : 'Match'}${opponent ? ` vs ${opponent}` : ''}`);
      }
      parts.push(`Elo ${formatElo(p.elo)}`);
      return {
        key: count ? `${p.date}#${count}` : p.date,
        date: p.date,
        elo: p.elo,
        result,
        opponent,
        xLabel: fmtDay(p.date),
        tooltip: parts.join(' · '),
      };
    });
}

/** {first, last, high, low, change} over chart points, or null with no points. */
export function eloRange(points) {
  if (!points.length) return null;
  const values = points.map((p) => p.elo);
  return {
    first: values[0],
    last: values[values.length - 1],
    high: Math.max(...values),
    low: Math.min(...values),
    change: values[values.length - 1] - values[0],
  };
}

// ---- Match preparation -----------------------------------------------------------

/**
 * Which side `team` is on in a fixture and the matching details blocks.
 * Returns null when the team is on neither side.
 * {isHome, venue, opponent, own, opp} where own/opp are `details.home|away`
 * objects ({} when missing).
 */
export function fixtureSides(fixture, team) {
  if (!fixture || !team) return null;
  let isHome;
  if (fixture.home_team === team) isHome = true;
  else if (fixture.away_team === team) isHome = false;
  else return null;
  const details = fixture.details && typeof fixture.details === 'object' ? fixture.details : {};
  const block = (v) => (v && typeof v === 'object' ? v : {});
  return {
    isHome,
    venue: isHome ? 'home' : 'away',
    opponent: isHome ? fixture.away_team : fixture.home_team,
    own: block(isHome ? details.home : details.away),
    opp: block(isHome ? details.away : details.home),
  };
}

const daysText = (n) => plural(n, 'day');

/** Upper bound of `details.*.days_since_last` from the model's feature engine. */
export const REST_CAP = 30;

/**
 * Rest-day comparison before the fixture, e.g.
 * "Arsenal FC: 4 days since their last match; Chelsea FC: 7 days (3 days less rest)."
 * Null when neither side's `days_since_last` is known.
 */
export function restGapText(sides, team) {
  if (!sides) return null;
  const own = isNum(sides.own.days_since_last) ? Math.round(sides.own.days_since_last) : null;
  const opp = isNum(sides.opp.days_since_last) ? Math.round(sides.opp.days_since_last) : null;
  if (own === null && opp === null) return null;
  // The model engine caps days_since_last at REST_CAP: a capped value means "at least".
  const ownCapped = own !== null && own >= REST_CAP;
  const oppCapped = opp !== null && opp >= REST_CAP;
  const days = (n, capped) => (capped ? `${REST_CAP}+ days` : daysText(n));
  const ownText = own === null ? 'rest unknown' : `${days(own, ownCapped)} since their last match`;
  const oppText = opp === null ? 'rest unknown' : days(opp, oppCapped);
  let gap = '';
  if (own !== null && opp !== null && !(ownCapped && oppCapped)) {
    const diff = Math.min(own, REST_CAP) - Math.min(opp, REST_CAP);
    const atLeast = ownCapped || oppCapped ? 'at least ' : '';
    gap = diff === 0 ? ' (equal rest)' : ` (${atLeast}${daysText(Math.abs(diff))} ${diff > 0 ? 'more' : 'less'} rest)`;
  }
  return `${team}: ${ownText}; ${sides.opponent}: ${oppText}${gap}.`;
}

/**
 * Head-to-head summary from `/h2h?a=team&b=opponent` (a = this team), e.g.
 * "21 meetings: 9 wins, 6 draws, 6 losses · goals 31–24".
 */
export function h2hRecordText(h2h) {
  if (!h2h || typeof h2h !== 'object') return null;
  const n = isInt(h2h.n) ? h2h.n : null;
  if (n === null) return null;
  if (n === 0) return 'No previous meetings on record.';
  const counts = [h2h.a_wins, h2h.draws, h2h.b_wins];
  const record = counts.every(isInt)
    ? `: ${plural(h2h.a_wins, 'win')}, ${plural(h2h.draws, 'draw')}, ${plural(h2h.b_wins, 'loss', 'losses')}`
    : '';
  const goals = isInt(h2h.a_goals) && isInt(h2h.b_goals) ? ` · goals ${h2h.a_goals}–${h2h.b_goals}` : '';
  return `${plural(n, 'meeting')}${record}${goals}`;
}

/** Result of a meeting from `team`'s perspective: 'W' | 'D' | 'L' | null. */
export function meetingResult(meeting, team) {
  if (!meeting || !isInt(meeting.home_goals) || !isInt(meeting.away_goals)) return null;
  const isHome = meeting.home_team === team;
  if (!isHome && meeting.away_team !== team) return null;
  const gf = isHome ? meeting.home_goals : meeting.away_goals;
  const ga = isHome ? meeting.away_goals : meeting.home_goals;
  return gf > ga ? 'W' : gf === ga ? 'D' : 'L';
}

/** Copy for a missing next fixture, keyed by `next_fixture_status`. */
export function noFixtureMessage(status, team, asOf = null) {
  if (status === 'none') {
    return {
      title: 'No fixture scheduled',
      message: `The fixture feed has no upcoming ${team} match in its domestic league or the Champions League right now.`,
    };
  }
  if (asOf) {
    return {
      title: 'Not shown for a past date',
      message: 'Upcoming fixtures are only shown for the current view, not for a historical “as of” date.',
    };
  }
  return {
    title: 'Fixture information unavailable',
    message:
      'The fixture source or the prediction model is not reachable at the moment, so the next match is unknown. No prediction is shown rather than a guess.',
  };
}

// ---- Season and averages -------------------------------------------------------------

const points = (r) => (isInt(r?.w) && isInt(r?.d) ? r.w * 3 + r.d : null);

/** Rows for the season split table: Home, Away, Total. Missing parts are skipped. */
export function seasonSplitRows(season) {
  if (!season || typeof season !== 'object') return [];
  const row = (key, label, r, pts) =>
    r && typeof r === 'object'
      ? {
          key,
          label,
          played: isInt(r.played) ? r.played : null,
          w: isInt(r.w) ? r.w : null,
          d: isInt(r.d) ? r.d : null,
          l: isInt(r.l) ? r.l : null,
          gf: isInt(r.gf) ? r.gf : null,
          ga: isInt(r.ga) ? r.ga : null,
          pts,
        }
      : null;
  return [
    row('home', 'Home', season.home, points(season.home)),
    row('away', 'Away', season.away, points(season.away)),
    row('total', 'Total', season, isInt(season.pts) ? season.pts : points(season)),
  ].filter(Boolean);
}

/** "+10", "−3", "0" goal difference, or "—". */
export function fmtGoalDiff(gf, ga) {
  if (!isInt(gf) || !isInt(ga)) return DASH;
  const d = gf - ga;
  return d > 0 ? `+${d}` : d < 0 ? `−${Math.abs(d)}` : '0';
}

/**
 * Display rows for the last-10 averages card. Shot rows show "—" when shot
 * data is missing. Returns {rows, n, nShots, shotsNote|null}.
 */
export function averagesRows(averages) {
  const a = averages && typeof averages === 'object' ? averages : {};
  const n = isInt(a.n) ? a.n : 0;
  const nShots = isInt(a.n_shots) ? a.n_shots : 0;
  const rows = [
    { key: 'goals_for', label: 'Goals scored', value: formatAverage(a.goals_for, 2), unit: 'per match' },
    { key: 'goals_against', label: 'Goals conceded', value: formatAverage(a.goals_against, 2), unit: 'per match' },
    { key: 'shots_for', label: 'Shots', value: formatAverage(a.shots_for, 1), unit: 'per match', shots: true },
    { key: 'shots_against', label: 'Shots faced', value: formatAverage(a.shots_against, 1), unit: 'per match', shots: true },
    { key: 'sot_for', label: 'Shots on target', value: formatAverage(a.sot_for, 1), unit: 'per match', shots: true },
    { key: 'sot_against', label: 'On target faced', value: formatAverage(a.sot_against, 1), unit: 'per match', shots: true },
    { key: 'clean_sheet_rate', label: 'Clean sheets', value: formatRate(a.clean_sheet_rate), unit: 'of matches' },
    { key: 'btts_rate', label: 'Both teams scored', value: formatRate(a.btts_rate), unit: 'of matches' },
    { key: 'over25_rate', label: 'Over 2.5 goals', value: formatRate(a.over25_rate), unit: 'of matches' },
  ];
  let shotsNote = null;
  if (n > 0 && nShots === 0) {
    shotsNote = 'Shot data isn’t available for these matches (for example Champions League games), so shot figures are shown as —.';
  } else if (n > 0 && nShots < n) {
    shotsNote = `Shot figures use the ${nShots} of ${n} matches that have shot data.`;
  }
  return { rows, n, nShots, shotsNote };
}

// ---- Recent matches -----------------------------------------------------------------

/** elo_after − elo_before for a match row, or null. */
export function eloDelta(row) {
  return isNum(row?.elo_after) && isNum(row?.elo_before) ? row.elo_after - row.elo_before : null;
}

/** "2–1" from the team's perspective, or "—". */
export function fmtScore(row) {
  return isInt(row?.gf) && isInt(row?.ga) ? `${row.gf}–${row.ga}` : DASH;
}

/** Accessible one-line description of a match row. */
export function matchRowLabel(row) {
  const venue = VENUE_LABELS[row?.venue] ?? '';
  const result = RESULT_LABELS[row?.result] ?? 'Result unknown';
  const delta = eloDelta(row);
  return [
    fmtDate(row?.date),
    venue ? `${venue} vs ${row?.opponent ?? 'unknown opponent'}` : `vs ${row?.opponent ?? 'unknown opponent'}`,
    `${result} ${fmtScore(row)}`,
    delta === null ? null : `Elo ${formatEloChange(delta)}`,
  ]
    .filter(Boolean)
    .join(', ');
}

/** Whether "show more" can fetch more rows: the last fetch filled its limit. */
export function canShowMore(rows, limit) {
  return Array.isArray(rows) && rows.length >= limit && limit < MATCH_LIMITS.more;
}

// ---- Team track record ---------------------------------------------------------------

/**
 * Summary for the "Model on <team>" card from a normalizeTrackRecord() result.
 * {empty, nSettled, nPredictions, accuracy, logLoss, uniform, verdict|null, smallSample}
 */
export function teamModelSummary(record) {
  const nSettled = isInt(record?.nSettled) ? record.nSettled : 0;
  const nPredictions = isInt(record?.nPredictions) ? record.nPredictions : 0;
  const logLoss = isNum(record?.overall?.logLoss) ? record.overall.logLoss : null;
  const uniform = isNum(record?.baselines?.uniform?.logLoss) ? record.baselines.uniform.logLoss : null;
  let verdict = null;
  if (nSettled > 0 && logLoss !== null && uniform !== null) {
    const diff = logLoss - uniform;
    if (Math.abs(diff) < 0.0005) verdict = 'Level with the uniform 1/3 guess.';
    else if (diff < 0) verdict = `Better than the uniform 1/3 guess by ${Math.abs(diff).toFixed(3)} (lower is better).`;
    else verdict = `Worse than the uniform 1/3 guess by ${diff.toFixed(3)} (lower is better).`;
  }
  return {
    empty: nSettled === 0,
    nSettled,
    nPredictions,
    accuracy: isNum(record?.overall?.accuracy) ? record.overall.accuracy : null,
    logLoss,
    uniform,
    verdict,
    smallSample: nSettled > 0 && nSettled < 20,
  };
}

// ---- Team page request state (used by hooks/useTeam) ------------------------
// The profile + Elo history ("core") and the match list are fetched
// separately: venue / limit changes refetch only the match list.

export const EMPTY_CORE = Object.freeze({
  key: null, teamKey: null, profile: null, eloHistory: null, eloError: null, error: null, errorKey: null,
});
export const EMPTY_LIST = Object.freeze({ key: null, teamKey: null, rows: null, error: null, errorKey: null });

/** Core state after the profile loaded (Elo may have failed: keep the last Elo for the same team). */
export function coreLoaded(prev, { key, teamKey, profile, eloHistory, eloError }) {
  const sameTeam = prev?.teamKey === teamKey;
  return {
    key,
    teamKey,
    profile,
    eloHistory: eloError ? (sameTeam ? prev.eloHistory : null) : eloHistory ?? null,
    eloError: eloError ?? null,
    error: null,
    errorKey: null,
  };
}

/** Core state after the profile request failed: earlier data for the same team stays. */
export function coreFailed(prev, { key, teamKey, error }) {
  if (prev?.teamKey === teamKey) return { ...prev, error, errorKey: key };
  return { ...EMPTY_CORE, teamKey: null, error, errorKey: key };
}

/** Match list after a successful request. */
export const listLoaded = (prev, { key, teamKey, rows }) => ({ key, teamKey, rows, error: null, errorKey: null });

/** Match list after a failed request: the last rows for the same team stay visible. */
export function listFailed(prev, { key, teamKey, error }) {
  if (prev?.teamKey === teamKey) return { ...prev, error, errorKey: key };
  return { ...EMPTY_LIST, teamKey, error, errorKey: key };
}

/**
 * What the team page shows for the current keys.
 * - `data` is null until the profile for this team arrived (never another team's).
 * - `matches` are the last rows loaded for this team, possibly for another
 *   venue/limit; then `stale` is true (loading or failed), so callers dim them.
 * - `error` is the profile failure for the current request (page level);
 *   `partialErrors` are section failures for the current request.
 */
export function teamView(core, list, { coreKey, matchesKey, teamKey }) {
  const coreSameTeam = core?.teamKey === teamKey;
  const coreError = core?.errorKey === coreKey ? core.error : null;
  const profileLoading = core?.key !== coreKey && !coreError;
  const rows = list?.teamKey === teamKey ? list.rows : null;
  const listError = list?.errorKey === matchesKey ? list.error : null;
  const listCurrent = list?.key === matchesKey;
  const matchesLoading = !listCurrent && !listError;
  return {
    data: coreSameTeam && core.profile
      ? { profile: core.profile, matches: rows ?? null, eloHistory: core.eloHistory ?? null }
      : null,
    partialErrors: { matches: listError, eloHistory: coreSameTeam ? core.eloError ?? null : null },
    error: coreError,
    profileLoading,
    matchesLoading,
    loading: profileLoading || matchesLoading,
    stale: rows !== null && !listCurrent,
  };
}
