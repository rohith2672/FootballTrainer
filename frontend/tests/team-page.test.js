import test from 'node:test';
import assert from 'node:assert/strict';
import {
  averagesRows,
  canShowMore,
  eloChartPoints,
  eloDelta,
  eloRange,
  fixtureSides,
  fmtGoalDiff,
  fmtScore,
  fmtSeason,
  h2hRecordText,
  matchRowLabel,
  meetingResult,
  noFixtureMessage,
  restGapText,
  seasonSplitRows,
  teamModelSummary,
} from '../src/lib/teamPage.js';
import { orderFavourites, pickerCountText, pickerResultsText } from '../src/lib/picker.js';

const FIXTURE = {
  home_team: 'Arsenal FC',
  away_team: 'Chelsea FC',
  details: {
    home: { elo: 1712, days_since_last: 4 },
    away: { elo: 1640, days_since_last: 7 },
    h2h: { n: 12, home_pts_rate: 0.58 },
  },
};

test('eloChartPoints sorts by date, drops invalid rows and builds tooltips', () => {
  const points = eloChartPoints([
    { date: '2026-10-16', elo: 1712.3, opponent: 'Chelsea FC', result: 'W' },
    { date: '2026-09-01', elo: 1700.04, opponent: 'Brighton & Hove Albion FC', result: 'L' },
    { date: '2026-09-20', elo: null, opponent: 'X', result: 'D' },
    { date: '', elo: 1690 },
    null,
    { date: '2026-09-25', elo: 1701, result: 'Q' },
  ]);
  assert.deepEqual(points.map((p) => p.date), ['2026-09-01', '2026-09-25', '2026-10-16']);
  assert.equal(points[0].result, 'L');
  assert.equal(points[1].result, null);
  assert.equal(points[2].tooltip, '16 Oct 2026 · Win vs Chelsea FC · Elo 1712');
  // ICU builds differ on "Sep" vs "Sept".
  assert.match(points[0].tooltip, /^1 Sept? 2026 · Loss vs Brighton & Hove Albion FC · Elo 1700$/);
  assert.equal(points[1].tooltip.endsWith('Elo 1701'), true);
  assert.deepEqual(eloChartPoints(undefined), []);
});

test('eloChartPoints keeps keys unique for two matches on one day', () => {
  const points = eloChartPoints([
    { date: '2026-10-16', elo: 1700, result: 'W' },
    { date: '2026-10-16', elo: 1705, result: 'W' },
  ]);
  assert.notEqual(points[0].key, points[1].key);
  assert.deepEqual(points.map((p) => p.elo), [1700, 1705]); // input order kept on ties
});

test('eloRange summarises the series', () => {
  const points = eloChartPoints([
    { date: '2026-01-01', elo: 1650 },
    { date: '2026-02-01', elo: 1730 },
    { date: '2026-03-01', elo: 1700 },
  ]);
  assert.deepEqual(eloRange(points), { first: 1650, last: 1700, high: 1730, low: 1650, change: 50 });
  assert.equal(eloRange([]), null);
});

test('fixtureSides works out venue, opponent and details for either side', () => {
  const home = fixtureSides(FIXTURE, 'Arsenal FC');
  assert.equal(home.isHome, true);
  assert.equal(home.opponent, 'Chelsea FC');
  assert.equal(home.own.days_since_last, 4);

  const away = fixtureSides(FIXTURE, 'Chelsea FC');
  assert.equal(away.venue, 'away');
  assert.equal(away.opponent, 'Arsenal FC');
  assert.equal(away.own.days_since_last, 7);
  assert.equal(away.opp.elo, 1712);

  assert.equal(fixtureSides(FIXTURE, 'Liverpool FC'), null);
  assert.deepEqual(fixtureSides({ home_team: 'A', away_team: 'B' }, 'A').own, {});
});

