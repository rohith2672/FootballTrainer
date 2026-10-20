import { useMemo, useSyncExternalStore } from 'react';
import { ROUTES, legacyView, parseRoute } from '../lib/routes.js';

export { ROUTES };
export { teamHref } from '../lib/teams.js';

// history.replaceState does not fire hashchange; replaceHash() announces it.
const REPLACED = 'ft:hashreplace';

function subscribe(callback) {
  window.addEventListener('hashchange', callback);
  window.addEventListener(REPLACED, callback);
  return () => {
    window.removeEventListener('hashchange', callback);
    window.removeEventListener(REPLACED, callback);
  };
}

const getSnapshot = () => window.location.hash;
const getServerSnapshot = () => '';

/** The raw location.hash, including any "?query". */
export const useLocationHash = () => useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

/**
 * Swap the current hash without adding a history entry or firing hashchange
 * (used for filter state, which changes on every keystroke).
 */
export function replaceHash(hash) {
  if (window.location.hash === hash || (hash === '#/' && window.location.hash === '')) return;
  try {
    window.history.replaceState(window.history.state, '', hash);
  } catch {
    return; // e.g. a sandboxed frame without history access
  }
  window.dispatchEvent(new Event(REPLACED));
}

/**
 * Current top-level view key derived from location.hash ('upcoming' |
 * 'trackRecord' | 'news'); anything unknown is "upcoming". Team routes
 * ("#/team/<name>") also map to 'upcoming' here so existing callers that index
 * a ROUTES-keyed table keep working — use `useRoute()` to see team routes.
 */
export function useHashRoute() {
  return legacyView(useLocationHash());
}

/**
 * Full route: `{ view, team }` where view is 'upcoming' | 'trackRecord' |
 * 'news' | 'team', and `team` is the decoded canonical name for team routes
 * (null otherwise). Malformed team hashes fall back to 'upcoming'.
 */
export function useRoute() {
  const hash = useLocationHash();
  return useMemo(() => parseRoute(hash), [hash]);
}
