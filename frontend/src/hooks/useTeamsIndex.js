import { useCallback, useEffect, useRef, useState } from 'react';
import { getTeamsIndex } from '../api';
import { createSessionCache } from '../lib/sessionCache.js';

// Shared by every consumer for the whole page session.
const cache = createSessionCache(() => getTeamsIndex());

/**
 * `/teams/index`, fetched once per session and shared by all components.
 * Returns `{ teams: [{name, league}], loading, error, reload }`; `teams` is []
 * until loaded. A failed load is not cached — `reload()` retries, and also
 * forces a refresh after a success.
 */
export function useTeamsIndex() {
  const [state, setState] = useState(() => ({
    teams: cache.peek() ?? null,
    loading: !cache.has(),
    error: null,
  }));
  const mounted = useRef(true);

  const settle = useCallback((promise) => {
    promise.then(
      (teams) => {
        if (mounted.current) setState({ teams, loading: false, error: null });
      },
      (error) => {
        if (mounted.current) setState((s) => ({ ...s, loading: false, error }));
      },
    );
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!cache.has()) settle(cache.load());
    return () => {
      mounted.current = false;
    };
  }, [settle]);

  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }));
    settle(cache.load({ force: true }));
  }, [settle]);

  return { teams: state.teams ?? [], loading: state.loading, error: state.error, reload };
}
