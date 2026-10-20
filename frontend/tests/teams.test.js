import test from 'node:test';
import assert from 'node:assert/strict';
import {
  OTHER_LEAGUE_LABEL, formDots, formSummary, formatAverage, formatElo, formatEloChange, formatRank, formatRate,
  formatRecord, groupTeamsByLeague, isFavouriteFixture, parseTeamRoute, searchTeams, shortTeamName,
  sortFixturesFavouritesFirst, stripTeamAffixes, teamHref,
} from '../src/lib/teams.js';
import { ROUTES, legacyView, parseRoute } from '../src/lib/routes.js';
import { createSessionCache } from '../src/lib/sessionCache.js';

const INDEX = [
  { name: 'Arsenal FC', league: 'PL' },
  { name: 'Tottenham Hotspur FC', league: 'PL' },
  { name: 'Manchester United FC', league: 'PL' },
  { name: 'Manchester City FC', league: 'PL' },
  { name: 'Brighton & Hove Albion FC', league: 'PL' },
  { name: 'FC Barcelona', league: 'PD' },
  { name: 'RCD Espanyol de Barcelona', league: 'PD' },
  { name: 'FC Internazionale Milano', league: 'SA' },
  { name: 'AC Milan', league: 'SA' },
  { name: '1. FC Köln', league: 'BL1' },
  { name: 'FC Bayern München', league: 'BL1' },
  { name: 'Paris Saint-Germain FC', league: 'FL1' },
  { name: 'Celtic FC', league: null },
  { name: 'Mystery FC', league: 'XX' },
];

test('team routes round-trip names with spaces, "&", "." and accents', () => {
  for (const name of ['Arsenal FC', 'Brighton & Hove Albion FC', '1. FC Köln', 'FC St. Pauli 1910', 'Nott/ham']) {
    const href = teamHref(name);
    assert.ok(href.startsWith('#/team/'));
    assert.equal(parseTeamRoute(href), name);
    assert.deepEqual(parseRoute(href), { view: 'team', team: name });
  }
  assert.equal(teamHref('Brighton & Hove Albion FC'), '#/team/Brighton%20%26%20Hove%20Albion%20FC');
  assert.equal(parseTeamRoute('#/team/Arsenal%20FC/'), 'Arsenal FC', 'trailing slash allowed');
});

test('malformed or empty team routes fall back to the upcoming view', () => {
  for (const hash of ['#/team/', '#/team', '#/team/%E0%A4%A', '#/team/%20%20', '#/team/a/b', '#/teams/x']) {
    assert.equal(parseTeamRoute(hash), null, hash);
    assert.deepEqual(parseRoute(hash), { view: 'upcoming', team: null }, hash);
  }
});

test('existing routes keep their behaviour', () => {
  assert.equal(parseRoute('').view, 'upcoming');
  assert.equal(parseRoute('#/').view, 'upcoming');
  assert.equal(parseRoute('#/track-record').view, 'trackRecord');
  assert.equal(parseRoute('#/track-record/').view, 'trackRecord');
  assert.equal(parseRoute('#/news').view, 'news');
  assert.equal(parseRoute('#/nope').view, 'upcoming');
  assert.deepEqual(Object.keys(ROUTES), ['upcoming', 'trackRecord', 'news']);
  // The legacy hook value never leaves ROUTES (App indexes a table by it).
  assert.equal(legacyView('#/team/Arsenal%20FC'), 'upcoming');
  assert.equal(legacyView('#/news'), 'news');
});

test('teams group by league in canonical order with no-league teams last', () => {
  const groups = groupTeamsByLeague([...INDEX, { name: 'Arsenal FC', league: 'PL' }, null, { name: '' }, 'Rangers FC']);
  assert.deepEqual(groups.map((g) => g.league), ['PL', 'PD', 'SA', 'BL1', 'FL1', 'XX', null]);
  assert.equal(groups[0].label, 'Premier League');
  assert.equal(groups.at(-1).label, OTHER_LEAGUE_LABEL);
  assert.deepEqual(groups.at(-1).teams.map((t) => t.name), ['Celtic FC', 'Rangers FC']);
  assert.equal(groups[0].teams.filter((t) => t.name === 'Arsenal FC').length, 1, 'duplicates dropped');
  assert.deepEqual(groupTeamsByLeague(null), []);
});

