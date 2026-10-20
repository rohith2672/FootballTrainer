import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, describeError, fetchUpcoming, isNotConfigured } from '../src/api.js';
import { teamNewsState } from '../src/lib/news.js';
import {
  currentSeasonStart,
  formerLeagueInfo,
  isCurrentSeason,
  seasonTableCaption,
} from '../src/lib/teamPage.js';
import { modelVersionParts } from '../src/lib/trackRecord.js';
import { dayNumber, lineGeometry, timeTicks } from '../src/lib/charts.js';

const NOT_CONFIGURED = 'Fixture source not configured (FOOTBALL_DATA_API_KEY missing)';

// ---- 1. Upcoming: 503 "not configured" is a configuration problem -------------

test('describeError shows the server detail for a not-configured upstream error', () => {
  const err = new ApiError('upstream', 'Service unavailable (HTTP 503).', 503, NOT_CONFIGURED);
  assert.equal(isNotConfigured(err), true);
  const { title, message } = describeError(err);
  assert.equal(title, 'Data source not configured');
  assert.match(message, /FOOTBALL_DATA_API_KEY missing\)\./);
  assert.doesNotMatch(message, /usually temporary/);
});

test('describeError keeps the transient copy for other upstream errors', () => {
  for (const detail of ['Database unavailable', 'Upstream timeout', null]) {
    const err = new ApiError('upstream', 'Service unavailable (HTTP 503).', 503, detail);
    assert.equal(isNotConfigured(err), false, String(detail));
    const { title, message } = describeError(err);
    assert.equal(title, 'Couldn’t reach the data provider');
    assert.match(message, /usually temporary/);
  }
  // Only upstream errors count, even with a matching detail.
  assert.equal(isNotConfigured(new ApiError('server', 'x', 500, NOT_CONFIGURED)), false);
});

test('fetchUpcoming carries the 503 detail through to describeError', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: NOT_CONFIGURED }), { status: 503 }));
  await assert.rejects(fetchUpcoming(), (err) => {
    assert.equal(err.kind, 'upstream');
    assert.equal(err.detail, NOT_CONFIGURED);
    assert.equal(describeError(err).title, 'Data source not configured');
    return true;
  });
});

// ---- 2. Team news card states ---------------------------------------------------

const ARTICLE = { id: '1', title: 'Arsenal win', url: 'https://example.com/a' };

test('teamNewsState: unavailable cache never claims "no headlines mention"', () => {
  assert.equal(teamNewsState({ data: { status: 'unavailable', stale: true, articles: [] } }), 'unavailable');
  // Unavailable with saved headlines that do not mention the team: still no claim.
  assert.equal(teamNewsState({ data: { status: 'unavailable', articles: [ARTICLE] }, matched: [] }), 'unavailable');
  // A matching saved headline is still listed.
  assert.equal(teamNewsState({ data: { status: 'unavailable', articles: [ARTICLE] }, matched: [ARTICLE] }), 'list');
});

test('teamNewsState: empty, no-match, loading and error states', () => {
  assert.equal(teamNewsState({ data: { status: 'ok', articles: [] } }), 'no-headlines');
  assert.equal(teamNewsState({ data: { status: 'stale', stale: true, articles: [ARTICLE] }, matched: [] }), 'no-match');
  assert.equal(teamNewsState({ data: { status: 'ok', articles: [ARTICLE] }, matched: [ARTICLE] }), 'list');
  assert.equal(teamNewsState({ data: null, loading: true }), 'loading');
  assert.equal(teamNewsState({ data: null }), 'loading');
  assert.equal(teamNewsState({ data: null, error: new Error('x') }), 'error');
});

// ---- 3. Relegated teams and season labels --------------------------------------------

test('currentSeasonStart rolls over on 1 July', () => {
  assert.equal(currentSeasonStart(new Date(2026, 5, 30)), 2025);
  assert.equal(currentSeasonStart(new Date(2026, 6, 1)), 2026);
  assert.equal(currentSeasonStart(new Date(2026, 9, 20)), 2026);
  assert.equal(currentSeasonStart(new Date(2027, 0, 5)), 2026);
  assert.equal(currentSeasonStart(new Date('nope')), null);
  assert.equal(isCurrentSeason(2026, new Date(2026, 9, 20)), true);
  assert.equal(isCurrentSeason(2025, new Date(2026, 9, 20)), false);
  assert.equal(isCurrentSeason(null, new Date(2026, 9, 20)), false);
});

const TODAY = new Date(2026, 9, 20);

test('formerLeagueInfo flags a team with a league size but no rank', () => {
  const relegated = {
    league: 'PL',
    elo: { rating: 1500, rank_in_league: null, league_size: 20 },
    season: { season: 2025 },
  };
  assert.deepEqual(formerLeagueInfo(relegated, TODAY), { lastSeason: '2025/26' });
  // Season unknown (or, oddly, current): still flagged, without a season.
  assert.deepEqual(formerLeagueInfo({ ...relegated, season: null }, TODAY), { lastSeason: null });
  assert.deepEqual(formerLeagueInfo({ ...relegated, season: { season: 2026 } }, TODAY), { lastSeason: null });
});

