// Pure helpers for the favourites-aware dashboard (no React, Node-testable).
// Fixtures are the normalised items from lib/matches.js (sortTime,
// hasPrediction, confidence, league, home_team, away_team, key).
import { defaultLeague } from './matches.js';
import { isFavouriteFixture, sortFixturesFavouritesFirst } from './teams.js';

/** Pseudo league code for the "My teams" pill. */
export const MY_TEAMS = 'MINE';

export const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

const CUP_LEAGUES = new Set(['CL']);
const leagueOf = (m) => m?.league || 'Other';
const timeOf = (now) => {
  if (now instanceof Date) return now.getTime();
  return typeof now === 'number' ? now : NaN;
};

/** Fixtures involving any of `teams`, in their given order. */
export function favouriteFixtures(matches, teams) {
  if (!Array.isArray(matches) || !teams?.length) return [];
  const set = new Set(teams);
  return matches.filter((m) => isFavouriteFixture(m, set));
}

/**
 * Pinned "My teams" list: favourite fixtures, primary first, then other
 * favourites; kickoff order (or whatever order `matches` has) inside each band.
 */
export function myTeamsFixtures(matches, teams, primary = null) {
  return sortFixturesFavouritesFirst(favouriteFixtures(matches, teams), teams, primary);
}

/**
 * League to open by default: the league the primary favourite plays in among
 * `codes`. A domestic league wins over a cup (CL); with several, the one with
 * most fixtures, then the earliest. Falls back to `defaultLeague(codes)`.
 */
export function leagueForPrimary(matches, primary, codes) {
  const fallback = defaultLeague(codes ?? []);
  if (!primary || !Array.isArray(matches) || !codes?.length) return fallback;
  const stats = new Map();
  for (const m of matches) {
    if (m?.home_team !== primary && m?.away_team !== primary) continue;
    const code = leagueOf(m);
    if (!codes.includes(code)) continue;
    const s = stats.get(code) ?? { code, n: 0, first: Infinity };
    s.n += 1;
    s.first = Math.min(s.first, m.sortTime ?? Infinity);
    stats.set(code, s);
  }
  if (!stats.size) return fallback;
  const ranked = [...stats.values()].sort(
    (a, b) =>
      Number(CUP_LEAGUES.has(a.code)) - Number(CUP_LEAGUES.has(b.code)) ||
      b.n - a.n ||
      a.first - b.first,
  );
  return ranked[0].code;
}

/**
 * The predicted fixture whose favourite outcome is least likely (smallest
 * max-probability). Ties: earliest kickoff. `null` when nothing is predicted.
 */
export function closestCall(matches) {
  let best = null;
  for (const m of Array.isArray(matches) ? matches : []) {
    if (!m?.hasPrediction || typeof m.confidence !== 'number') continue;
    if (
      !best ||
      m.confidence < best.confidence ||
      (m.confidence === best.confidence && (m.sortTime ?? Infinity) < (best.sortTime ?? Infinity))
    ) {
      best = m;
    }
  }
  return best;
}

/** Kickoff in [now, now + 7 days). Fixtures without a known date never count. */
export function isWithinWeek(match, now) {
  const t = match?.sortTime;
  const start = timeOf(now);
  if (typeof t !== 'number' || !Number.isFinite(t) || t === Number.MAX_SAFE_INTEGER) return false;
  if (!Number.isFinite(start)) return false;
  return t >= start && t < start + WEEK_MS;
}

/**
 * Figures for the stats bar over the fixtures currently shown.
 * `favouritesThisWeek` is null when there are no favourites (nothing to count).
 */
export function dashboardStats(matches, teams, now) {
  const list = Array.isArray(matches) ? matches : [];
  const predicted = list.filter((m) => m?.hasPrediction).length;
  return {
    shown: list.length,
    predicted,
    unavailable: list.length - predicted,
    favouritesThisWeek: teams?.length
      ? favouriteFixtures(list, teams).filter((m) => isWithinWeek(m, now)).length
      : null,
    closest: closestCall(list),
  };
}

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

/**
 * Compact per-team figures for a card from `/upcoming` `details.home|away`
 * (`elo`, `form_pts_pg`, `form_n`). Only real values are returned: `null`
 * when the side has neither. `ppg` is null when form_n is 0 or missing data.
 */
export function teamSnapshot(match, side) {
  const d = match?.details?.[side];
  if (!d || typeof d !== 'object') return null;
  const elo = isNum(d.elo) ? Math.round(d.elo) : null;
  const n = Number.isInteger(d.form_n) ? d.form_n : null;
  const ppg = isNum(d.form_pts_pg) && n !== 0 ? Math.round(d.form_pts_pg * 10) / 10 : null;
  if (elo === null && ppg === null) return null;
  const parts = [];
  if (elo !== null) parts.push(`Elo ${elo}`);
  if (ppg !== null) parts.push(`${ppg.toFixed(1)} pts/g`);
  const spoken = [];
  if (elo !== null) spoken.push(`Elo rating ${elo}`);
  if (ppg !== null) {
    spoken.push(`${ppg.toFixed(1)} points per game${n ? ` over the last ${n} ${n === 1 ? 'match' : 'matches'}` : ''}`);
  }
  return { elo, ppg, n, text: parts.join(' · '), label: spoken.join(', ') };
}

/**
 * A DOM id for a fixture card (keys contain "|", spaces and "#"). A short hash
 * of the raw key keeps ids distinct when two keys differ only in punctuation.
 */
export function matchElementId(key, prefix = 'match') {
  const raw = String(key ?? '');
  const safe = raw
    .normalize('NFD')
    .replace(/[^A-Za-z0-9_-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
  let hash = 5381;
  for (let i = 0; i < raw.length; i += 1) hash = ((hash * 33) ^ raw.charCodeAt(i)) >>> 0;
  return `${prefix}-${safe || 'fixture'}-${hash.toString(36)}`;
}
