// Centralised access to the prediction API.
//
// VITE_API_URL is baked in at build time. In the Docker image it defaults to
// "/api" (proxied by nginx). During `npm run dev` it falls back to the local
// uvicorn server. An explicit empty string means "same origin".
const DEFAULT_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '/api';
export const API_BASE = String(import.meta.env.VITE_API_URL ?? DEFAULT_BASE).replace(/\/+$/, '');

/**
 * kind: 'network' (never reached the API), 'upstream' (502/503/504, the API
 * or its data provider is unavailable), 'client' (other 4xx), 'server'
 * (other 5xx) or 'parse' (unexpected response body).
 */
export class ApiError extends Error {
  constructor(kind, message, status = null) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
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
    if ([502, 503, 504].includes(status)) {
      throw new ApiError('upstream', `Service unavailable (HTTP ${status}).`, status);
    }
    if (status >= 500) {
      throw new ApiError('server', `The prediction service failed (HTTP ${status}).`, status);
    }
    throw new ApiError('client', `The request was rejected (HTTP ${status}).`, status);
  }

  try {
    return await response.json();
  } catch {
    throw new ApiError('parse', 'The prediction service returned an unreadable response.');
  }
}

/** Fetch the upcoming fixtures. Resolves to an array (possibly empty). */
export async function fetchUpcoming({ signal } = {}) {
  const data = await getJson('/upcoming', { signal });
  if (!Array.isArray(data)) {
    throw new ApiError('parse', 'The prediction service returned an unexpected response.');
  }
  return data;
}

/** Fetch the live track record. Resolves to the raw response object. */
export async function fetchTrackRecord({ league, weeks, signal } = {}) {
  const data = await getJson('/track-record', { signal, params: { league, weeks } });
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

/** Map an error to user-facing copy. */
export function describeError(err) {
  switch (err?.kind) {
    case 'network':
      return {
        title: 'Can’t reach the prediction service',
        message: 'The app could not connect to the backend. Check that the API is running and your connection is working, then try again.',
      };
    case 'upstream':
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
