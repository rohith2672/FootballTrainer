import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchNews } from '../api';
import { ageNewsCache, nextNewsBoundary, subscribeNewsPolling } from '../lib/news';

export function useNews() {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const controllerRef = useRef(null);
  const load = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const data = await fetchNews({ signal: controller.signal });
      if (!controller.signal.aborted) setState({ data: ageNewsCache(data), loading: false, error: null });
    } catch (error) {
      if (!controller.signal.aborted && error?.name !== 'AbortError') {
        setState((previous) => ({ ...previous, data: ageNewsCache(previous.data), loading: false, error }));
      }
    }
  }, []);

  useEffect(() => {
    load();
    const unsubscribe = subscribeNewsPolling(load);
    return () => {
      unsubscribe();
      controllerRef.current?.abort();
    };
  }, [load]);

  useEffect(() => {
    const delay = nextNewsBoundary(state.data);
    if (delay === null) return;
    const timer = setTimeout(() => {
      setState((previous) => ({ ...previous, data: ageNewsCache(previous.data) }));
    }, delay);
    return () => clearTimeout(timer);
  }, [state.data]);

  return { ...state, reload: load };
}
