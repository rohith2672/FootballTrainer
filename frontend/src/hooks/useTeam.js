import { useCallback, useEffect, useRef, useState } from 'react';
import { getEloHistory, getTeam, getTeamMatches } from '../api';

const settledValue = (result) => (result.status === 'fulfilled' ? result.value : null);
const settledError = (result) => (result.status === 'rejected' ? result.reason : null);
const isAbort = (err) => err?.name === 'AbortError';

/** Profile is required (its error rejects); matches/Elo failures are partial. */
async function fetchTeamBundle(team, { asOf, limit, venue, since }, signal) {
  const [profile, matches, eloHistory] = await Promise.allSettled([
    getTeam(team, { asOf: asOf ?? undefined, signal }),
    getTeamMatches(team, { limit, venue, signal }),
    getEloHistory(team, { since: since ?? undefined, signal }),
  ]);
  if (profile.status === 'rejected') throw profile.reason;
  const partial = (result) => {
    const err = settledError(result);
    return err && !isAbort(err) ? err : null;
  };
  return {
    data: {
      profile: profile.value,
      matches: settledValue(matches),
      eloHistory: settledValue(eloHistory),
    },
    partialErrors: { matches: partial(matches), eloHistory: partial(eloHistory) },
  };
}

/**
 * Team page data: profile, recent matches and Elo history fetched in parallel.
 *
 * `useTeam(name, { asOf, limit = 20, venue = 'all', since })` returns
 *   {
 *     data: { profile, matches, eloHistory } | null,
 *     loading, error,          // error = the profile request failed (page-level)
 *     partialErrors: { matches, eloHistory },  // per-section failures (or null)
 *     stale,                   // data is from the same team but other options
 *     refetch,
 *   }
 *
 * Data belongs to the query that produced it: another team's data is never
 * returned. When only `venue`/`limit`/`since` change for the same team the
 * previous data stays visible (`stale: true`, `loading: true`) until the new
 * response arrives. A null/blank `name` is idle: no request, everything null.
 */
export function useTeam(name, { asOf = null, limit = 20, venue = 'all', since = null } = {}) {
  const team = typeof name === 'string' ? name.trim() : '';
  const teamKey = `${team}|${asOf ?? ''}`;
  const key = `${teamKey}|${limit}|${venue}|${since ?? ''}`;

  const [state, setState] = useState({
    data: null,
    partialErrors: { matches: null, eloHistory: null },
    dataKey: null,
    dataTeamKey: null,
    loading: false,
    error: null,
    errorKey: null,
  });
  const controllerRef = useRef(null);

  const load = useCallback(async () => {
    controllerRef.current?.abort();
    if (!team) return;
    const controller = new AbortController();
    controllerRef.current = controller;

    // No synchronous setState here (this runs inside an effect): a new query
    // is "loading" because its key differs from dataKey; refetch() sets the
    // flag explicitly for a reload of the same query.
    try {
      const bundle = await fetchTeamBundle(team, { asOf, limit, venue, since }, controller.signal);
      if (controller.signal.aborted) return;
      setState({
        data: bundle.data,
        partialErrors: bundle.partialErrors,
        dataKey: key,
        dataTeamKey: teamKey,
        loading: false,
        error: null,
        errorKey: null,
      });
    } catch (err) {
      if (isAbort(err) || controller.signal.aborted) return;
      setState((s) => ({ ...s, loading: false, error: err, errorKey: key }));
    }
  }, [team, asOf, limit, venue, since, key, teamKey]);

  useEffect(() => {
    load();
    return () => controllerRef.current?.abort();
  }, [load]);

  const refetch = useCallback(() => {
    if (!team) return;
    setState((s) => ({ ...s, loading: true, error: null, errorKey: null }));
    load();
  }, [team, load]);

  if (!team) {
    return {
      data: null,
      partialErrors: { matches: null, eloHistory: null },
      loading: false,
      error: null,
      stale: false,
      refetch,
    };
  }

  const sameTeam = state.dataTeamKey === teamKey;
  const current = state.dataKey === key;
  const error = state.errorKey === key ? state.error : null;
  return {
    data: sameTeam ? state.data : null,
    partialErrors: sameTeam ? state.partialErrors : { matches: null, eloHistory: null },
    loading: !error && (state.loading || !current),
    error,
    stale: sameTeam && !current,
    refetch,
  };
}
