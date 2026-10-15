import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchTrackRecord } from '../api';

/**
 * Loads /track-record for a league (null = all) and a week window. A reload of
 * the same query keeps its data (also after a failed refresh); changing the
 * query drops it so figures for another league are never shown by mistake.
 */
export function useTrackRecord({ league = null, weeks }) {
  const [state, setState] = useState({
    data: null,
    dataKey: null,
    loading: true,
    error: null,
    errorKey: null,
  });
  const controllerRef = useRef(null);

  const key = `${league ?? ''}|${weeks}`;

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fetchTrackRecord({ league, weeks, signal: controller.signal });
      if (controller.signal.aborted) return;
      setState({ data, dataKey: key, loading: false, error: null, errorKey: null });
    } catch (err) {
      if (err?.name === 'AbortError' || controller.signal.aborted) return;
      setState((s) => ({ ...s, loading: false, error: err, errorKey: key }));
    }
  }, [league, weeks, key]);

  useEffect(() => {
    load();
    return () => controllerRef.current?.abort();
  }, [load]);

  // Results belong to the query that produced them; anything else is ignored.
  const current = state.dataKey === key;
  const error = state.errorKey === key ? state.error : null;
  return {
    data: current ? state.data : null,
    loading: !error && (state.loading || !current),
    error,
    reload: load,
  };
}
