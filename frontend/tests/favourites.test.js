import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_FAVOURITES, FAVOURITES_KEY, MAX_FAVOURITES, addFavourite, createFavouritesStore, parseFavourites,
  removeFavourite, sanitizeFavourites, setPrimaryFavourite, toggleFavourite,
} from '../src/lib/favourites.js';

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
  };
}

const throwingStorage = {
  getItem() { throw new Error('SecurityError'); },
  setItem() { throw new Error('QuotaExceededError'); },
  removeItem() { throw new Error('SecurityError'); },
};

function fakeTarget() {
  const handlers = new Set();
  return {
    handlers,
    addEventListener(name, handler) { assert.equal(name, 'storage'); handlers.add(handler); },
    removeEventListener(name, handler) { assert.equal(name, 'storage'); handlers.delete(handler); },
    fire(event) { for (const handler of handlers) handler(event); },
  };
}

test('corrupt or malformed stored data yields the empty state', () => {
  for (const raw of [null, '', '{', 'null', '42', '"x"', '[]', '{"teams": "Arsenal FC"}', '{"primary": "Arsenal FC"}']) {
    assert.equal(parseFavourites(raw), EMPTY_FAVOURITES, raw);
  }
});

test('sanitising dedupes, trims, drops non-strings and caps the list', () => {
  const state = sanitizeFavourites({
    teams: [' Arsenal FC ', 'Arsenal FC', '', '   ', 3, null, { name: 'x' }, 'Chelsea FC'],
    primary: 'Chelsea FC',
  });
  assert.deepEqual(state, { teams: ['Arsenal FC', 'Chelsea FC'], primary: 'Chelsea FC' });

  const many = Array.from({ length: 30 }, (_, i) => `Team ${i}`);
  const capped = sanitizeFavourites({ teams: many, primary: 'Team 25' });
  assert.equal(capped.teams.length, MAX_FAVOURITES);
  assert.equal(capped.primary, 'Team 0', 'a primary dropped by the cap is replaced by the first team');
});

test('an invalid primary is replaced by the first team; no teams means no primary', () => {
  assert.equal(sanitizeFavourites({ teams: ['A', 'B'], primary: 'Z' }).primary, 'A');
  assert.equal(sanitizeFavourites({ teams: ['A', 'B'], primary: 7 }).primary, 'A');
  assert.equal(sanitizeFavourites({ teams: ['A', 'B'] }).primary, 'A');
  assert.equal(sanitizeFavourites({ teams: [], primary: 'A' }), EMPTY_FAVOURITES);
});

test('first added team becomes primary; removing the primary promotes the next', () => {
  let state = addFavourite(EMPTY_FAVOURITES, 'Arsenal FC');
  assert.deepEqual(state, { teams: ['Arsenal FC'], primary: 'Arsenal FC' });
  state = addFavourite(state, 'Chelsea FC');
  state = addFavourite(state, 'Everton FC');
  assert.equal(state.primary, 'Arsenal FC');
  state = removeFavourite(state, 'Arsenal FC');
  assert.deepEqual(state, { teams: ['Chelsea FC', 'Everton FC'], primary: 'Chelsea FC' });
  state = removeFavourite(state, 'Everton FC');
  assert.equal(state.primary, 'Chelsea FC', 'removing a non-primary keeps the primary');
  assert.equal(removeFavourite(state, 'Chelsea FC'), EMPTY_FAVOURITES);
});

test('setPrimary adds a missing team and switches the primary', () => {
  let state = addFavourite(EMPTY_FAVOURITES, 'Arsenal FC');
  state = setPrimaryFavourite(state, 'Liverpool FC');
  assert.deepEqual(state, { teams: ['Arsenal FC', 'Liverpool FC'], primary: 'Liverpool FC' });
  state = setPrimaryFavourite(state, 'Arsenal FC');
  assert.equal(state.primary, 'Arsenal FC');
  assert.deepEqual(toggleFavourite(state, 'Arsenal FC'), { teams: ['Liverpool FC'], primary: 'Liverpool FC' });
});

