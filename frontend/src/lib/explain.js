// Pure helpers for the "Why this prediction?" panel. Everything tolerates
// missing or malformed data: the backend may omit any of these fields.

export const DASH = '—';

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

/** Fixed-decimals number, or an em dash for null/NaN. */
export function fmtNumber(value, digits = 1) {
  return isNum(value) ? value.toFixed(digits) : DASH;
}

/** Raw feature value: integers stay whole, others get up to 2 decimals. */
export function fmtRawValue(value) {
  if (value === null || value === undefined) return DASH;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (!isNum(value)) return String(value);
  if (Number.isInteger(value)) return String(value);
  return String(Number(value.toFixed(2)));
}

/** Signed contribution, e.g. "+0.21" / "−0.08" (real minus sign). */
export function fmtContribution(value) {
  if (!isNum(value)) return DASH;
  const text = Math.abs(value).toFixed(2);
  if (Number(text) === 0) return '0.00';
  return `${value > 0 ? '+' : '−'}${text}`;
}

/** Valid factors in the order given, with a usable label and numeric contribution. */
export function getFactors(match) {
  if (!Array.isArray(match?.top_factors)) return [];
  return match.top_factors
    .filter((f) => f && typeof f === 'object' && isNum(f.contribution))
    .map((f, i) => ({
      key: `${f.feature ?? 'factor'}-${i}`,
      label: String(f.label || f.feature || 'Factor'),
      value: f.value,
      contribution: f.contribution,
    }));
}

/** details object when it carries at least one of home / away / h2h. */
export function getDetails(match) {
  const d = match?.details;
  if (!d || typeof d !== 'object') return null;
  const ok = (x) => x && typeof x === 'object';
  if (!ok(d.home) && !ok(d.away) && !ok(d.h2h)) return null;
  return { home: ok(d.home) ? d.home : {}, away: ok(d.away) ? d.away : {}, h2h: ok(d.h2h) ? d.h2h : null };
}

/** What the explanation panel can show for a match (factors only with a prediction). */
export function explanationContent(match) {
  const factors = match?.hasPrediction ? getFactors(match) : [];
  const details = getDetails(match);
  return { factors, details, any: factors.length > 0 || details !== null };
}

/** Rows for the home/away comparison table. */
export const DETAIL_ROWS = [
  { key: 'elo', label: 'Elo rating', format: (v) => fmtNumber(v, 0) },
  { key: 'form_pts_pg', label: 'Form (points per game)', format: (v) => fmtNumber(v, 2) },
  { key: 'goals_for_avg', label: 'Goals scored (avg)', format: (v) => fmtNumber(v, 2) },
  { key: 'goals_against_avg', label: 'Goals conceded (avg)', format: (v) => fmtNumber(v, 2) },
  { key: 'shots_for_avg', label: 'Shots (avg)', format: (v) => fmtNumber(v, 1) },
  {
    key: 'days_since_last',
    label: 'Days since last match',
    format: (v) => (isNum(v) ? String(Math.round(v)) : DASH),
  },
];

/** One-line head-to-head summary, or null when no h2h block exists. */
export function h2hSummary(h2h, homeTeam) {
  if (!h2h) return null;
  const n = isNum(h2h.n) ? h2h.n : null;
  if (n === 0) return 'No previous meetings on record.';
  const meetings = n === null ? 'Previous meetings' : `${n} previous ${n === 1 ? 'meeting' : 'meetings'}`;
  if (!isNum(h2h.home_pts_rate)) return `${meetings}; points rate unavailable.`;
  const rate = Math.round(h2h.home_pts_rate * 100);
  return `${meetings}: ${homeTeam} took ${rate}% of the available points.`;
}

/** Footnote on how many matches the form averages cover. */
export function formBasis(details) {
  const h = details.home.form_n;
  const a = details.away.form_n;
  if (!isNum(h) && !isNum(a)) return null;
  if (isNum(h) && isNum(a) && h === a) return `Form and goal averages use each team’s last ${h} matches.`;
  return `Form and goal averages use the last ${isNum(h) ? h : '—'} (home) and ${isNum(a) ? a : '—'} (away) matches.`;
}
