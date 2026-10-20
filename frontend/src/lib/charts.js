// Pure geometry helpers for the hand-drawn SVG line chart (no chart library).
// Kept free of React and of extension-less imports so Node tests can load it.

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

/**
 * "Nice" axis bounds and ticks covering [lo, hi]: {min, max, ticks}.
 * A range narrower than `minSpan` is widened to mid ± minSpan so a flat
 * series still gets a readable axis (0.02 matches the log-loss chart).
 */
export function niceAxis(lo, hi, { target = 5, minSpan = 0.02 } = {}) {
  if (!isNum(lo) || !isNum(hi)) return { min: 0, max: 1, ticks: [0, 1] };
  let min = Math.min(lo, hi);
  let max = Math.max(lo, hi);
  if (max - min < minSpan) {
    const mid = (max + min) / 2;
    min = mid - minSpan;
    max = mid + minSpan;
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

/** Linear map from [d0, d1] to [r0, r1]; a zero-width domain maps to the range midpoint. */
export function linearScale(d0, d1, r0, r1) {
  const span = d1 - d0;
  if (!span) return () => (r0 + r1) / 2;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** x position of the i-th of n evenly spaced points; a single point is centred. */
export function indexX(i, n, left, innerW) {
  if (n <= 1) return left + innerW / 2;
  return left + (i / (n - 1)) * innerW;
}

/** Show every `step`-th x label so labels stay at least `minGap` px apart. */
export function labelStep(n, innerW, minGap = 70) {
  if (n <= 0) return 1;
  const maxLabels = Math.max(2, Math.floor(innerW / minGap));
  return Math.max(1, Math.ceil(n / maxLabels));
}

/**
 * Lay out a single-series chart.
 * `values`: array of numbers or null (null breaks the line). Returns
 * null when there is nothing to plot, else
 * {axis, innerW, innerH, bottom, xs, ys, labelStep, y} where xs/ys line up with
 * `values` (ys[i] is null for missing values) and y() maps a value to px.
 */
export function lineGeometry(values, { width, height, margin, minSpan = 0.02, minLabelGap = 70 }) {
  const list = Array.isArray(values) ? values : [];
  const present = list.filter(isNum);
  if (!present.length) return null;
  const axis = niceAxis(Math.min(...present), Math.max(...present), { minSpan });
  const innerW = Math.max(1, width - margin.left - margin.right);
  const innerH = Math.max(1, height - margin.top - margin.bottom);
  const y = linearScale(axis.min, axis.max, margin.top + innerH, margin.top);
  const xs = list.map((_, i) => indexX(i, list.length, margin.left, innerW));
  const ys = list.map((v) => (isNum(v) ? y(v) : null));
  return {
    axis,
    innerW,
    innerH,
    bottom: margin.top + innerH,
    xs,
    ys,
    y,
    labelStep: labelStep(list.length, innerW, minLabelGap),
  };
}

/** Consecutive runs of plotted points [{x, y, i}], so gaps break the line. */
export function segments(xs, ys) {
  const out = [];
  let run = [];
  for (let i = 0; i < xs.length; i += 1) {
    if (ys[i] === null || ys[i] === undefined) {
      if (run.length) out.push(run);
      run = [];
    } else run.push({ x: xs[i], y: ys[i], i });
  }
  if (run.length) out.push(run);
  return out;
}

export const pathOf = (run) =>
  run.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

/**
 * Index of the plotted point whose x is nearest to `px` (ties → earlier
 * point), skipping indexes whose y is null. -1 when nothing is plotted.
 */
export function nearestIndex(xs, ys, px) {
  let best = -1;
  let bestDist = Infinity;
  for (let i = 0; i < xs.length; i += 1) {
    if (ys && (ys[i] === null || ys[i] === undefined)) continue;
    const d = Math.abs(xs[i] - px);
    if (d < bestDist) {
      best = i;
      bestDist = d;
    }
  }
  return best;
}

/** Plotted indexes in order (for keyboard navigation). */
export function plottedIndexes(ys) {
  const out = [];
  ys.forEach((y, i) => {
    if (y !== null && y !== undefined) out.push(i);
  });
  return out;
}

/**
 * Next plotted index for a navigation key, or `current` when the key does not
 * move (or is not a navigation key). Keys: ArrowRight/ArrowUp (next),
 * ArrowLeft/ArrowDown (previous), Home, End.
 */
export function stepIndex(plotted, current, key) {
  if (!plotted.length) return current;
  const pos = plotted.indexOf(current);
  const at = pos === -1 ? 0 : pos;
  switch (key) {
    case 'ArrowRight':
    case 'ArrowUp':
      return plotted[Math.min(plotted.length - 1, at + 1)];
    case 'ArrowLeft':
    case 'ArrowDown':
      return plotted[Math.max(0, at - 1)];
    case 'Home':
      return plotted[0];
    case 'End':
      return plotted[plotted.length - 1];
    default:
      return current;
  }
}

/**
 * Position a tooltip of width `tipW` (and estimated height `tipH`) for the
 * point (x, y) inside a box `width` px wide. It is centred on x and clamped
 * horizontally so it never leaves the box. It sits above the point (its
 * bottom edge at `anchorY`) unless that would cross the top edge, in which
 * case it flips below (its top edge at `anchorY`).
 * Returns {left, anchorY, placement: 'above' | 'below'}.
 */
export function placeTooltip({ x, y, tipW, tipH, width, gap = 12, pad = 4 }) {
  const maxLeft = Math.max(pad, width - tipW - pad);
  const left = Math.min(Math.max(x - tipW / 2, pad), maxLeft);
  if (y - gap - tipH >= pad) return { left, anchorY: y - gap, placement: 'above' };
  return { left, anchorY: y + gap, placement: 'below' };
}
