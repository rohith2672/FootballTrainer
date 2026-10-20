import test from 'node:test';
import assert from 'node:assert/strict';
import { dashboardStats } from '../src/lib/dashboard.js';
import { normalizeMatches } from '../src/lib/matches.js';
import { EMPTY_FAVOURITES, FAVOURITES_KEY, createFavouritesStore } from '../src/lib/favourites.js';
import {
  EMPTY_CORE, EMPTY_LIST, REST_CAP, coreFailed, coreLoaded, fixtureSides, listFailed, listLoaded, restGapText, teamView,
} from '../src/lib/teamPage.js';

// ---- "Your teams · next 7 days" counts every fixture from now ----------------

const NOW = Date.parse('2026-10-20T12:00:00Z');
const DAY = 24 * 60 * 60 * 1000;
const at = (days) => new Date(NOW + days * DAY).toISOString();
const ALL = normalizeMatches([
  { fixture_id: 1, league: 'PL', home_team: 'Arsenal FC', away_team: 'Chelsea FC', kickoff: at(1), home_win: 0.5, draw: 0.25, away_win: 0.25 },
  { fixture_id: 2, league: 'CL', home_team: 'FC Barcelona', away_team: 'Arsenal FC', kickoff: at(2), home_win: 0.4, draw: 0.3, away_win: 0.3 },
  { fixture_id: 3, league: 'PD', home_team: 'Getafe CF', away_team: 'Sevilla FC', kickoff: at(3), home_win: 0.4, draw: 0.3, away_win: 0.3 },
  { fixture_id: 4, league: 'PL', home_team: 'Arsenal FC', away_team: 'Everton FC', kickoff: at(-0.5), home_win: 0.6, draw: 0.2, away_win: 0.2 },
]);

test('favourites this week counts all fixtures, other stats only the shown ones', () => {
  const shown = ALL.filter((m) => m.league === 'PD');
  const stats = dashboardStats(shown, ['Arsenal FC'], NOW, ALL);
  assert.equal(stats.shown, 1);
  assert.equal(stats.predicted, 1);
  assert.equal(stats.closest.fixture_id, 3);
  assert.equal(stats.favouritesThisWeek, 2, 'PL + CL fixtures, not the one already kicked off');
  // The window moves with `now`.
  assert.equal(dashboardStats(shown, ['Arsenal FC'], NOW + 1.5 * DAY, ALL).favouritesThisWeek, 1);
  // Without allMatches it falls back to the shown list.
  assert.equal(dashboardStats(shown, ['Arsenal FC'], NOW).favouritesThisWeek, 0);
});

// ---- storage events from another storage area are ignored ----------------------

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

function fakeTarget() {
  const handlers = new Set();
  return {
    addEventListener: (_, h) => handlers.add(h),
    removeEventListener: (_, h) => handlers.delete(h),
    fire: (event) => handlers.forEach((h) => h(event)),
  };
}

test('sessionStorage.clear() in another tab does not wipe favourites', () => {
  const local = memoryStorage();
  const session = memoryStorage();
  const target = fakeTarget();
  const store = createFavouritesStore({ storage: local, target });
  store.subscribe(() => {});
  store.add('Arsenal FC');
  target.fire({ key: null, storageArea: session });
  assert.deepEqual(store.getSnapshot().teams, ['Arsenal FC']);
  target.fire({ key: FAVOURITES_KEY, storageArea: session });
  assert.deepEqual(store.getSnapshot().teams, ['Arsenal FC']);
  // The same clear on our own storage area still applies.
  target.fire({ key: null, storageArea: local });
  assert.equal(store.getSnapshot(), EMPTY_FAVOURITES);
});

// ---- capped rest days ----------------------------------------------------------

const fixture = (home, away) => ({
  home_team: 'Arsenal FC',
  away_team: 'Chelsea FC',
  details: { home: { days_since_last: home }, away: { days_since_last: away } },
});

test('rest days at the engine cap read as "30+ days"', () => {
  assert.equal(REST_CAP, 30);
  assert.equal(
    restGapText(fixtureSides(fixture(30, 4), 'Arsenal FC'), 'Arsenal FC'),
    'Arsenal FC: 30+ days since their last match; Chelsea FC: 4 days (at least 26 days more rest).',
  );
  assert.equal(
    restGapText(fixtureSides(fixture(5, 30), 'Arsenal FC'), 'Arsenal FC'),
    'Arsenal FC: 5 days since their last match; Chelsea FC: 30+ days (at least 25 days less rest).',
  );
  assert.equal(
    restGapText(fixtureSides(fixture(30, 31), 'Arsenal FC'), 'Arsenal FC'),
    'Arsenal FC: 30+ days since their last match; Chelsea FC: 30+ days.',
  );
  assert.match(restGapText(fixtureSides(fixture(29, 4), 'Arsenal FC'), 'Arsenal FC'), /29 days since.*\(25 days more rest\)/);
});