test('restGapText compares rest days from the team’s point of view', () => {
  assert.equal(
    restGapText(fixtureSides(FIXTURE, 'Arsenal FC'), 'Arsenal FC'),
    'Arsenal FC: 4 days since their last match; Chelsea FC: 7 days (3 days less rest).',
  );
  assert.equal(
    restGapText(fixtureSides(FIXTURE, 'Chelsea FC'), 'Chelsea FC'),
    'Chelsea FC: 7 days since their last match; Arsenal FC: 4 days (3 days more rest).',
  );
  const equal = { ...FIXTURE, details: { home: { days_since_last: 1 }, away: { days_since_last: 1 } } };
  assert.match(restGapText(fixtureSides(equal, 'Arsenal FC'), 'Arsenal FC'), /1 day since.*\(equal rest\)/);
  const partial = { ...FIXTURE, details: { home: { days_since_last: 5 }, away: {} } };
  assert.equal(
    restGapText(fixtureSides(partial, 'Arsenal FC'), 'Arsenal FC'),
    'Arsenal FC: 5 days since their last match; Chelsea FC: rest unknown.',
  );
  assert.equal(restGapText(fixtureSides({ home_team: 'A', away_team: 'B' }, 'A'), 'A'), null);
  assert.equal(restGapText(null, 'A'), null);
});

test('h2hRecordText and meetingResult read the record for team a', () => {
  assert.equal(
    h2hRecordText({ n: 21, a_wins: 9, draws: 6, b_wins: 6, a_goals: 31, b_goals: 24 }),
    '21 meetings: 9 wins, 6 draws, 6 losses · goals 31–24',
  );
  assert.equal(
    h2hRecordText({ n: 1, a_wins: 0, draws: 0, b_wins: 1, a_goals: 0, b_goals: 2 }),
    '1 meeting: 0 wins, 0 draws, 1 loss · goals 0–2',
  );
  assert.equal(h2hRecordText({ n: 0, a_wins: 0, draws: 0, b_wins: 0 }), 'No previous meetings on record.');
  assert.equal(h2hRecordText(null), null);

  const m = { home_team: 'Chelsea FC', away_team: 'Arsenal FC', home_goals: 1, away_goals: 2 };
  assert.equal(meetingResult(m, 'Arsenal FC'), 'W');
  assert.equal(meetingResult(m, 'Chelsea FC'), 'L');
  assert.equal(meetingResult({ ...m, home_goals: 2 }, 'Arsenal FC'), 'D');
  assert.equal(meetingResult(m, 'Liverpool FC'), null);
});

test('noFixtureMessage never invents a prediction', () => {
  assert.match(noFixtureMessage('none', 'Arsenal FC').message, /no upcoming Arsenal FC match/);
  assert.match(noFixtureMessage('unavailable', 'Arsenal FC').message, /No prediction is shown/);
  assert.equal(noFixtureMessage('unavailable', 'Arsenal FC', '2025-01-01').title, 'Not shown for a past date');
});

test('seasonSplitRows adds points for the home/away split', () => {
  const rows = seasonSplitRows({
    season: 2026, played: 8, w: 5, d: 2, l: 1, gf: 16, ga: 6, pts: 17,
    home: { played: 4, w: 3, d: 1, l: 0, gf: 10, ga: 2 },
    away: { played: 4, w: 2, d: 1, l: 1, gf: 6, ga: 4 },
  });
  assert.deepEqual(rows.map((r) => [r.key, r.pts]), [['home', 10], ['away', 7], ['total', 17]]);
  assert.deepEqual(seasonSplitRows(null), []);
  assert.deepEqual(seasonSplitRows({ played: 0, w: 0, d: 0, l: 0 }).map((r) => r.key), ['total']);
  assert.equal(fmtSeason(2026), '2026/27');
  assert.equal(fmtSeason(1999), '1999/00');
  assert.equal(fmtGoalDiff(16, 6), '+10');
  assert.equal(fmtGoalDiff(2, 5), '−3');
  assert.equal(fmtGoalDiff(2, 2), '0');
  assert.equal(fmtGoalDiff(null, 2), '—');
});