test('search is case/diacritic-insensitive and understands short names', () => {
  const names = (q) => searchTeams(INDEX, q).map((t) => t.name);
  assert.deepEqual(names('barca'), ['FC Barcelona']);
  assert.deepEqual(names('BARÇA'), ['FC Barcelona']);
  assert.deepEqual(names('spurs'), ['Tottenham Hotspur FC']);
  assert.equal(names('inter')[0], 'FC Internazionale Milano');
  assert.deepEqual(names('man utd'), ['Manchester United FC']);
  assert.deepEqual(names('koln'), ['1. FC Köln']);
  assert.deepEqual(names('bayern munich'), ['FC Bayern München']);
  assert.deepEqual(names('psg'), ['Paris Saint-Germain FC']);
  assert.deepEqual(names('paris st germain'), ['Paris Saint-Germain FC']);
  assert.deepEqual(names('brighton & hove'), ['Brighton & Hove Albion FC']);
  assert.equal(names('barcelona')[0], 'FC Barcelona', 'closer match ranks first');
  assert.ok(names('barcelona').includes('RCD Espanyol de Barcelona'));
  assert.equal(names('').length, INDEX.length);
  assert.deepEqual(names('zzz'), []);
});

test('name helpers strip affixes and pick short names', () => {
  assert.equal(stripTeamAffixes('SSC Napoli'), 'Napoli');
  assert.equal(stripTeamAffixes('1. FC Köln'), 'Köln');
  assert.equal(stripTeamAffixes('Bologna FC 1909'), 'Bologna');
  assert.equal(stripTeamAffixes('Arsenal FC'), 'Arsenal');
  assert.equal(stripTeamAffixes('FC'), 'FC', 'never strips to nothing');
  assert.equal(shortTeamName('Manchester United FC'), 'Man Utd');
  assert.equal(shortTeamName('Celtic FC'), 'Celtic');
});

test('form dots and summaries', () => {
  assert.deepEqual(formDots('WDLx'), [
    { result: 'W', label: 'Win' }, { result: 'D', label: 'Draw' }, { result: 'L', label: 'Loss' },
  ]);
  assert.deepEqual(formDots(''), []);
  assert.deepEqual(formDots(null), []);
  assert.equal(formSummary('WL'), 'Last 2: Win, Loss (most recent last)');
  assert.equal(formSummary(''), 'No recent matches');
});

test('number formatting handles nulls', () => {
  assert.equal(formatElo(1712.3), '1712');
  assert.equal(formatElo(null), '—');
  assert.equal(formatEloChange(14.62), '+14.6');
  assert.equal(formatEloChange(-3.24), '−3.2');
  assert.equal(formatEloChange(0.01), '0.0');
  assert.equal(formatEloChange(undefined), '—');
  assert.equal(formatRate(0.4), '40%');
  assert.equal(formatRate(0.4567, 1), '45.7%');
  assert.equal(formatRate(NaN), '—');
  assert.equal(formatAverage(1.94), '1.9');
  assert.equal(formatAverage(null), '—');
  assert.equal(formatRank(2, 20), '2nd of 20');
  assert.equal(formatRank(11, 20), '11th of 20');
  assert.equal(formatRank(23, null), '23rd');
  assert.equal(formatRank(null, 20), '—');
  assert.equal(formatRecord({ w: 5, d: 2, l: 1 }), '5W 2D 1L');
  assert.equal(formatRecord(null), '—');
});

test('favourite fixtures are detected and sorted first, stable within bands', () => {
  const fixtures = [
    { id: 1, home_team: 'A', away_team: 'B' },
    { id: 2, home_team: 'C', away_team: 'Fav' },
    { id: 3, home_team: 'D', away_team: 'E' },
    { id: 4, home_team: 'Primary', away_team: 'F' },
    { id: 5, home_team: 'Fav', away_team: 'G' },
  ];
  assert.equal(isFavouriteFixture(fixtures[1], ['Fav']), true);
  assert.equal(isFavouriteFixture(fixtures[0], new Set(['Fav'])), false);
  assert.equal(isFavouriteFixture(null, ['Fav']), false);
  const sorted = sortFixturesFavouritesFirst(fixtures, ['Fav', 'Primary'], 'Primary');
  assert.deepEqual(sorted.map((f) => f.id), [4, 2, 5, 1, 3]);
  assert.deepEqual(sortFixturesFavouritesFirst(fixtures, []).map((f) => f.id), [1, 2, 3, 4, 5]);
  assert.notEqual(sortFixturesFavouritesFirst(fixtures, []), fixtures, 'returns a new array');
});

test('session cache shares in-flight loads, keeps successes and never caches failures', async () => {
  let calls = 0;
  let fail = true;
  const cache = createSessionCache(async () => {
    calls += 1;
    if (fail) throw new Error('down');
    return ['Arsenal FC'];
  });
  const [a, b] = await Promise.allSettled([cache.load(), cache.load()]);
  assert.equal(calls, 1, 'concurrent loads share one request');
  assert.equal(a.status, 'rejected');
  assert.equal(b.status, 'rejected');
  assert.equal(cache.has(), false);
  fail = false;
  assert.deepEqual(await cache.load(), ['Arsenal FC']);
  assert.deepEqual(await cache.load(), ['Arsenal FC']);
  assert.equal(calls, 2);
  assert.deepEqual(cache.peek(), ['Arsenal FC']);
  await cache.load({ force: true });
  assert.equal(calls, 3);
});
