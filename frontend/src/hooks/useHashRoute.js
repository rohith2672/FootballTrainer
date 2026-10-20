import { useMemo, useSyncExternalStore } from 'react';
import { ROUTES, legacyView, parseRoute } from '../lib/routes.js';

export { ROUTES };
export { teamHref } from '../lib/teams.js';

function subscribe(callback) {
  window.addEventListener('hashchange', callback);
  return () => window.removeEventListener('hashchange', callback);
}

const getSnapshot = () => window.location.hash;
const getServerSnapshot = () => '';

const useHash = () => useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

/**
 * Current top-level view key derived from location.hash ('upcoming' |
 * 'trackRecord' | 'news'); anything unknown is "upcoming". Team routes
 * ("#/team/<name>") also map to 'upcoming' here so existing callers that index
 * a ROUTES-keyed table keep working — use `useRoute()` to see team routes.
 */
export function useHashRoute() {
  return legacyView(useHash());
}

/**
 * Full route: `{ view, team }` where view is 'upcoming' | 'trackRecord' |
 * 'news' | 'team', and `team` is the decoded canonical name for team routes
 * (null otherwise). Malformed team hashes fall back to 'upcoming'.
 */
export function useRoute() {
  const hash = useHash();
  return useMemo(() => parseRoute(hash), [hash]);
}
