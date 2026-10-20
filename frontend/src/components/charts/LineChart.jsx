import { useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  lineGeometry,
  nearestIndex,
  pathOf,
  placeTooltip,
  plottedIndexes,
  segments,
  stepIndex,
} from '../../lib/charts.js';
import '../../styles/charts.css';

const DEFAULT_MARGIN = { top: 16, right: 18, bottom: 56, left: 58 };
const DEFAULT_WIDTH = 640;
const MIN_WIDTH = 260;
const TIP_W = 220;
const TIP_H = 56; // estimate, only used to decide whether the tooltip fits above
const NAV_KEYS = ['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown', 'Home', 'End'];

/** Width of an element, kept current with ResizeObserver. */
function useElementWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.max(MIN_WIDTH, Math.floor(entry.contentRect.width)));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

/** W / D / L (or default) marker. Shapes differ so results never rely on colour alone. */
export function Marker({ shape, x, y, r, className }) {
  if (shape === 'W') {
    // Triangle pointing up.
    const h = r * 1.15;
    return (
      <path
        d={`M${x},${y - h} L${x + h},${y + h * 0.8} L${x - h},${y + h * 0.8} Z`}
        className={className}
      />
    );
  }
  if (shape === 'L') {
    const h = r * 1.15;
    return (
      <path
        d={`M${x},${y + h} L${x + h},${y - h * 0.8} L${x - h},${y - h * 0.8} Z`}
        className={className}
      />
    );
  }
  if (shape === 'D') {
    const s = r * 0.9;
    return <rect x={x - s} y={y - s} width={s * 2} height={s * 2} className={className} />;
  }
  return <circle cx={x} cy={y} r={r} className={className} />;
}

/**
 * Single-series line chart drawn in SVG.
 *
 * Props:
 * - `title`, `desc`: accessible name and description (also the SVG <title>/<desc>).
 * - `points`: [{key, xLabel, y (number|null), tooltip, marker?: 'W'|'D'|'L', className?}].
 *   Points are evenly spaced; null y breaks the line.
 * - `seriesClass`: class for the line and default markers (e.g. "model").
 * - `yFormat(tick)`, `yAxisTitle`, `xAxisTitle`, `minSpan` (smallest y range), `height`.
 * - `legend`: optional node rendered above the chart.
 * - `table`: {caption, columns: [{key, label, num?}], rows: [{key, cells: [...]}]} —
 *   the data-table fallback inside a <details>; the first cell is the row header.
 * - `emptyMessage`: shown instead of the chart when nothing can be plotted.
 *
 * Interaction: hover or tap anywhere on the plot to inspect the nearest point
 * (crosshair + tooltip). Keyboard: the points form one tab stop; arrow keys,
 * Home and End move between them.
 */