// ---- team page request state -----------------------------------------------------

const KEYS = (venue = 'all', nonce = 0) => ({
  teamKey: 'Arsenal FC|',
  coreKey: `Arsenal FC||${nonce}`,
  matchesKey: `Arsenal FC||${venue}|20|${nonce}`,
});

test('profile and match list load independently', () => {
  const k = KEYS();
  let view = teamView(EMPTY_CORE, EMPTY_LIST, k);
  assert.equal(view.data, null);
  assert.equal(view.profileLoading, true);
  assert.equal(view.matchesLoading, true);

  const core = coreLoaded(EMPTY_CORE, {
    key: k.coreKey, teamKey: k.teamKey, profile: { name: 'Arsenal FC' }, eloHistory: { points: [] },
  });
  view = teamView(core, EMPTY_LIST, k);
  assert.deepEqual(view.data, { profile: { name: 'Arsenal FC' }, matches: null, eloHistory: { points: [] } });
  assert.equal(view.profileLoading, false);
  assert.equal(view.loading, true, 'matches still loading');

  const list = listLoaded(EMPTY_LIST, { key: k.matchesKey, teamKey: k.teamKey, rows: [{ id: 1 }] });
  view = teamView(core, list, k);
  assert.equal(view.loading, false);
  assert.equal(view.stale, false);
  assert.deepEqual(view.data.matches, [{ id: 1 }]);

  // A venue change only changes the matches key: the profile stays current.
  view = teamView(core, list, KEYS('home'));
  assert.equal(view.profileLoading, false);
  assert.equal(view.matchesLoading, true);
  assert.equal(view.stale, true, 'old rows are dimmed while the new venue loads');
  assert.deepEqual(view.data.matches, [{ id: 1 }]);
});

test('a failed match-list request keeps the last rows, marked stale', () => {
  const k = KEYS();
  const home = KEYS('home');
  const core = coreLoaded(EMPTY_CORE, { key: k.coreKey, teamKey: k.teamKey, profile: { name: 'Arsenal FC' } });
  const list = listLoaded(EMPTY_LIST, { key: k.matchesKey, teamKey: k.teamKey, rows: [{ id: 1 }] });
  const err = new Error('boom');
  const view = teamView(core, listFailed(list, { key: home.matchesKey, teamKey: home.teamKey, error: err }), home);
  assert.deepEqual(view.data.matches, [{ id: 1 }]);
  assert.equal(view.partialErrors.matches, err);
  assert.equal(view.stale, true);
  assert.equal(view.matchesLoading, false);
  // First-ever failure: no rows, error shown, nothing stale.
  const first = teamView(core, listFailed(EMPTY_LIST, { key: k.matchesKey, teamKey: k.teamKey, error: err }), k);
  assert.equal(first.data.matches, null);
  assert.equal(first.stale, false);
  assert.equal(first.partialErrors.matches, err);
});

test('a failed refetch keeps profile and Elo; another team never leaks', () => {
  const k = KEYS();
  const core = coreLoaded(EMPTY_CORE, {
    key: k.coreKey, teamKey: k.teamKey, profile: { name: 'Arsenal FC' }, eloHistory: { points: [1] },
  });
  // Refetch (nonce 1): Elo fails, profile ok → last Elo stays alongside the error.
  const k1 = KEYS('all', 1);
  const eloErr = new Error('elo');
  const refreshed = coreLoaded(core, { key: k1.coreKey, teamKey: k1.teamKey, profile: { name: 'Arsenal FC' }, eloError: eloErr });
  let view = teamView(refreshed, EMPTY_LIST, k1);
  assert.deepEqual(view.data.eloHistory, { points: [1] });
  assert.equal(view.partialErrors.eloHistory, eloErr);
  // Profile fails on refetch: page-level error, data still shown.
  const err = new Error('down');
  view = teamView(coreFailed(core, { key: k1.coreKey, teamKey: k1.teamKey, error: err }), EMPTY_LIST, k1);
  assert.equal(view.error, err);
  assert.equal(view.data.profile.name, 'Arsenal FC');
  // Another team's state is never returned.
  const other = { teamKey: 'Chelsea FC|', coreKey: 'Chelsea FC||0', matchesKey: 'Chelsea FC||all|20|0' };
  view = teamView(core, listLoaded(EMPTY_LIST, { key: k.matchesKey, teamKey: k.teamKey, rows: [1] }), other);
  assert.equal(view.data, null);
  assert.equal(view.stale, false);
  const fresh = coreFailed(core, { key: other.coreKey, teamKey: other.teamKey, error: err });
  assert.equal(teamView(fresh, EMPTY_LIST, other).data, null);
  assert.equal(teamView(fresh, EMPTY_LIST, other).error, err);
});