test('averagesRows shows dashes and a note when shot data is missing', () => {
  const none = averagesRows({
    n: 10, n_shots: 0, goals_for: 1.9, goals_against: 0.8, shots_for: null, shots_against: null,
    sot_for: null, sot_against: null, clean_sheet_rate: 0.4, btts_rate: 0.4, over25_rate: 0.5,
  });
  const byKey = Object.fromEntries(none.rows.map((r) => [r.key, r.value]));
  assert.equal(byKey.goals_for, '1.90');
  assert.equal(byKey.shots_for, '—');
  assert.equal(byKey.clean_sheet_rate, '40%');
  assert.match(none.shotsNote, /isn’t available/);

  const partial = averagesRows({ n: 10, n_shots: 8, shots_for: 15.2 });
  assert.equal(partial.shotsNote, 'Shot figures use the 8 of 10 matches that have shot data.');
  assert.equal(averagesRows({ n: 10, n_shots: 10 }).shotsNote, null);
  assert.equal(averagesRows(null).n, 0);
});

test('match rows: score, Elo change, label and show-more rule', () => {
  const row = {
    date: '2026-10-16', league: 'PL', venue: 'away', opponent: 'Chelsea FC', gf: 2, ga: 1,
    result: 'W', elo_before: 1705.1, elo_after: 1712.3,
  };
  assert.equal(fmtScore(row), '2–1');
  assert.ok(Math.abs(eloDelta(row) - 7.2) < 1e-9);
  assert.equal(eloDelta({ elo_before: null, elo_after: 1 }), null);
  assert.equal(matchRowLabel(row), '16 Oct 2026, Away vs Chelsea FC, Win 2–1, Elo +7.2');

  assert.equal(canShowMore(new Array(20).fill(row), 20), true);
  assert.equal(canShowMore(new Array(12).fill(row), 20), false);
  assert.equal(canShowMore(new Array(50).fill(row), 50), false);
});

test('teamModelSummary is honest about empty and small samples', () => {
  const empty = teamModelSummary({ nSettled: 0, nPredictions: 3, overall: { logLoss: null }, baselines: {} });
  assert.equal(empty.empty, true);
  assert.equal(empty.verdict, null);
  assert.equal(empty.nPredictions, 3);

  const better = teamModelSummary({
    nSettled: 12, nPredictions: 14,
    overall: { logLoss: 0.95, accuracy: 0.5 },
    baselines: { uniform: { logLoss: 1.0986 } },
  });
  assert.equal(better.empty, false);
  assert.equal(better.smallSample, true);
  assert.match(better.verdict, /^Better than the uniform 1\/3 guess by 0\.149/);

  const worse = teamModelSummary({
    nSettled: 40, overall: { logLoss: 1.2 }, baselines: { uniform: { logLoss: 1.0986 } },
  });
  assert.match(worse.verdict, /^Worse/);
  assert.equal(worse.smallSample, false);
});

test('picker helpers: counts, result summary and primary-first order', () => {
  assert.equal(pickerCountText(0, 20), 'No favourite teams yet (you can follow up to 20).');
  assert.equal(pickerCountText(3, 20), '3 of 20 favourite teams.');
  assert.match(pickerCountText(20, 20), /the list is full/);
  assert.equal(pickerResultsText(1, ''), '1 team listed.');
  assert.equal(pickerResultsText(4, ' spurs '), '4 teams match “spurs”.');
  assert.equal(pickerResultsText(0, 'zzz'), 'No teams match “zzz”.');
  assert.deepEqual(orderFavourites(['A', 'B', 'C'], 'B'), ['B', 'A', 'C']);
  assert.deepEqual(orderFavourites(['A', 'B'], null), ['A', 'B']);
  assert.deepEqual(orderFavourites(undefined, 'A'), []);
});
