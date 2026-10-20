import { useCallback, useEffect, useRef, useState } from 'react';
import { getH2H } from '../api';

/**
 * Head-to-head between two canonical team names.
 *
 * `useH2H(a, b, { limit = 10 })` returns `{ data, loading, error, reload }`.
 * Idle (no request, everything null/false) when either name is blank or both
 * are the same team. Results are keyed by query, so a previous pair's data is
 * never shown for a new pair.
 */
export function useH2H(a, b, { limit = 10 } = {}) {
  const teamA = typeof a === 'string' ? a.trim() : '';
  const teamB = typeof b === 'string' ? b.trim() : '';
  const enabled = Boolean(teamA && teamB && teamA !== teamB);
  const key = `${teamA}|${teamB}|${limit}`;

  const [state, setState] = useState({
    data: null,
    dataKey: null,
    loading: false,
    error: null,
    errorKey: null,
  });
  const controllerRef = useRef(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    if (!enabled) return;
    const controller = new AbortController();
    controllerRef.current = controller;

    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await getH2H(teamA, teamB, { limit, signal: controller.signal });
      if (controller.signal.aborted) return;
      setState({ data, dataKey: key, loading: false, error: null, errorKey: null });
    } catch (err) {
      if (err?.name === 'AbortError' || controller.signal.aborted) return;
      setState((s) => ({ ...s, loading: false, error: err, errorKey: key }));
    }
  }, [enabled, teamA, teamB, limit, key]);

  useEffect(() => {
    load();
    return () => controllerRef.current?.abort();
  }, [load]);

  if (!enabled) return { data: null, loading: false, error: null, reload: load };

  const current = state.dataKey === key;
  const error = state.errorKey === key ? state.error : null;
  return {
    data: current ? state.data : null,
    loading: !error && (state.loading || !current),
    error,
    reload: load,
  };
}
