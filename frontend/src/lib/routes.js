// Pure hash-route parsing (kept out of the hook so it is testable in Node).
import { parseTeamRoute } from './teams.js';

/** Top-level views reachable from the main nav. */
export const ROUTES = {
  upcoming: '#/',
  trackRecord: '#/track-record',
  news: '#/news',
};

/**
 * Parse location.hash into `{ view, team }`.
 * - "#/team/<encoded name>" → `{ view: 'team', team: '<decoded name>' }`
 * - a known top-level route → `{ view: <key>, team: null }` (trailing "/" ignored)
 * - anything else, including a malformed team hash → `{ view: 'upcoming', team: null }`
 */
export function parseRoute(hash) {
  const value = String(hash ?? '');
  const team = parseTeamRoute(value);
  if (team) return { view: 'team', team };
  const normalized = value.replace(/\/+$/, '');
  const view = Object.keys(ROUTES).find((key) => ROUTES[key] === normalized) ?? 'upcoming';
  return { view, team: null };
}

/** Legacy view key: only the ROUTES keys, so callers indexing by it never miss. */
export function legacyView(hash) {
  const { view } = parseRoute(hash);
  return view in ROUTES ? view : 'upcoming';
}
