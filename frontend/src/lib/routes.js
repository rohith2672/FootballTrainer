// Pure hash-route parsing (kept out of the hook so it is testable in Node).
// A hash is "<path>[?<query>]": the path picks the view, the query carries
// shareable view state (only the Upcoming dashboard uses it today).
import { parseTeamRoute } from './teams.js';

/** Top-level views reachable from the main nav. */
export const ROUTES = {
  upcoming: '#/',
  trackRecord: '#/track-record',
  news: '#/news',
};

/** "#/news?x=1" → { path: '#/news', query: 'x=1' }. Splits on the first "?". */
export function splitHash(hash) {
  const value = String(hash ?? '');
  const i = value.indexOf('?');
  return i === -1 ? { path: value, query: '' } : { path: value.slice(0, i), query: value.slice(i + 1) };
}

/**
 * Parse location.hash into `{ view, team }` (any "?query" is ignored here).
 * - "#/team/<encoded name>" → `{ view: 'team', team: '<decoded name>' }`
 * - a known top-level route → `{ view: <key>, team: null }` (trailing "/" ignored)
 * - anything else, including a malformed team hash → `{ view: 'upcoming', team: null }`
 */
export function parseRoute(hash) {
  const { path } = splitHash(hash);
  const team = parseTeamRoute(path);
  if (team) return { view: 'team', team };
  const normalized = path.replace(/\/+$/, '');
  const view =
    Object.keys(ROUTES).find((key) => ROUTES[key].replace(/\/+$/, '') === normalized) ?? 'upcoming';
  return { view, team: null };
}

/** Legacy view key: only the ROUTES keys, so callers indexing by it never miss. */
export function legacyView(hash) {
  const { view } = parseRoute(hash);
  return view in ROUTES ? view : 'upcoming';
}

// ---- Dashboard filters in the hash query ------------------------------------
// e.g. "#/?league=PL&q=ars&sort=confidence" or "#/?mine=1".

export const SORTS = ['kickoff', 'confidence'];

/** Filters with nothing chosen. `league: null` means "the default league". */
export const DEFAULT_FILTERS = Object.freeze({
  league: null,
  mine: false,
  q: '',
  from: '',
  to: '',
  sort: 'kickoff',
});

const LEAGUE_RE = /^[A-Z0-9]{2,6}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_QUERY = 80;

const validDate = (v) => (typeof v === 'string' && DATE_RE.test(v) ? v : '');

/**
 * Dashboard filters from a hash (or a bare query string). Unknown or invalid
 * values fall back to the defaults; the search text is kept verbatim (no trim)
 * so typing "man " round-trips through the URL.
 */
export function parseDashboardFilters(hash) {
  const value = String(hash ?? '');
  const query = value.startsWith('#') ? splitHash(value).query : value.replace(/^\?/, '');
  let params;
  try {
    params = new URLSearchParams(query);
  } catch {
    return { ...DEFAULT_FILTERS };
  }
  const league = (params.get('league') ?? '').toUpperCase();
  const mine = params.get('mine') === '1' || league === 'MINE';
  const sort = params.get('sort');
  return {
    league: !mine && LEAGUE_RE.test(league) ? league : null,
    mine,
    q: (params.get('q') ?? '').slice(0, MAX_QUERY),
    from: validDate(params.get('from')),
    to: validDate(params.get('to')),
    sort: SORTS.includes(sort) ? sort : DEFAULT_FILTERS.sort,
  };
}

/** Hash for the Upcoming view with `filters`; defaults are left out ("#/" when nothing is set). */
export function dashboardHash(filters = {}) {
  const f = { ...DEFAULT_FILTERS, ...filters };
  const params = new URLSearchParams();
  if (f.mine) params.set('mine', '1');
  else if (typeof f.league === 'string' && f.league) params.set('league', f.league);
  if (f.q) params.set('q', String(f.q).slice(0, MAX_QUERY));
  if (validDate(f.from)) params.set('from', f.from);
  if (validDate(f.to)) params.set('to', f.to);
  if (SORTS.includes(f.sort) && f.sort !== DEFAULT_FILTERS.sort) params.set('sort', f.sort);
  const query = params.toString();
  return query ? `${ROUTES.upcoming}?${query}` : ROUTES.upcoming;
}

/** True when any filter differs from the defaults. */
export const hasDashboardFilters = (filters) => dashboardHash(filters) !== ROUTES.upcoming;
