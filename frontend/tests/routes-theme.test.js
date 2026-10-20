import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  DEFAULT_FILTERS, ROUTES, dashboardHash, hasDashboardFilters, parseDashboardFilters, parseRoute, splitHash,
} from '../src/lib/routes.js';
import {
  THEME_KEY, applyThemePref, normalizeThemePref, readThemePref, resolveTheme, themeAttribute, writeThemePref,
} from '../src/lib/theme.js';
import { teamHref } from '../src/lib/teams.js';

// ---- Routes with a query ---------------------------------------------------

test('splitHash splits on the first "?" only', () => {
  assert.deepEqual(splitHash('#/news?x=1'), { path: '#/news', query: 'x=1' });
  assert.deepEqual(splitHash('#/?q=a?b'), { path: '#/', query: 'q=a?b' });
  assert.deepEqual(splitHash('#/track-record'), { path: '#/track-record', query: '' });
  assert.deepEqual(splitHash(undefined), { path: '', query: '' });
});

test('parseRoute ignores the query and keeps every view reachable', () => {
  assert.deepEqual(parseRoute('#/?league=PL&q=ars'), { view: 'upcoming', team: null });
  assert.deepEqual(parseRoute('#/news?x=1'), { view: 'news', team: null });
  assert.deepEqual(parseRoute('#/track-record/?weeks=4'), { view: 'trackRecord', team: null });
  assert.deepEqual(parseRoute(`${teamHref('Brighton & Hove Albion FC')}?tab=x`), {
    view: 'team',
    team: 'Brighton & Hove Albion FC',
  });
  // "?" inside a team name is percent-encoded, so it never splits the name.
  assert.deepEqual(parseRoute(teamHref('What? FC')), { view: 'team', team: 'What? FC' });
});

test('dashboard filters default when the query is empty or junk', () => {
  assert.deepEqual(parseDashboardFilters(''), DEFAULT_FILTERS);
  assert.deepEqual(parseDashboardFilters('#/'), DEFAULT_FILTERS);
  assert.deepEqual(parseDashboardFilters('#/news'), DEFAULT_FILTERS);
  assert.deepEqual(
    parseDashboardFilters('#/?league=premier%20league!&sort=random&from=yesterday&to=2026-13'),
    DEFAULT_FILTERS,
  );
});

test('dashboard filters parse every field', () => {
  assert.deepEqual(parseDashboardFilters('#/?league=pl&q=ars&from=2026-10-20&to=2026-10-31&sort=confidence'), {
    league: 'PL', mine: false, q: 'ars', from: '2026-10-20', to: '2026-10-31', sort: 'confidence',
  });
  // Unknown but well-formed league codes are kept; the dashboard falls back if absent.
  assert.equal(parseDashboardFilters('#/?league=ALL').league, 'ALL');
  assert.equal(parseDashboardFilters('#/?league=XYZ1').league, 'XYZ1');
  // mine wins over a league; league=MINE is accepted as an alias.
  assert.deepEqual(
    { ...parseDashboardFilters('#/?league=PL&mine=1') },
    { ...DEFAULT_FILTERS, mine: true },
  );
  assert.equal(parseDashboardFilters('#/?league=MINE').mine, true);
  assert.equal(parseDashboardFilters('#/?mine=0').mine, false);
  // A bare query string works too.
  assert.equal(parseDashboardFilters('?q=spurs').q, 'spurs');
});

test('dashboardHash leaves defaults out', () => {
  assert.equal(dashboardHash(), ROUTES.upcoming);
  assert.equal(dashboardHash(DEFAULT_FILTERS), '#/');
  assert.equal(dashboardHash({ sort: 'kickoff', q: '' }), '#/');
  assert.equal(dashboardHash({ league: 'PL' }), '#/?league=PL');
  assert.equal(dashboardHash({ mine: true, league: 'PL' }), '#/?mine=1');
  assert.equal(dashboardHash({ sort: 'confidence' }), '#/?sort=confidence');
  assert.equal(dashboardHash({ sort: 'nonsense', from: 'bad' }), '#/');
  assert.equal(hasDashboardFilters(DEFAULT_FILTERS), false);
  assert.equal(hasDashboardFilters({ q: 'a' }), true);
});

test('search text round-trips verbatim, including reserved characters', () => {
  for (const q of ['man ', 'Brighton & Hove', 'a+b', '100%', 'c#', 'Barça', '  spaced  ', 'q=1&x=2', 'what?']) {
    const hash = dashboardHash({ q, league: 'PD' });
    const back = parseDashboardFilters(hash);
    assert.equal(back.q, q, hash);
    assert.equal(back.league, 'PD', hash);
    assert.equal(parseRoute(hash).view, 'upcoming', hash);
    // One "#" only: a "#" in the text is encoded.
    assert.equal(hash.indexOf('#', 1), -1, hash);
  }
});

