import test from 'node:test';
import assert from 'node:assert/strict';
import {
  WEEK_MS, closestCall, dashboardStats, favouriteFixtures, isWithinWeek, leagueForPrimary,
  matchElementId, myTeamsFixtures, teamSnapshot,
} from '../src/lib/dashboard.js';
import { normalizeMatches } from '../src/lib/matches.js';

const NOW = Date.parse('2026-10-20T12:00:00Z');
const DAY = 24 * 60 * 60 * 1000;
const at = (days) => new Date(NOW + days * DAY).toISOString();

const RAW = [
  { fixture_id: 1, league: 'PL', home_team: 'Arsenal FC', away_team: 'Chelsea FC', date: '2026-10-21', kickoff: at(1), home_win: 0.5, draw: 0.25, away_win: 0.25, prediction_available: true },
  { fixture_id: 2, league: 'CL', home_team: 'FC Barcelona', away_team: 'Arsenal FC', date: '2026-10-22', kickoff: at(2), home_win: 0.36, draw: 0.3, away_win: 0.34, prediction_available: true },
  { fixture_id: 3, league: 'PD', home_team: 'FC Barcelona', away_team: 'Getafe CF', date: '2026-10-25', kickoff: at(5), home_win: 0.7, draw: 0.2, away_win: 0.1, prediction_available: true },
  { fixture_id: 4, league: 'SA', home_team: 'Como 1907', away_team: 'AC Milan', date: '2026-10-26', kickoff: at(6), home_win: 0.34, draw: 0.33, away_win: 0.33, prediction_available: true },
  { fixture_id: 5, league: 'PL', home_team: 'Liverpool FC', away_team: 'Arsenal FC', date: '2026-11-02', kickoff: at(13), home_win: null, draw: null, away_win: null, prediction_available: false, reason: 'No match history' },
  { fixture_id: 6, league: 'BL1', home_team: 'Celtic FC', away_team: 'FC Bayern München', date: '2026-10-27', kickoff: at(7), home_win: 0.34, draw: 0.33, away_win: 0.33, prediction_available: true },
];
const MATCHES = normalizeMatches(RAW);
const CODES = ['PL', 'PD', 'SA', 'BL1', 'CL'];

test('favouriteFixtures keeps order and handles empty input', () => {
  assert.deepEqual(favouriteFixtures(MATCHES, ['Arsenal FC']).map((m) => m.fixture_id), [1, 2, 5]);
  assert.deepEqual(favouriteFixtures(MATCHES, []), []);
  assert.deepEqual(favouriteFixtures(null, ['Arsenal FC']), []);
  assert.deepEqual(favouriteFixtures(MATCHES, null), []);
});

test('myTeamsFixtures puts the primary first, then other favourites, order kept in bands', () => {
  const ids = myTeamsFixtures(MATCHES, ['FC Barcelona', 'Arsenal FC'], 'FC Barcelona').map((m) => m.fixture_id);
  assert.deepEqual(ids, [2, 3, 1, 5]);
  const noPrimary = myTeamsFixtures(MATCHES, ['Getafe CF', 'AC Milan']).map((m) => m.fixture_id);
  assert.deepEqual(noPrimary, [3, 4]);
});

test('leagueForPrimary prefers a domestic league over CL', () => {
  assert.equal(leagueForPrimary(MATCHES, 'Arsenal FC', CODES), 'PL');
  assert.equal(leagueForPrimary(MATCHES, 'FC Barcelona', CODES), 'PD');
  // Only a CL fixture: CL is still the primary's league.
  const clOnly = MATCHES.filter((m) => m.fixture_id === 2);
  assert.equal(leagueForPrimary(clOnly, 'Arsenal FC', ['CL']), 'CL');
});

test('leagueForPrimary falls back to defaultLeague', () => {
  assert.equal(leagueForPrimary(MATCHES, null, CODES), 'PL');
  assert.equal(leagueForPrimary(MATCHES, 'Unknown FC', ['PD', 'SA']), 'PD');
  // League of the primary not among the offered codes.
  assert.equal(leagueForPrimary(MATCHES, 'AC Milan', ['PL', 'PD']), 'PL');
  assert.equal(leagueForPrimary([], 'Arsenal FC', []), null);
});

test('leagueForPrimary picks the domestic league with most fixtures, then the earliest', () => {
  const list = normalizeMatches([
    { league: 'FL1', home_team: 'X FC', away_team: 'A', date: '2026-10-30', kickoff: at(10), home_win: 0.4, draw: 0.3, away_win: 0.3 },
    { league: 'PL', home_team: 'X FC', away_team: 'B', date: '2026-10-21', kickoff: at(1), home_win: 0.4, draw: 0.3, away_win: 0.3 },
    { league: 'FL1', home_team: 'C', away_team: 'X FC', date: '2026-11-03', kickoff: at(14), home_win: 0.4, draw: 0.3, away_win: 0.3 },
  ]);
  assert.equal(leagueForPrimary(list, 'X FC', ['PL', 'FL1']), 'FL1');
  assert.equal(leagueForPrimary(list.slice(0, 2), 'X FC', ['PL', 'FL1']), 'PL');
});