test('formerLeagueInfo leaves ranked and league-less teams alone', () => {
  assert.equal(formerLeagueInfo({ league: 'PL', elo: { rank_in_league: 2, league_size: 20 } }, TODAY), null);
  // Champions-League-only team (e.g. Celtic): no league, no size.
  assert.equal(formerLeagueInfo({ league: null, elo: { rank_in_league: null, league_size: null } }, TODAY), null);
  assert.equal(formerLeagueInfo({ league: 'PL', elo: { rank_in_league: null, league_size: null } }, TODAY), null);
  assert.equal(formerLeagueInfo({ league: 'PL', elo: { rank_in_league: null, league_size: 0 } }, TODAY), null);
  assert.equal(formerLeagueInfo(null, TODAY), null);
});

test('seasonTableCaption only says "this season" for the current season', () => {
  assert.equal(seasonTableCaption(2026, TODAY), 'Home and away record this season');
  assert.equal(seasonTableCaption(2025, TODAY), '2025/26 home and away record');
  assert.equal(seasonTableCaption(undefined, TODAY), 'Home and away record');
});

// ---- 4. Model version tokens -------------------------------------------------------

test('modelVersionParts splits version and date into unbreakable tokens', () => {
  assert.deepEqual(modelVersionParts('lgbm@6172844 2026-10-15'), ['lgbm@6172844', '2026-10-15']);
  assert.deepEqual(modelVersionParts('  stub  '), ['stub']);
  assert.deepEqual(modelVersionParts(''), []);
  assert.deepEqual(modelVersionParts(null), []);
});

// ---- 5a. Time-based x scale for the Elo chart ------------------------------------

test('dayNumber counts whole UTC days', () => {
  assert.equal(dayNumber('1970-01-02'), 1);
  assert.equal(dayNumber('2026-03-29') - dayNumber('2026-03-28'), 1); // across a DST change
  assert.equal(dayNumber('2026-10-20T15:00:00Z'), dayNumber('2026-10-20'));
  assert.equal(dayNumber('bad'), null);
  assert.equal(dayNumber(null), null);
});

const MARGIN = { top: 10, right: 10, bottom: 10, left: 10 };

test('lineGeometry places points by x value when xValues are given', () => {
  // Three matches: two a day apart, then one after a 98-day break.
  const xValues = [0, 1, 99];
  const g = lineGeometry([1500, 1510, 1490], { width: 120, height: 100, margin: MARGIN, xValues });
  assert.deepEqual(g.xDomain, [0, 99]);
  assert.equal(g.xs[0], 10);
  assert.equal(g.xs[2], 110);
  assert.ok(Math.abs(g.xs[1] - (10 + 100 / 99)) < 1e-9);
  assert.equal(g.x(99), 110);
});

test('lineGeometry keeps even spacing without (valid) xValues', () => {
  const even = lineGeometry([1, 2, 3], { width: 120, height: 100, margin: MARGIN });
  assert.deepEqual(even.xs, [10, 60, 110]);
  assert.equal(even.x, null);
  const bad = lineGeometry([1, 2, 3], { width: 120, height: 100, margin: MARGIN, xValues: [0, null, 5] });
  assert.deepEqual(bad.xs, [10, 60, 110]);
});

test('timeTicks: month starts with the year when the range spans years', () => {
  const d0 = dayNumber('2025-10-21');
  const d1 = dayNumber('2026-10-18');
  const ticks = timeTicks(d0, d1, 1000, 70);
  assert.equal(ticks[0].label, 'Nov 2025');
  assert.equal(ticks[0].value, dayNumber('2025-11-01'));
  assert.equal(ticks.at(-1).label, 'Oct 2026');
  assert.ok(ticks.every((t) => t.value >= d0 && t.value <= d1));
  assert.ok(ticks.every((t) => /^\w{3,4} \d{4}$/.test(t.label)));
});

test('timeTicks thins month starts to fit narrow charts', () => {
  const d0 = dayNumber('2025-10-21');
  const d1 = dayNumber('2026-10-18');
  const narrow = timeTicks(d0, d1, 260, 70); // a phone: at most 3 labels
  assert.ok(narrow.length >= 2 && narrow.length <= 3, JSON.stringify(narrow));
  const labels = narrow.map((t) => t.label);
  assert.deepEqual(labels.slice(0, 2), ['Jan 2026', 'May 2026']);
  assert.match(labels[2], /^Sept? 2026$/); // en-GB ICU data may abbreviate September as "Sept"
});

test('timeTicks: one calendar year has month-only labels; short ranges use days', () => {
  const ticks = timeTicks(dayNumber('2026-02-10'), dayNumber('2026-06-20'), 1000);
  assert.deepEqual(ticks.map((t) => t.label), ['Mar', 'Apr', 'May', 'Jun']);
  const short = timeTicks(dayNumber('2026-10-02'), dayNumber('2026-10-20'), 600);
  assert.deepEqual(short.map((t) => t.label), ['2 Oct', '20 Oct']);
  assert.deepEqual(timeTicks(null, 5, 100), []);
});
