// Favourite teams: pure state logic plus a small external store that persists
// to localStorage when it can and silently falls back to memory when it can't.
//
// Shape (localStorage key `ft.favourites.v1`):
//   { "teams": ["Arsenal FC", ...], "primary": "Arsenal FC" | null }
//
// Invariant kept by every function here: `primary` is null exactly when
// `teams` is empty, otherwise it is one of `teams`. Consequences: the first
// team added becomes primary, an invalid stored primary is replaced by the
// first team, and removing the primary promotes the first remaining team.
//
// Every operation returns the *same object* when nothing changes, so the
// store's snapshot stays referentially stable for useSyncExternalStore.

export const FAVOURITES_KEY = 'ft.favourites.v1';
export const MAX_FAVOURITES = 20;
export const EMPTY_FAVOURITES = Object.freeze({ teams: Object.freeze([]), primary: null });

const cleanName = (value) => (typeof value === 'string' ? value.trim() : '');

function make(teams, primary) {
  if (!teams.length) return EMPTY_FAVOURITES;
  return Object.freeze({
    teams: Object.freeze([...teams]),
    primary: teams.includes(primary) ? primary : teams[0],
  });
}

/** Coerce anything (parsed JSON, old data, garbage) into a valid state. */
export function sanitizeFavourites(value) {
  if (!value || typeof value !== 'object' || !Array.isArray(value.teams)) return EMPTY_FAVOURITES;
  const teams = [];
  for (const entry of value.teams) {
    const name = cleanName(entry);
    if (name && !teams.includes(name)) teams.push(name);
    if (teams.length >= MAX_FAVOURITES) break;
  }
  return make(teams, cleanName(value.primary));
}

/** Parse a stored string; missing or corrupt data yields the empty state. */
export function parseFavourites(raw) {
  if (typeof raw !== 'string' || !raw) return EMPTY_FAVOURITES;
  try {
    return sanitizeFavourites(JSON.parse(raw));
  } catch {
    return EMPTY_FAVOURITES;
  }
}

export function serializeFavourites(state) {
  return JSON.stringify({ teams: [...state.teams], primary: state.primary });
}

export function sameFavourites(a, b) {
  return (
    a === b ||
    (a.primary === b.primary &&
      a.teams.length === b.teams.length &&
      a.teams.every((name, i) => name === b.teams[i]))
  );
}

export const isFavourite = (state, name) => state.teams.includes(cleanName(name));
export const isFavouritesFull = (state) => state.teams.length >= MAX_FAVOURITES;

/** Append a team (no-op when blank, already present, or at the cap). */
export function addFavourite(state, name) {
  const team = cleanName(name);
  if (!team || state.teams.includes(team) || isFavouritesFull(state)) return state;
  return make([...state.teams, team], state.primary);
}

/** Remove a team; removing the primary promotes the first remaining team. */
export function removeFavourite(state, name) {
  const team = cleanName(name);
  if (!state.teams.includes(team)) return state;
  return make(state.teams.filter((t) => t !== team), state.primary);
}

export function toggleFavourite(state, name) {
  return isFavourite(state, name) ? removeFavourite(state, name) : addFavourite(state, name);
}

/**
 * Make `name` the primary team, adding it first if needed. No-op for blank
 * names, the current primary, or a new team when the list is full.
 */
export function setPrimaryFavourite(state, name) {
  const team = cleanName(name);
  if (!team || state.primary === team) return state;
  const added = addFavourite(state, team);
  if (!added.teams.includes(team)) return state;
  return make(added.teams, team);
}

export function clearFavourites() {
  return EMPTY_FAVOURITES;
}

function resolveStorage(storage) {
  try {
    const value = typeof storage === 'function' ? storage() : storage;
    return value && typeof value.getItem === 'function' ? value : null;
  } catch {
    return null; // e.g. SecurityError when site data is blocked
  }
}

function readStorage(storage, key) {
  try {
    const store = resolveStorage(storage);
    return store ? parseFavourites(store.getItem(key)) : null;
  } catch {
    return null;
  }
}

/**
 * External store for useSyncExternalStore.
 *
 * - `storage`: a Storage-like object or a function returning one (it may throw;
 *   access is always guarded). Absent/throwing storage → memory only.
 * - `target`: an EventTarget receiving `storage` events (window) for
 *   cross-tab sync; listened to only while there are subscribers.
 */
export function createFavouritesStore({ storage = null, key = FAVOURITES_KEY, target = null } = {}) {
  let state = readStorage(storage, key) ?? EMPTY_FAVOURITES;
  const listeners = new Set();

  const emit = () => {
    for (const listener of [...listeners]) listener();
  };

  const set = (next) => {
    if (next === state || sameFavourites(next, state)) return state;
    state = next;
    try {
      const store = resolveStorage(storage);
      if (store) {
        if (next.teams.length) store.setItem(key, serializeFavourites(next));
        else store.removeItem?.(key);
      }
    } catch {
      // Quota exceeded or storage blocked: keep the in-memory state.
    }
    emit();
    return state;
  };

  const onStorage = (event) => {
    if (event && event.key !== null && event.key !== undefined && event.key !== key) return;
    // A null key means another tab cleared all storage.
    const next = event?.key === null ? EMPTY_FAVOURITES : readStorage(storage, key);
    if (!next || sameFavourites(next, state)) return;
    state = next;
    emit();
  };

  return {
    getSnapshot: () => state,
    getServerSnapshot: () => EMPTY_FAVOURITES,
    subscribe(listener) {
      listeners.add(listener);
      if (listeners.size === 1) target?.addEventListener?.('storage', onStorage);
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) target?.removeEventListener?.('storage', onStorage);
      };
    },
    isFavourite: (name) => isFavourite(state, name),
    add: (name) => set(addFavourite(state, name)),
    remove: (name) => set(removeFavourite(state, name)),
    toggle: (name) => set(toggleFavourite(state, name)),
    setPrimary: (name) => set(setPrimaryFavourite(state, name)),
    clear: () => set(clearFavourites()),
  };
}