test('filters round-trip through the hash', () => {
  const filters = { league: 'BL1', mine: false, q: 'bay', from: '2026-10-01', to: '2026-10-31', sort: 'confidence' };
  assert.deepEqual(parseDashboardFilters(dashboardHash(filters)), filters);
  const mine = { ...DEFAULT_FILTERS, mine: true, q: 'x' };
  assert.deepEqual(parseDashboardFilters(dashboardHash(mine)), mine);
});

test('very long search text is capped', () => {
  const long = 'a'.repeat(500);
  assert.equal(parseDashboardFilters(dashboardHash({ q: long })).q.length, 80);
});

// ---- Theme -------------------------------------------------------------------

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
    data,
  };
}

test('theme preference is normalised', () => {
  assert.equal(normalizeThemePref('light'), 'light');
  assert.equal(normalizeThemePref('dark'), 'dark');
  assert.equal(normalizeThemePref('system'), 'system');
  for (const junk of [null, undefined, '', 'LIGHT', 'blue', 1]) assert.equal(normalizeThemePref(junk), 'system');
});

test('theme resolves against the system preference', () => {
  assert.equal(resolveTheme('light', true), 'light');
  assert.equal(resolveTheme('dark', false), 'dark');
  assert.equal(resolveTheme('system', false), 'light');
  assert.equal(resolveTheme('system', true), 'dark');
  // Unknown system preference: the app's default (dark).
  assert.equal(resolveTheme('system', undefined), 'dark');
  assert.equal(resolveTheme('bogus', false), 'light');
});

test('data-theme is set only for an explicit choice', () => {
  assert.equal(themeAttribute('system'), null);
  assert.equal(themeAttribute('light'), 'light');
  assert.equal(themeAttribute('dark'), 'dark');
  const attrs = new Map();
  const root = {
    setAttribute: (k, v) => attrs.set(k, v),
    removeAttribute: (k) => attrs.delete(k),
  };
  applyThemePref(root, 'light');
  assert.equal(attrs.get('data-theme'), 'light');
  applyThemePref(root, 'system');
  assert.equal(attrs.has('data-theme'), false);
  assert.equal(applyThemePref(null, 'dark'), 'dark');
});

test('theme storage reads, writes and survives broken storage', () => {
  const store = memoryStorage();
  assert.equal(readThemePref(store), 'system');
  assert.equal(writeThemePref(store, 'dark'), true);
  assert.equal(store.data.get(THEME_KEY), 'dark');
  assert.equal(readThemePref(store), 'dark');
  writeThemePref(store, 'system');
  assert.equal(store.data.has(THEME_KEY), false);
  assert.equal(readThemePref(memoryStorage({ [THEME_KEY]: 'neon' })), 'system');

  const throwing = {
    getItem() { throw new Error('SecurityError'); },
    setItem() { throw new Error('QuotaExceededError'); },
    removeItem() { throw new Error('SecurityError'); },
  };
  assert.equal(readThemePref(throwing), 'system');
  assert.equal(writeThemePref(throwing, 'light'), false);
  assert.equal(readThemePref(() => { throw new Error('blocked'); }), 'system');
  assert.equal(writeThemePref(null, 'light'), false);
});

test('index.html applies the stored theme before paint with the same key', () => {
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const head = html.slice(0, html.indexOf('</head>'));
  assert.ok(head.includes(`'${THEME_KEY}'`), 'inline script reads the theme key');
  assert.ok(head.includes("setAttribute('data-theme'"), 'inline script sets data-theme');
  assert.ok(head.indexOf(THEME_KEY) < head.indexOf('stylesheet'), 'runs before stylesheets load');
  assert.match(html, /<title>Upcoming — Match Predictor<\/title>/);
  assert.match(html, /viewport-fit=cover/);
});

test('both light token blocks in index.css are identical', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');
  const media = /@media \(prefers-color-scheme: light\) \{\s*:root:not\(\[data-theme='dark'\]\) \{([^}]*)\}/.exec(css);
  const pinned = /:root\[data-theme='light'\] \{([^}]*)\}/.exec(css);
  assert.ok(media && pinned, 'both light blocks exist');
  const norm = (s) => s.split('\n').map((l) => l.trim()).filter(Boolean).join('\n');
  assert.equal(norm(media[1]), norm(pinned[1]));
  assert.match(norm(media[1]), /color-scheme: light;/);
});
