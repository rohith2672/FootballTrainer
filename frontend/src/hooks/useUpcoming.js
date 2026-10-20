import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchUpcoming } from '../api';

/**
 * Loads /upcoming and exposes a reload function. Previously loaded data is
 * kept while refreshing or after a failed refresh so the page never blanks.
 * `team` (optional, canonical name) keeps only fixtures involving that team;
 * callers that pass it should remount (key) the consumer when it changes.
 */
export function useUpcoming({ team = null } = {}) {
  const [state, setState] = useState({
    matches: [],
    loading: true,
    error: null,
    updatedAt: null,
  });
  const controllerRef = useRef(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const matches = await fetchUpcoming({ team: team ?? undefined, signal: controller.signal });
      if (controller.signal.aborted) return;
      setState({ matches, loading: false, error: null, updatedAt: new Date() });
    } catch (err) {
      if (err?.name === 'AbortError' || controller.signal.aborted) return;
      setState((s) => ({ ...s, loading: false, error: err }));
    }
  }, [team]);

  useEffect(() => {
    load();
    return () => controllerRef.current?.abort();
  }, [load]);

  return { ...state, reload: load };
}
