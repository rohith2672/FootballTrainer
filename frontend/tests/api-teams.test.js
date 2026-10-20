import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ApiError, describeTeamError, fetchTrackRecord, fetchUpcoming, getEloHistory, getH2H, getTeam, getTeamMatches,
  getTeamsIndex, isTeamNotFound,
} from '../src/api.js';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

function mockFetch(t, handler) {
  const urls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    urls.push(url);
    return handler(url, options);
  });
  return urls;
}

test('team paths encode names with spaces, "&", "." and accents', async (t) => {
  const urls = mockFetch(t, (url) => {
    if (url.includes('/matches')) return json([]);
    if (url.includes('/elo-history')) return json({ team: 'x', points: [] });
    return json({ name: 'x' });
  });
  await getTeam('Brighton & Hove Albion FC');
  await getTeam('1. FC Köln', { asOf: '2026-10-01' });
  await getTeamMatches('FC St. Pauli 1910', { limit: 5, venue: 'home' });
  await getTeamMatches('Arsenal FC', { venue: 'all' });
  await getEloHistory('Arsenal FC', { since: '2025-01-01' });
  assert.deepEqual(urls, [
    '/api/teams/Brighton%20%26%20Hove%20Albion%20FC',
    '/api/teams/1.%20FC%20K%C3%B6ln?as_of=2026-10-01',
    '/api/teams/FC%20St.%20Pauli%201910/matches?limit=5&venue=home',
    '/api/teams/Arsenal%20FC/matches',
    '/api/teams/Arsenal%20FC/elo-history?since=2025-01-01',
  ]);
});

test('team filters are optional and backward compatible', async (t) => {
  const urls = mockFetch(t, (url) => (url.includes('track-record') ? json({ n_settled: 0 }) : json([])));
  await fetchUpcoming();
  await fetchUpcoming({ team: 'Brighton & Hove Albion FC' });
  await fetchTrackRecord({ league: 'PL', weeks: 26 });
  await fetchTrackRecord({ weeks: 26, team: 'Arsenal FC' });
  await getH2H('Arsenal FC', 'Chelsea FC', { limit: 5 }).catch(() => {});
  assert.deepEqual(urls, [
    '/api/upcoming',
    '/api/upcoming?team=Brighton+%26+Hove+Albion+FC',
    '/api/track-record?league=PL&weeks=26',
    '/api/track-record?weeks=26&team=Arsenal+FC',
    '/api/h2h?a=Arsenal+FC&b=Chelsea+FC&limit=5',
  ]);
});

test('blank names are rejected before any request', async (t) => {
  const urls = mockFetch(t, () => json({}));
  await assert.rejects(getTeam(''), (e) => e instanceof ApiError && e.kind === 'client');
  await assert.rejects(getTeamMatches('  '), (e) => e.kind === 'client');
  await assert.rejects(getEloHistory(null), (e) => e.kind === 'client');
  await assert.rejects(getH2H('Arsenal FC', ''), (e) => e.kind === 'client');
  assert.deepEqual(urls, []);
});

test('unexpected bodies are parse errors', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => json({ nope: true }));
  await assert.rejects(getTeamsIndex(), (e) => e.kind === 'parse');
  await assert.rejects(getTeamMatches('Arsenal FC'), (e) => e.kind === 'parse');
  await assert.rejects(getEloHistory('Arsenal FC'), (e) => e.kind === 'parse');
  await assert.rejects(getH2H('Arsenal FC', 'Chelsea FC'), (e) => e.kind === 'parse');
  fetchMock.mock.mockImplementation(async () => json([{ name: 'x' }]));
  await assert.rejects(getTeam('Arsenal FC'), (e) => e.kind === 'parse');
  fetchMock.mock.mockImplementation(async () => json([{ name: 'Arsenal FC', league: 'PL' }, null, { league: 'PL' }]));
  assert.deepEqual(await getTeamsIndex(), [{ name: 'Arsenal FC', league: 'PL' }]);
});

test('server detail distinguishes an unknown team from a missing endpoint', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => json({ detail: 'Team not found: Unknown FC' }, 404));
  const err = await getTeam('Unknown FC').catch((e) => e);
  assert.equal(err.kind, 'client');
  assert.equal(err.status, 404);
  assert.equal(err.detail, 'Team not found: Unknown FC');
  assert.equal(err.message, 'The request was rejected (HTTP 404).', 'existing message unchanged');
  assert.equal(isTeamNotFound(err), true);
  assert.equal(describeTeamError(err).title, 'Team not found');

  fetchMock.mock.mockImplementation(async () => json({ detail: 'Not Found' }, 404));
  const missing = await getTeam('Arsenal FC').catch((e) => e);
  assert.equal(isTeamNotFound(missing), false);
  assert.match(describeTeamError(missing).title, /isn’t available yet/);

  fetchMock.mock.mockImplementation(async () => new Response('', { status: 503 }));
  const down = await getTeam('Arsenal FC').catch((e) => e);
  assert.equal(down.kind, 'upstream');
  assert.equal(down.detail, null);
});
