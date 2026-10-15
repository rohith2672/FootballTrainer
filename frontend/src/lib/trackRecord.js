// Pure helpers for the track-record page. Lower log-loss is better.
import { DASH } from './explain';
import { parseLocalDate } from './matches';

export const WEEK_OPTIONS = [8, 13, 26, 52];
export const DEFAULT_WEEKS = 26;

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const arr = (v) => (Array.isArray(v) ? v : []);
const obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
const numOrNull = (v) => (isNum(v) ? v : null);

export const fmtLogLoss = (v) => (isNum(v) ? v.toFixed(3) : DASH);
export const fmtPercent = (v) => (isNum(v) ? `${(v * 100).toFixed(1)}%` : DASH);
export const fmtPct0 = (v) => (isNum(v) ? `${Math.round(v * 100)}%` : DASH);

/** Signed difference with a real minus sign, e.g. "+0.012", "−0.020". */
export function fmtGap(v) {
  if (!isNum(v)) return DASH;
  const text = Math.abs(v).toFixed(3);
  if (Number(text) === 0) return '0.000';
  return `${v > 0 ? '+' : '−'}${text}`;
}

export const gapOf = (model, book) => (isNum(model) && isNum(book) ? model - book : null);

/** "12 Oct" from a YYYY-MM-DD string. */
export function fmtShortDate(value) {
  const d = parseLocalDate(value);
  if (!d) return String(value ?? DASH);
  return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }).format(d);
}

export function fmtLongDate(value) {
  const d = parseLocalDate(value);
  if (!d) return String(value ?? DASH);
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(d);
}

/** Coerce the response into a predictable shape; unknown/missing parts become null/[]. */
export function normalizeTrackRecord(raw) {
  const overall = obj(raw.overall);
  const baselines = obj(raw.baselines);
  const backtest = raw.backtest && typeof raw.backtest === 'object' ? obj(raw.backtest) : null;
  const bookmaker = obj(baselines.bookmaker);
  const prior = obj(baselines.class_prior);
  const uniform = obj(baselines.uniform);

  return {
    modelVersion: typeof raw.model_version === 'string' ? raw.model_version : null,
    nPredictions: numOrNull(raw.n_predictions) ?? 0,
    nSettled: numOrNull(raw.n_settled) ?? 0,
    overall: {
      logLoss: numOrNull(overall.log_loss),
      accuracy: numOrNull(overall.accuracy),
      brier: numOrNull(overall.brier),
    },
    baselines: {
      bookmaker: { logLoss: numOrNull(bookmaker.log_loss), n: numOrNull(bookmaker.n) },
      classPrior: { logLoss: numOrNull(prior.log_loss), n: numOrNull(prior.n) },
      uniform: { logLoss: numOrNull(uniform.log_loss), n: numOrNull(uniform.n) },
    },
    byLeague: arr(raw.by_league)
      .filter((r) => r && typeof r === 'object')
      .map((r) => ({
        league: String(r.league ?? ''),
        n: numOrNull(r.n) ?? 0,
        logLoss: numOrNull(r.log_loss),
        accuracy: numOrNull(r.accuracy),
        bookmakerLogLoss: numOrNull(r.bookmaker_log_loss),
      })),
    timeline: arr(raw.timeline)
      .filter((r) => r && typeof r === 'object' && r.week_start)
      .map((r) => ({
        weekStart: String(r.week_start),
        n: numOrNull(r.n) ?? 0,
        logLoss: numOrNull(r.log_loss),
        accuracy: numOrNull(r.accuracy),
        bookmakerLogLoss: numOrNull(r.bookmaker_log_loss),
      }))
      .sort((a, b) => a.weekStart.localeCompare(b.weekStart)),
    recent: arr(raw.recent).filter((r) => r && typeof r === 'object'),
    backtest: backtest
      ? {
          source: typeof backtest.source === 'string' ? backtest.source : null,
          bestModel: typeof backtest.best_model === 'string' ? backtest.best_model : null,
          window: Array.isArray(backtest.holdout_window) ? backtest.holdout_window : null,
          logLoss: numOrNull(backtest.holdout_log_loss),
          accuracy: numOrNull(backtest.holdout_accuracy),
          baselines: Object.entries(obj(backtest.baselines))
            .filter(([, v]) => isNum(v))
            .map(([key, v]) => ({ key, logLoss: v })),
        }
      : null,
  };
}

export const BASELINE_LABELS = {
  bookmaker: 'Bookmaker odds',
  class_prior: 'Class prior (always predict base rates)',
  uniform: 'Uniform (1/3 each)',
  elo: 'Elo rating',
};

export function baselineLabel(key) {
  return BASELINE_LABELS[key] ?? key.replace(/_/g, ' ');
}

const RESULT_LABELS = { H: 'Home win', D: 'Draw', A: 'Away win' };
export const resultLabel = (r) => RESULT_LABELS[r] ?? DASH;

/** Highest-probability outcome code ('H' | 'D' | 'A') or null. */
export function predictedCode(row) {
  const p = { H: row.home_win, D: row.draw, A: row.away_win };
  if (!Object.values(p).every(isNum)) return null;
  return Object.entries(p).sort((a, b) => b[1] - a[1])[0][0];
}

/** Round to a "nice" step for axis ticks: returns {min, max, ticks}. */
export function niceAxis(lo, hi, target = 5) {
  if (!isNum(lo) || !isNum(hi)) return { min: 0, max: 1, ticks: [0, 1] };
  let min = lo;
  let max = hi;
  if (max - min < 0.02) {
    const mid = (max + min) / 2;
    min = mid - 0.02;
    max = mid + 0.02;
  }
  const rough = (max - min) / target;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const frac = rough / pow;
  const step = (frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10) * pow;
  const niceMin = Math.floor(min / step) * step;
  const niceMax = Math.ceil(max / step) * step;
  const ticks = [];
  for (let t = niceMin; t <= niceMax + step / 2; t += step) ticks.push(Number(t.toFixed(10)));
  return { min: niceMin, max: niceMax, ticks };
}
