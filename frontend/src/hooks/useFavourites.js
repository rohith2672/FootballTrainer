import { useMemo, useSyncExternalStore } from 'react';
import { createFavouritesStore } from '../lib/favourites.js';

// One store per page, created on first use so nothing touches localStorage at
// import time. Storage access may throw (blocked site data); the store guards
// every read/write and keeps working in memory.
let defaultStore = null;

function getStore() {
  if (!defaultStore) {
    defaultStore = createFavouritesStore({
      storage: () => window.localStorage,
      target: typeof window === 'undefined' ? null : window,
    });
  }
  return defaultStore;
}

/**
 * Favourite teams shared by every component (and synced across tabs).
 * `primary` is null exactly when `teams` is empty; the first team added
 * becomes primary and removing the primary promotes the first remaining team.
 */
export function useFavourites() {
  const store = getStore();
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
  return useMemo(
    () => ({
      teams: state.teams,
      primary: state.primary,
      isFavourite: (name) => state.teams.includes(name),
      toggle: store.toggle,
      add: store.add,
      remove: store.remove,
      setPrimary: store.setPrimary,
      clear: store.clear,
    }),
    [state, store],
  );
}
