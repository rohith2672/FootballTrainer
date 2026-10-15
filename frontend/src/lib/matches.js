// Pure helpers for turning /upcoming items into display-ready fixtures.
// Works with both the original response shape and the extended one
// (kickoff, prediction_available, is_fallback, reason, fixture_id, ...).
// Missing new fields are treated as unknown.

export const ALL_LEAGUES = 'ALL';

export const LEAGUES = {
  PL: { name: 'Premier League', emoji: '\u{1F3F4}\u{E0067}\u{E0062}\u{E0065}\u{E006E}\u{E0067}\u{E007F}' },
  PD: { name: 'La Liga', emoji: '\u{1F1EA}\u{1F1F8}' },
  SA: { name: 'Serie A', emoji: '\u{1F1EE}\u{1F1F9}' },
  BL1: { name: 'Bundesliga', emoji: '\u{1F1E9}\u{1F1EA}' },
  FL1: { name: 'Ligue 1', emoji: '\u{1F1EB}\u{1F1F7}' },
  CL: { name: 'Champions League', emoji: '\u{1F3C6}' },
};

export function leagueInfo(code) {
  return LEAGUES[code] ?? { name: code || 'Other', emoji: '⚽' };
}

const pad = (n) => String(n).padStart(2, '0');

/** Local calendar date key (YYYY-MM-DD) for a Date. */
export function localDateKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Parse "YYYY-MM-DD" as a local calendar date (no timezone shift). */
export function parseLocalDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  if (!m) return null;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Lower-case, accent-insensitive text for searching. */
export function normalizeText(value) {
  return String(value ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}

const isProb = (v) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1;

// The legacy backend substitutes this exact triple when scoring fails and does
// not flag it. Treat it as a placeholder unless the response says otherwise.
function isLegacyPlaceholder(raw) {
  // Any v2 field means the backend is flag-aware, so its values are authoritative.
  const v2 = ['is_fallback', 'prediction_available', 'model_version', 'top_factors', 'details'];
  if (v2.some((key) => raw[key] !== undefined)) return false;
  const near = (a, b) => Math.abs(a - b) < 1e-9;
  return near(raw.home_win, 0.33) && near(raw.draw, 0.34) && near(raw.away_win, 0.33);
}

function noPredictionReason(raw, placeholder) {
  if (typeof raw.reason === 'string' && raw.reason.trim()) return raw.reason.trim();
  if (placeholder || raw.is_fallback === true) {
    return 'the model could not score this fixture, so only a generic placeholder was available';
  }
  return 'no model prediction is available for this fixture';
}

function normalizeMatch(raw) {
  const kickoffDate = raw.kickoff ? new Date(raw.kickoff) : null;
  const kickoff = kickoffDate && !Number.isNaN(kickoffDate.getTime()) ? kickoffDate : null;

  const dateKey = kickoff ? localDateKey(kickoff) : String(raw.date ?? '').slice(0, 10);
  const day = parseLocalDate(dateKey);

  const placeholder = isLegacyPlaceholder(raw);
  const probsOk = isProb(raw.home_win) && isProb(raw.draw) && isProb(raw.away_win);
  const hasPrediction =
    probsOk && raw.prediction_available !== false && raw.is_fallback !== true && !placeholder;

  let outcome = null;
  let confidence = null;
  if (hasPrediction) {
    const { home_win: h, draw: d, away_win: a } = raw;
    confidence = Math.max(h, d, a);
    outcome = h === confidence ? 'home' : d === confidence ? 'draw' : 'away';
  }

  return {
    ...raw,
    kickoffDate: kickoff,
    dateKey,
    sortTime: kickoff ? kickoff.getTime() : day ? day.getTime() : Number.MAX_SAFE_INTEGER,
    hasPrediction,
    noPredictionReason: hasPrediction ? null : noPredictionReason(raw, placeholder),
    confidence,
    outcome,
  };
}

/** Normalise the API payload and assign stable, unique keys. */
export function normalizeMatches(rawList) {
  const seen = new Map();
  return rawList.map((raw) => {
    const match = normalizeMatch(raw);
    const base =
      raw.fixture_id != null
        ? `fx-${raw.fixture_id}`
        : `${raw.league}|${raw.date}|${raw.home_team}|${raw.away_team}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    match.key = count ? `${base}#${count}` : base;
    return match;
  });
}

/** Leagues present in the data: known leagues in canonical order, then others. */
export function leaguesPresent(matches) {
  const present = new Set(matches.map((m) => m.league || 'Other'));
  const known = Object.keys(LEAGUES).filter((code) => present.has(code));
  const other = [...present].filter((code) => !(code in LEAGUES)).sort();
  return [...known, ...other];
}

export function defaultLeague(codes) {
  if (codes.includes('PL')) return 'PL';
  return codes[0] ?? null;
}

export function filterMatches(matches, { query = '', from = '', to = '' } = {}) {
  const q = normalizeText(query);
  return matches.filter((m) => {
    if (q && !normalizeText(m.home_team).includes(q) && !normalizeText(m.away_team).includes(q)) {
      return false;
    }
    if (from && m.dateKey < from) return false;
    if (to && m.dateKey > to) return false;
    return true;
  });
}

export function sortMatches(matches, sort) {
  const list = [...matches];
  if (sort === 'confidence') {
    // Matches without a prediction go last.
    list.sort(
      (a, b) =>
        (b.confidence ?? -1) - (a.confidence ?? -1) || a.sortTime - b.sortTime,
    );
  } else {
    list.sort((a, b) => a.sortTime - b.sortTime || a.home_team.localeCompare(b.home_team));
  }
  return list;
}

export function groupByDate(matches) {
  const groups = [];
  for (const m of matches) {
    const last = groups[groups.length - 1];
    if (last && last.dateKey === m.dateKey) last.matches.push(m);
    else groups.push({ dateKey: m.dateKey, matches: [m] });
  }
  return groups;
}

/** Heading for a date group, e.g. "Saturday, 3 January". */
export function formatDateHeading(dateKey) {
  const day = parseLocalDate(dateKey);
  if (!day) return 'Date to be confirmed';
  const options = { weekday: 'long', month: 'long', day: 'numeric' };
  if (day.getFullYear() !== new Date().getFullYear()) options.year = 'numeric';
  return new Intl.DateTimeFormat(undefined, options).format(day);
}

/** Kickoff in the browser's locale/timezone, or just the date if no time is known. */
export function formatKickoff(match) {
  if (match.kickoffDate) {
    return {
      text: new Intl.DateTimeFormat(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      }).format(match.kickoffDate),
      iso: match.kickoffDate.toISOString(),
    };
  }
  const day = parseLocalDate(match.dateKey);
  if (!day) return { text: 'Date to be confirmed', iso: undefined };
  return {
    text: new Intl.DateTimeFormat(undefined, {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    }).format(day),
    iso: match.dateKey,
  };
}

export const pct = (p) => `${Math.round(p * 100)}%`;

/** "Arsenal FC to win", "Draw most likely" for a match that has a prediction. */
export function outcomeLabel(match) {
  if (match.outcome === 'home') return `${match.home_team} to win`;
  if (match.outcome === 'away') return `${match.away_team} to win`;
  return 'Draw most likely';
}
