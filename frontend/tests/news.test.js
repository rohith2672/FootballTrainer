import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchNews, ApiError } from '../src/api.js';
import { NEWS_POLL_MS, NEWS_STALE_MS, NEWS_EXPIRE_MS, ageNewsCache, nextNewsBoundary, normalizeNews, publicationAge, safeArticleUrl, subscribeNewsPolling } from '../src/lib/news.js';

const article = (overrides = {}) => ({
  id: 'first', title: 'Club confirms next fixture', url: 'https://www.bbc.com/sport/football/articles/example',
  publisher: 'BBC Sport', published_at: '2026-10-16T10:00:00Z', fetched_at: '2026-10-16T11:00:00Z', ...overrides,
});
const response = (overrides = {}) => ({
  articles: [article()], status: 'ok', stale: false, last_attempt_at: '2026-10-16T11:00:00Z',
  last_success_at: '2026-10-16T11:00:00Z', next_check_at: '2026-10-16T12:00:00Z', ...overrides,
});

test('news rejects unsafe destinations and preserves valid publisher links', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,hello', '/relative', 'file:///local', 'https://user:password@example.com']) {
    assert.equal(safeArticleUrl(value), null);
  }
  assert.equal(safeArticleUrl('https://www.bbc.com/sport'), 'https://www.bbc.com/sport');
});

test('news orders recent stories first, removes duplicates and invalid stories, and handles missing dates', () => {
  const raw = response({ articles: [
    article(), article(), null, article({ title: ' ' }), article({ url: 'javascript:alert(1)' }),
    article({ id: 'missing', url: 'https://www.bbc.com/missing', published_at: 'invalid' }),
    article({ id: 'new', title: ' New headline ', url: 'https://www.bbc.com/new', published_at: '2026-10-16T11:00:00Z' }),
  ] });
  const data = normalizeNews(raw);
  assert.deepEqual(data.articles.map((item) => item.id), ['new', 'first', 'missing']);
  assert.equal(data.articles[0].title, 'New headline');
  assert.equal(data.articles[2].published_at, null);
  assert.equal(data.last_success_at, raw.last_success_at);
});

test('empty, stale, and unavailable cache states remain distinct', () => {
  assert.equal(normalizeNews(response({ articles: [] })).status, 'ok');
  assert.equal(normalizeNews(response({ status: 'stale', stale: false })).stale, true);
  const unavailable = normalizeNews(response({ status: 'unavailable', articles: [], last_success_at: null, next_check_at: null }));
  assert.equal(unavailable.status, 'unavailable');
  assert.equal(unavailable.last_success_at, null);
  assert.equal(unavailable.next_check_at, null);
  assert.throws(() => normalizeNews({ articles: {}, status: 'ok' }), /unexpected response/);
  assert.throws(() => normalizeNews({ articles: [], status: 'unknown' }), /unexpected response/);
});

test('publication ages are human-readable and do not produce negative ages', () => {
  const now = Date.parse('2026-10-16T12:00:00Z');
  assert.equal(publicationAge(null, now), 'Publication time unavailable');
  assert.equal(publicationAge('2026-10-16T13:00:00Z', now), 'Just published');
  assert.equal(publicationAge('2026-10-16T11:55:00Z', now), '5 min ago');
  assert.equal(publicationAge('2026-10-16T10:00:00Z', now), '2 hr ago');
  assert.equal(publicationAge('2026-10-15T10:00:00Z', now), '1 day ago');
});

test('cache ages locally through outages and expires at the 24-hour boundary', () => {
  const data = normalizeNews(response());
  const success = Date.parse(data.last_success_at);
  assert.equal(ageNewsCache(data, success).stale, false);
  assert.equal(nextNewsBoundary(data, success), NEWS_STALE_MS);
  const stale = ageNewsCache(data, success + NEWS_STALE_MS);
  assert.equal(stale.stale, true);
  assert.equal(stale.articles.length, 1);
  assert.equal(nextNewsBoundary(stale, success + NEWS_STALE_MS), NEWS_EXPIRE_MS - NEWS_STALE_MS);
  const expired = ageNewsCache(stale, success + NEWS_EXPIRE_MS);
  assert.equal(expired.status, 'unavailable');
  assert.equal(expired.articles.length, 0);
  assert.equal(nextNewsBoundary(expired, success + NEWS_EXPIRE_MS), null);
  assert.equal(ageNewsCache(null, success), null);
});

test('individual expired articles are removed even when the latest source check succeeded', () => {
  const data = normalizeNews(response({ articles: [article({ fetched_at: '2026-10-15T10:00:00Z' })] }));
  assert.equal(ageNewsCache(data, Date.parse('2026-10-16T11:00:00Z')).articles.length, 0);
  const missingSuccess = normalizeNews(response({ last_success_at: null }));
  assert.equal(ageNewsCache(missingSuccess, Date.parse('2026-10-16T11:00:00Z')).articles.length, 1);
});

test('polling reads cache every five minutes while visible and cleans up on unmount', () => {
  let count = 0;
  let tick;
  let visibilityHandler;
  let cleared;
  let removed;
  const page = {
    visibilityState: 'visible',
    addEventListener(name, handler) { assert.equal(name, 'visibilitychange'); visibilityHandler = handler; },
    removeEventListener(name, handler) { assert.equal(name, 'visibilitychange'); removed = handler; },
  };
  const clock = {
    setInterval(callback, delay) { assert.equal(delay, NEWS_POLL_MS); tick = callback; return 42; },
    clearInterval(id) { cleared = id; },
  };
  const unsubscribe = subscribeNewsPolling(() => { count += 1; }, page, clock);
  tick();
  assert.equal(count, 1);
  page.visibilityState = 'hidden';
  tick();
  visibilityHandler();
  assert.equal(count, 1);
  page.visibilityState = 'visible';
  visibilityHandler();
  assert.equal(count, 2);
  unsubscribe();
  assert.equal(cleared, 42);
  assert.equal(removed, visibilityHandler);
});

test('news API performs a limited cache GET and validates the contract', async (t) => {
  const controller = new AbortController();
  const fetchMock = t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/news?limit=50');
    assert.equal(options.signal, controller.signal);
    assert.equal(options.method, undefined);
    return new Response(JSON.stringify(response()), { status: 200 });
  });
  const data = await fetchNews({ signal: controller.signal });
  assert.equal(data.articles.length, 1);
  fetchMock.mock.mockImplementation(async () => new Response('{"articles":false}', { status: 200 }));
  await assert.rejects(fetchNews(), (error) => error instanceof ApiError && error.kind === 'parse');
});

test('news API exposes failure and cancellation without inventing headlines', async (t) => {
  const fetchMock = t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 503 }));
  await assert.rejects(fetchNews(), (error) => error.kind === 'upstream');
  fetchMock.mock.mockImplementation(async () => { throw new TypeError('offline'); });
  await assert.rejects(fetchNews(), (error) => error.kind === 'network');
  fetchMock.mock.mockImplementation(async () => { throw new DOMException('Cancelled', 'AbortError'); });
  await assert.rejects(fetchNews(), (error) => error.name === 'AbortError');
});