function LineChart({
  title,
  desc,
  points,
  seriesClass = 'model',
  yFormat = (t) => String(t),
  yAxisTitle,
  xAxisTitle,
  minSpan = 0.02,
  height = 300,
  margin = DEFAULT_MARGIN,
  markerRadius,
  legend = null,
  table = null,
  emptyMessage = 'No data to chart yet.',
  className = '',
}) {
  const [wrapRef, width] = useElementWidth();
  const svgRef = useRef(null);
  const pointRefs = useRef(new Map());
  const uid = useId();
  const titleId = `${uid}-title`;
  const descId = `${uid}-desc`;

  // active: the inspected point (hover/tap/focus); focusIndex: the roving tab stop.
  const [active, setActive] = useState(null);
  const [focusIndex, setFocusIndex] = useState(null);

  const geometry = useMemo(
    () =>
      lineGeometry(
        points.map((p) => p.y),
        { width, height, margin, minSpan },
      ),
    [points, width, height, margin, minSpan],
  );
  const plotted = useMemo(() => (geometry ? plottedIndexes(geometry.ys) : []), [geometry]);

  if (!geometry) {
    return <p className="explain-note">{emptyMessage}</p>;
  }

  const { axis, innerW, innerH, bottom, xs, ys, y, labelStep } = geometry;
  // Clamp state that may refer to points from an earlier dataset.
  const activeIndex = active && plotted.includes(active.index) ? active.index : null;
  const tabStop = plotted.includes(focusIndex) ? focusIndex : plotted[plotted.length - 1];
  // Thin markers when points are dense (e.g. a full season on a phone).
  const spacing = points.length > 1 ? innerW / (points.length - 1) : innerW;
  const r = markerRadius ?? (spacing < 8 ? 2.6 : spacing < 14 ? 3.4 : 4.5);

  const inspectAt = (clientX, source) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const scale = rect.width ? width / rect.width : 1;
    const i = nearestIndex(xs, ys, (clientX - rect.left) * scale);
    if (i >= 0) setActive({ index: i, source });
  };

  const onPointerMove = (e) => inspectAt(e.clientX, e.pointerType || 'mouse');
  const onPointerDown = (e) => inspectAt(e.clientX, e.pointerType || 'mouse');
  const onPointerLeave = (e) => {
    // A tap fires pointerleave right away; keep touch/pen tooltips until the next tap.
    if (e.pointerType === 'mouse' && active?.source === 'mouse') setActive(null);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      setActive(null);
      return;
    }
    if (!NAV_KEYS.includes(e.key)) return;
    e.preventDefault();
    const next = stepIndex(plotted, activeIndex ?? tabStop, e.key);
    setFocusIndex(next);
    setActive({ index: next, source: 'focus' });
    pointRefs.current.get(next)?.focus();
  };

  const activePoint = activeIndex === null ? null : points[activeIndex];
  const tipW = Math.min(TIP_W, width - 8);
  const tip =
    activeIndex === null
      ? null
      : placeTooltip({ x: xs[activeIndex], y: ys[activeIndex], tipW, tipH: TIP_H, width });

  return (
    <div className={`chart-card lc ${className}`.trim()}>
      {legend}

      <div className="chart-wrap lc-wrap" ref={wrapRef}>
        <svg
          ref={svgRef}
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="group"
          aria-labelledby={`${titleId} ${descId}`}
          className="chart-svg lc-svg"
          onPointerMove={onPointerMove}
          onPointerDown={onPointerDown}
          onPointerLeave={onPointerLeave}
        >
          <title id={titleId}>{title}</title>
          <desc id={descId}>{desc}</desc>

          {/* Gridlines and y axis */}
          <g aria-hidden="true">
            {axis.ticks.map((t) => (
              <g key={t}>
                <line x1={margin.left} x2={margin.left + innerW} y1={y(t)} y2={y(t)} className="chart-grid" />
                <text x={margin.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="chart-tick">
                  {yFormat(t)}
                </text>
              </g>
            ))}
            {yAxisTitle ? (
              <text
                transform={`translate(14 ${margin.top + innerH / 2}) rotate(-90)`}
                textAnchor="middle"
                className="chart-axis-title"
              >
                {yAxisTitle}
              </text>
            ) : null}

            {/* X axis */}
            <line x1={margin.left} x2={margin.left + innerW} y1={bottom} y2={bottom} className="chart-axis" />
            {points.map((p, i) =>
              i % labelStep === 0 ? (
                <g key={`x${p.key}`}>
                  <line x1={xs[i]} x2={xs[i]} y1={bottom} y2={bottom + 5} className="chart-axis" />
                  <text x={xs[i]} y={bottom + 20} textAnchor="middle" className="chart-tick">
                    {p.xLabel}
                  </text>
                </g>
              ) : null,
            )}
            {xAxisTitle ? (
              <text x={margin.left + innerW / 2} y={height - 8} textAnchor="middle" className="chart-axis-title">
                {xAxisTitle}
              </text>
            ) : null}

            {/* Crosshair */}
            {activeIndex !== null ? (
              <line
                x1={xs[activeIndex]}
                x2={xs[activeIndex]}
                y1={margin.top}
                y2={bottom}
                className="lc-crosshair"
              />
            ) : null}

            {/* Series line */}
            {segments(xs, ys).map((run) => (
              <path key={`s${points[run[0].i].key}`} d={pathOf(run)} className={`series-line ${seriesClass}`} />
            ))}
          </g>

          {/* Points: one tab stop, arrow keys move between them. */}
          <g className="lc-points">
            {plotted.map((i) => {
              const p = points[i];
              const isActive = i === activeIndex;
              return (
                <g
                  key={`p${p.key}`}
                  ref={(el) => {
                    if (el) pointRefs.current.set(i, el);
                    else pointRefs.current.delete(i);
                  }}
                  role="img"
                  aria-label={p.tooltip}
                  tabIndex={i === tabStop ? 0 : -1}
                  className={`lc-point ${isActive ? 'active' : ''}`}
                  onFocus={() => {
                    setFocusIndex(i);
                    setActive({ index: i, source: 'focus' });
                  }}
                  onBlur={() => setActive((a) => (a?.source === 'focus' && a.index === i ? null : a))}
                  onKeyDown={onKeyDown}
                >
                  {isActive ? <circle cx={xs[i]} cy={ys[i]} r={r + 5} className="lc-focus-ring" /> : null}
                  <Marker
                    shape={p.marker}
                    x={xs[i]}
                    y={ys[i]}
                    r={isActive ? r + 1.5 : r}
                    className={p.className ?? `series-point ${seriesClass}`}
                  />
                </g>
              );
            })}
          </g>
        </svg>

        {activePoint && tip ? (
          <div
            className={`lc-tooltip ${tip.placement}`}
            style={{ left: tip.left, top: tip.anchorY, width: tipW }}
            aria-hidden="true"
          >
            {activePoint.tooltip}
          </div>
        ) : null}
      </div>
      {/* Touch inspection is announced; focus already reads each point's label. */}
      <p className="sr-only" aria-live="polite">
        {activePoint && active?.source !== 'focus' && active?.source !== 'mouse' ? activePoint.tooltip : ''}
      </p>

      {table ? (
        <details className="chart-data">
          <summary>Show chart data as a table</summary>
          <div className="table-scroll">
            <table className="data-table">
              <caption className="sr-only">{table.caption ?? title}</caption>
              <thead>
                <tr>
                  {table.columns.map((c) => (
                    <th key={c.key} scope="col" className={c.num ? 'num' : undefined}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row) => (
                  <tr key={row.key}>
                    {row.cells.map((cell, ci) =>
                      ci === 0 ? (
                        <th key={table.columns[ci].key} scope="row">{cell}</th>
                      ) : (
                        <td key={table.columns[ci].key} className={table.columns[ci].num ? 'num' : undefined}>
                          {cell}
                        </td>
                      ),
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  );
}

export default LineChart;
