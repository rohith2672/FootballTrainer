import { useSyncExternalStore } from 'react';

export const ROUTES = {
  upcoming: '#/',
  trackRecord: '#/track-record',
  news: '#/news',
};

function subscribe(callback) {
  window.addEventListener('hashchange', callback);
  return () => window.removeEventListener('hashchange', callback);
}

const getSnapshot = () => window.location.hash;
const getServerSnapshot = () => '';

/** Current view derived from location.hash; anything unknown is "upcoming". */
export function useHashRoute() {
  const hash = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const normalized = hash.replace(/\/+$/, '');
  return Object.keys(ROUTES).find((key) => ROUTES[key] === normalized) ?? 'upcoming';
}