test('no-op operations return the same object (stable snapshots)', () => {
  const state = sanitizeFavourites({ teams: ['A', 'B'], primary: 'A' });
  assert.equal(addFavourite(state, 'A'), state);
  assert.equal(addFavourite(state, '  '), state);
  assert.equal(addFavourite(state, 5), state);
  assert.equal(removeFavourite(state, 'Z'), state);
  assert.equal(setPrimaryFavourite(state, 'A'), state);
  assert.equal(setPrimaryFavourite(state, ''), state);
  const full = sanitizeFavourites({ teams: Array.from({ length: MAX_FAVOURITES }, (_, i) => `T${i}`) });
  assert.equal(addFavourite(full, 'New'), full);
  assert.equal(setPrimaryFavourite(full, 'New'), full);
});

test('store persists to storage and notifies subscribers', () => {
  const storage = memoryStorage();
  const store = createFavouritesStore({ storage });
  let calls = 0;
  const unsubscribe = store.subscribe(() => { calls += 1; });
  store.add('Arsenal FC');
  store.add('Arsenal FC');
  assert.equal(calls, 1, 'a no-op does not notify');
  assert.deepEqual(JSON.parse(storage.getItem(FAVOURITES_KEY)), { teams: ['Arsenal FC'], primary: 'Arsenal FC' });
  const snapshot = store.getSnapshot();
  assert.equal(store.getSnapshot(), snapshot);
  assert.equal(store.isFavourite('Arsenal FC'), true);
  store.clear();
  assert.equal(storage.getItem(FAVOURITES_KEY), null);
  assert.equal(calls, 2);
  unsubscribe();

  const reloaded = createFavouritesStore({
    storage: memoryStorage({ [FAVOURITES_KEY]: '{"teams":["Chelsea FC","Chelsea FC"],"primary":"nope"}' }),
  });
  assert.deepEqual(reloaded.getSnapshot(), { teams: ['Chelsea FC'], primary: 'Chelsea FC' });
});

test('blocked or throwing storage falls back to memory without errors', () => {
  for (const storage of [throwingStorage, () => { throw new Error('SecurityError'); }, null, undefined, {}]) {
    const store = createFavouritesStore({ storage });
    let calls = 0;
    store.subscribe(() => { calls += 1; });
    assert.equal(store.getSnapshot(), EMPTY_FAVOURITES);
    store.toggle('Arsenal FC');
    store.setPrimary('Chelsea FC');
    assert.deepEqual(store.getSnapshot(), { teams: ['Arsenal FC', 'Chelsea FC'], primary: 'Chelsea FC' });
    store.remove('Chelsea FC');
    assert.equal(store.getSnapshot().primary, 'Arsenal FC');
    assert.equal(calls, 3);
  }
});

test('storage events from other tabs update state; unrelated keys are ignored', () => {
  const storage = memoryStorage();
  const target = fakeTarget();
  const store = createFavouritesStore({ storage, target });
  assert.equal(target.handlers.size, 0, 'listens only while subscribed');
  let calls = 0;
  const unsubscribe = store.subscribe(() => { calls += 1; });
  assert.equal(target.handlers.size, 1);

  storage.setItem(FAVOURITES_KEY, '{"teams":["Liverpool FC"],"primary":"Liverpool FC"}');
  target.fire({ key: FAVOURITES_KEY });
  assert.deepEqual(store.getSnapshot(), { teams: ['Liverpool FC'], primary: 'Liverpool FC' });
  assert.equal(calls, 1);

  const before = store.getSnapshot();
  target.fire({ key: 'something.else' });
  target.fire({ key: FAVOURITES_KEY }); // same content: keep the reference
  assert.equal(store.getSnapshot(), before);
  assert.equal(calls, 1);

  storage.setItem(FAVOURITES_KEY, 'corrupt{');
  target.fire({ key: FAVOURITES_KEY });
  assert.equal(store.getSnapshot(), EMPTY_FAVOURITES);

  store.add('Arsenal FC');
  target.fire({ key: null }); // another tab called localStorage.clear()
  assert.equal(store.getSnapshot(), EMPTY_FAVOURITES);

  unsubscribe();
  assert.equal(target.handlers.size, 0);
});

test('storage events are ignored when storage cannot be read', () => {
  const target = fakeTarget();
  const store = createFavouritesStore({ storage: throwingStorage, target });
  store.subscribe(() => {});
  store.add('Arsenal FC');
  target.fire({ key: FAVOURITES_KEY });
  assert.deepEqual(store.getSnapshot().teams, ['Arsenal FC']);
});