test('closestCall picks the smallest max-probability, earliest kickoff on ties, ignores unpredicted', () => {
  // Fixtures 4 and 6 both have max 0.34; 4 kicks off first.
  assert.equal(closestCall(MATCHES).fixture_id, 4);
  assert.equal(closestCall(MATCHES.filter((m) => m.fixture_id !== 4)).fixture_id, 6);
  assert.equal(closestCall(MATCHES.filter((m) => m.fixture_id === 5)), null);
  assert.equal(closestCall([]), null);
  assert.equal(closestCall(undefined), null);
});

test('isWithinWeek covers [now, now + 7 days)', () => {
  const m = (t) => ({ sortTime: t });
  assert.equal(isWithinWeek(m(NOW), NOW), true);
  assert.equal(isWithinWeek(m(NOW + WEEK_MS - 1), NOW), true);
  assert.equal(isWithinWeek(m(NOW + WEEK_MS), NOW), false);
  assert.equal(isWithinWeek(m(NOW - 1), NOW), false);
  assert.equal(isWithinWeek(m(Number.MAX_SAFE_INTEGER), NOW), false);
  assert.equal(isWithinWeek({}, NOW), false);
  assert.equal(isWithinWeek(m(NOW + DAY), new Date(NOW)), true);
  // Without a reference time nothing counts.
  assert.equal(isWithinWeek(m(NOW + DAY), null), false);
  assert.equal(isWithinWeek(m(NOW + DAY), undefined), false);
});

test('dashboardStats summarises the shown fixtures', () => {
  const stats = dashboardStats(MATCHES, ['Arsenal FC'], NOW);
  assert.equal(stats.shown, 6);
  assert.equal(stats.predicted, 5);
  assert.equal(stats.unavailable, 1);
  // Arsenal: fixtures 1 (day 1) and 2 (day 2) this week, 5 (day 13) is not.
  assert.equal(stats.favouritesThisWeek, 2);
  assert.equal(stats.closest.fixture_id, 4);

  const none = dashboardStats(MATCHES, [], NOW);
  assert.equal(none.favouritesThisWeek, null);

  const empty = dashboardStats([], ['Arsenal FC'], NOW);
  assert.deepEqual(empty, { shown: 0, predicted: 0, unavailable: 0, favouritesThisWeek: 0, closest: null });
});

test('teamSnapshot shows only real Elo / form values', () => {
  const match = {
    details: {
      home: { elo: 1712.3, form_pts_pg: 2.2, form_n: 5 },
      away: { elo: null, form_pts_pg: 1.44, form_n: 3 },
    },
  };
  const home = teamSnapshot(match, 'home');
  assert.equal(home.text, 'Elo 1712 · 2.2 pts/g');
  assert.equal(home.label, 'Elo rating 1712, 2.2 points per game over the last 5 matches');
  const away = teamSnapshot(match, 'away');
  assert.equal(away.text, '1.4 pts/g');
  assert.equal(away.elo, null);
  assert.equal(teamSnapshot({ details: { home: { elo: 1500, form_pts_pg: 0, form_n: 0 } } }, 'home').text, 'Elo 1500');
  assert.equal(teamSnapshot({ details: { home: { elo: null, form_pts_pg: null } } }, 'home'), null);
  assert.equal(teamSnapshot({ details: null }, 'home'), null);
  assert.equal(teamSnapshot({}, 'away'), null);
  assert.equal(teamSnapshot(null, 'away'), null);
  assert.equal(
    teamSnapshot({ details: { away: { form_pts_pg: 3, form_n: 1 } } }, 'away').label,
    '3.0 points per game over the last 1 match',
  );
});

test('matchElementId yields valid, distinct ids', () => {
  const a = matchElementId('PL|2026-10-18|Arsenal FC|Chelsea FC');
  assert.match(a, /^match-[A-Za-z0-9_-]+$/);
  assert.notEqual(matchElementId('A B'), matchElementId('A-B'));
  assert.notEqual(matchElementId('fx-1'), matchElementId('fx-1#1'));
  assert.equal(matchElementId('fx-1'), matchElementId('fx-1'));
  assert.match(matchElementId('', 'x'), /^x-fixture-/);
  assert.match(matchElementId('Köln|München', 'pin'), /^pin-[A-Za-z0-9_-]+$/);
});
