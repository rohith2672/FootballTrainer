import { useCallback, useEffect, useState } from 'react';
import { getEloHistory, getTeam, getTeamMatches } from '../api';
import {
  EMPTY_CORE,
  EMPTY_LIST,
  coreFailed,
  coreLoaded,
  listFailed,
  listLoaded,
  teamView,
} from '../lib/teamPage.js';

const isAbort = (err) => err?.name === 'AbortError';

const IDLE = {
  data: null,
  partialErrors: { matches: null, eloHistory: null },
  loading: false,
  profileLoading: false,
  matchesLoading: false,
  error: null,
  stale: false,
};

/**
 * Team page data.
 *
 * `useTeam(name, { asOf, limit = 20, venue = 'all', since })` returns
 *   {
 *     data: { profile, matches, eloHistory } | null,
 *     loading, profileLoading, matchesLoading,
 *     error,                   // the profile request failed (page level)
 *     partialErrors: { matches, eloHistory },  // per-section failures (or null)
 *     stale,                   // `matches` are from another venue/limit (loading or failed)
 *     refetch,
 *   }
 *
 * The profile and Elo history are keyed by team (+ asOf / since); the match
 * list by team + venue + limit, so changing the venue or limit refetches only
 * `/teams/{name}/matches`. Another team's data is never returned. When a
 * request fails, the last data for the same team stays visible. A null/blank
 * `name` is idle: no request, everything null.
 */
export function useTeam(name, { asOf = null, limit = 20, venue = 'all', since = null } = {}) {
  const team = typeof name === 'string' ? name.trim() : '';
  // Bumped by refetch() so both requests run again with new keys.
  const [nonce, setNonce] = useState(0);
  const teamKey = `${team}|${asOf ?? ''}`;
  const coreKey = `${teamKey}|${since ?? ''}|${nonce}`;
  const matchesKey = `${teamKey}|${venue}|${limit}|${nonce}`;

  const [core, setCore] = useState(EMPTY_CORE);
  const [list, setList] = useState(EMPTY_LIST);

  // Profile + Elo history. State is only set when a response arrives; until
  // then "loading" is derived from the key mismatch.
  useEffect(() => {
    if (!team) return undefined;
    const controller = new AbortController();
    const { signal } = controller;
    Promise.allSettled([
      getTeam(team, { asOf: asOf ?? undefined, signal }),
      getEloHistory(team, { since: since ?? undefined, signal }),
    ]).then(([profile, elo]) => {
      if (signal.aborted) return;
      if (profile.status === 'rejected') {
        if (!isAbort(profile.reason)) setCore((s) => coreFailed(s, { key: coreKey, teamKey, error: profile.reason }));
        return;
      }
      const eloError = elo.status === 'rejected' && !isAbort(elo.reason) ? elo.reason : null;
      setCore((s) =>
        coreLoaded(s, {
          key: coreKey,
          teamKey,
          profile: profile.value,
          eloHistory: elo.status === 'fulfilled' ? elo.value : null,
          eloError,
        }),
      );
    });
    return () => controller.abort();
  }, [team, asOf, since, coreKey, teamKey]);

  // Match list.
  useEffect(() => {
    if (!team) return undefined;
    const controller = new AbortController();
    const { signal } = controller;
    getTeamMatches(team, { limit, venue, signal }).then(
      (rows) => {
        if (!signal.aborted) setList((s) => listLoaded(s, { key: matchesKey, teamKey, rows }));
      },
      (error) => {
        if (signal.aborted || isAbort(error)) return;
        setList((s) => listFailed(s, { key: matchesKey, teamKey, error }));
      },
    );
    return () => controller.abort();
  }, [team, limit, venue, matchesKey, teamKey]);

  const refetch = useCallback(() => {
    if (team) setNonce((n) => n + 1);
  }, [team]);

  if (!team) return { ...IDLE, refetch };
  return { ...teamView(core, list, { coreKey, matchesKey, teamKey }), refetch };
}
