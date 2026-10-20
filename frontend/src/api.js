// Centralised access to the prediction API.
//
// VITE_API_URL is baked in at build time. In the Docker image it defaults to
// "/api" (proxied by nginx). During `npm run dev` it falls back to the local
// uvicorn server. An explicit empty string means "same origin".
import { normalizeNews } from './lib/news.js';

const DEFAULT_BASE = import.meta.env?.DEV ? 'http://localhost:8000' : '/api';
export const API_BASE = String(import.meta.env?.VITE_API_URL ?? DEFAULT_BASE).replace(/\/+$/, '');

/**
 * kind: 'network' (never reached the API), 'upstream' (502/503/504, the API
 * or its data provider is unavailable), 'client' (other 4xx), 'server'
 * (other 5xx) or 'parse' (unexpected response body).
 */
export class ApiError extends Error {
  /** `detail`: the server's `{"detail": "..."}` string for non-2xx responses, if any. */
  constructor(kind, message, status = null, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

async function readDetail(response) {
  try {
    const body = await response.json();
    return typeof body?.detail === 'string' && body.detail.trim() ? body.detail.trim() : null;
  } catch {
    return null;
  }
}

/**
 * GET `path` and resolve to the parsed JSON body. Network failures and non-2xx
 * statuses are turned into ApiError; AbortError is rethrown untouched.
 */
async function getJson(path, { signal, params } = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
  }
  const qs = query.toString();

  let response;
  try {
    response = await fetch(`${API_BASE}${path}${qs ? `?${qs}` : ''}`, {
      signal,
      headers: { Accept: 'application/json' },
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    throw new ApiError('network', 'Could not connect to the prediction service.');
  }

  if (!response.ok) {
    const { status } = response;
    const detail = await readDetail(response);
    if ([502, 503, 504].includes(status)) {
      throw new ApiError('upstream', `Service unavailable (HTTP ${status}).`, status, detail);
    }
    if (status >= 500) {
      throw new ApiError('server', `The prediction service failed (HTTP ${status}).`, status, detail);
    }
    throw new ApiError('client', `The request was rejected (HTTP ${status}).`, status, detail);
  }

  try {
    return await response.json();
  } catch {
    throw new ApiError('parse', 'The prediction service returned an unreadable response.');
  }
}

const unexpected = () => new ApiError('parse', 'The prediction service returned an unexpected response.');
const isObject = (v) => !!v && typeof v === 'object' && !Array.isArray(v);

/**
 * Fetch the upcoming fixtures. Resolves to an array (possibly empty).
 * `team` (optional, canonical name) keeps only fixtures involving that team.
 */
export async function fetchUpcoming({ signal, team } = {}) {
  const data = await getJson('/upcoming', { signal, params: { team } });
  if (!Array.isArray(data)) throw unexpected();
  return data;
}

/** Path segment for a team name; names contain spaces, "&", "." and accents. */
function teamPath(name, suffix = '') {
  const team = typeof name === 'string' ? name.trim() : '';
  if (!team) throw new ApiError('client', 'A team name is required.');
  return `/teams/${encodeURIComponent(team)}${suffix}`;
}

/** GET /teams/index → [{name, league|null}] sorted by league then name. */
export async function getTeamsIndex({ signal } = {}) {
  const data = await getJson('/teams/index', { signal });
  if (!Array.isArray(data)) throw unexpected();
  return data.filter((t) => isObject(t) && typeof t.name === 'string' && t.name);
}

/** GET /teams/{name}?as_of= → team profile object (404 → ApiError client/404). */
export async function getTeam(name, { asOf, signal } = {}) {
  const data = await getJson(teamPath(name), { signal, params: { as_of: asOf } });
  if (!isObject(data) || typeof data.name !== 'string') throw unexpected();
  return data;
}

/** GET /teams/{name}/matches?limit=&venue= → match rows, newest first. */
export async function getTeamMatches(name, { limit, venue, signal } = {}) {
  const data = await getJson(teamPath(name, '/matches'), {
    signal,
    params: { limit, venue: venue && venue !== 'all' ? venue : undefined },
  });
  if (!Array.isArray(data)) throw unexpected();
  return data;
}

/** GET /teams/{name}/elo-history?since= → {team, points: [...]}, ascending by date. */
export async function getEloHistory(name, { since, signal } = {}) {
  const data = await getJson(teamPath(name, '/elo-history'), { signal, params: { since } });
  if (!isObject(data) || !Array.isArray(data.points)) throw unexpected();
  return data;
}

/** GET /h2h?a=&b=&limit= → head-to-head totals and the newest meetings. */
export async function getH2H(a, b, { limit, signal } = {}) {
  const teamA = typeof a === 'string' ? a.trim() : '';
  const teamB = typeof b === 'string' ? b.trim() : '';
  if (!teamA || !teamB) throw new ApiError('client', 'Two team names are required.');
  const data = await getJson('/h2h', { signal, params: { a: teamA, b: teamB, limit } });
  if (!isObject(data) || !Array.isArray(data.meetings)) throw unexpected();
  return data;
}

/** True for a 404 whose detail says the team is unknown (vs. a missing endpoint). */
export function isTeamNotFound(err) {
  return err?.kind === 'client' && err.status === 404 && /^Team not found/i.test(err.detail ?? '');
}

/** Error copy for team pages. */
export function describeTeamError(err) {
  if (isTeamNotFound(err)) {
    return {
      title: 'Team not found',
      message: `${err.detail}. Check the name or pick a team from the list.`,
    };
  }
  if (err?.kind === 'client' && err.status === 404) {
    return {
      title: 'Team analysis isn’t available yet',
      message:
        'The service does not expose the team endpoints. The backend may not have been updated yet — try again after the next deploy.',
    };
  }
  if (err?.kind === 'client' && err.status === 422 && err.detail) {
    return { title: 'Request rejected', message: err.detail };
  }
  if (err?.kind === 'upstream') {
    return {
      title: 'Team data temporarily unavailable',
      message: `${err.message} This is usually temporary — try again in a minute.`,
    };
  }
  return describeError(err);
}

/** Read the server's news cache; this never initiates publisher ingestion. */
export async function fetchNews({ signal } = {}) {
  const data = await getJson('/news', { signal, params: { limit: 50 } });
  try {
    return normalizeNews(data);
  } catch (error) {
    throw new ApiError('parse', error.message);
  }
}

/**
 * Fetch the live track record. Resolves to the raw response object.
 * `team` (optional) restricts it to stored predictions involving that team.
 */
export async function fetchTrackRecord({ league, weeks, team, signal } = {}) {
  const data = await getJson('/track-record', { signal, params: { league, weeks, team } });
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new ApiError('parse', 'The prediction service returned an unexpected response.');
  }
  return data;
}

/** Error copy for the track-record page (the endpoint may not be deployed yet). */
export function describeTrackRecordError(err) {
  if (err?.kind === 'client' && err.status === 404) {
    return {
      title: 'Track record isn’t available yet',
      message:
        'The service does not expose a track record endpoint. The backend may not have been updated yet — try again after the next deploy.',
    };
  }
  if (err?.kind === 'upstream') {
    return {
      title: 'Track record temporarily unavailable',
      message: `${err.message} This is usually temporary — try again in a minute.`,
    };
  }
  return describeError(err);
}

/**
 * True when an upstream (502/503/504) error's detail says a data source is not
 * configured (e.g. "Fixture source not configured (FOOTBALL_DATA_API_KEY
 * missing)"): a permanent setup problem rather than a transient outage.
 */
export function isNotConfigured(err) {
  return err?.kind === 'upstream' && typeof err.detail === 'string' && /not configured|api[_ ]?key/i.test(err.detail);
}

/** Map an error to user-facing copy. */
export function describeError(err) {
  switch (err?.kind) {
    case 'network':
      return {
        title: 'Can’t reach the prediction service',
        message: 'The app could not connect to the backend. Check that the API is running and your connection is working, then try again.',
      };
    case 'upstream':
      if (isNotConfigured(err)) {
        return {
          title: 'Data source not configured',
          message: `${err.detail.replace(/\.?$/, '.')} This is a server configuration problem, not a temporary outage — retrying won’t help until it is fixed.`,
        };
      }
      return {
        title: 'Couldn’t reach the data provider',
        message: 'The prediction service is up but could not get fixtures from the data provider right now. This is usually temporary — try again in a minute.',
      };
    case 'server':
      return {
        title: 'The prediction service hit an error',
        message: `${err.message} Try again shortly.`,
      };
    case 'client':
      return {
        title: 'Request rejected',
        message: `${err.message} This looks like a configuration problem rather than a temporary outage.`,
      };
    case 'parse':
      return {
        title: 'Unexpected response',
        message: err.message,
      };
    default:
      return {
        title: 'Something went wrong',
        message: 'Unable to load predictions. Please try again.',
      };
  }
}
