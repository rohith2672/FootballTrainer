import { useEffect, useMemo, useRef, useState } from 'react';
import { fmtLogLoss, fmtShortDate, isNum, niceAxis } from '../lib/trackRecord';

const HEIGHT = 300;
const MARGIN = { top: 16, right: 18, bottom: 56, left: 58 };
const DEFAULT_WIDTH = 640;
const MIN_WIDTH = 280;

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

/** Consecutive runs of non-null points, so gaps in the data break the line. */
function segments(points) {
  const out = [];
  let run = [];
  for (const p of points) {
    if (p.y === null) {
      if (run.length) out.push(run);
      run = [];
    } else run.push(p);
  }
  if (run.length) out.push(run);
  return out;
}

const pathOf = (run) => run.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

function LegendSwatch({ kind }) {
  return (
    <svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true" focusable="false">
      <line x1="1" y1="6" x2="33" y2="6" className={`series-line ${kind}`} />
      {kind === 'model' ? (
        <circle cx="17" cy="6" r="4" className={`series-point ${kind}`} />
      ) : (
        <rect x="13" y="2" width="8" height="8" className={`series-point ${kind}`} />
      )}
    </svg>
  );
}

/**
 * Per-week log-loss for the model and the bookmaker. Hand-drawn SVG, no chart
 * library. Lower is better, which the axis title says explicitly.
 */
function LogLossChart({ timeline }) {
  const [wrapRef, width] = useElementWidth();

  const geometry = useMemo(() => {
    const values = timeline.flatMap((t) => [t.logLoss, t.bookmakerLogLoss]).filter(isNum);
    if (values.length === 0) return null;
    const axis = niceAxis(Math.min(...values), Math.max(...values));
    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;
    const x = (i) =>
      MARGIN.left + (timeline.length === 1 ? innerW / 2 : (i / (timeline.length - 1)) * innerW);
    const y = (v) => MARGIN.top + innerH - ((v - axis.min) / (axis.max - axis.min)) * innerH;
    const toPoints = (field) =>
      timeline.map((t, i) => ({
        x: x(i),
        y: isNum(t[field]) ? y(t[field]) : null,
        value: t[field],
        week: t,
      }));
    const maxLabels = Math.max(2, Math.floor(innerW / 70));
    const step = Math.ceil(timeline.length / maxLabels);
    return {
      axis,
      y,
      x,
      innerH,
      innerW,
      model: toPoints('logLoss'),
      book: toPoints('bookmakerLogLoss'),
      labelStep: step,
    };
  }, [timeline, width]);

  if (!geometry) {
    return <p className="explain-note">No weekly log-loss values to chart yet.</p>;
  }

  const { axis, y, x, innerH, innerW, model, book, labelStep } = geometry;
  const bottomY = MARGIN.top + innerH;
  const first = timeline[0].weekStart;
  const last = timeline[timeline.length - 1].weekStart;
  const desc =
    `Line chart of weekly log-loss from ${fmtShortDate(first)} to ${fmtShortDate(last)}, ` +
    'comparing the model with bookmaker odds. Lower values are better. ' +
    'The same figures are available in the table below the chart.';

  const tip = (p, name) =>
    `${name}, week of ${fmtShortDate(p.week.weekStart)}: log-loss ${fmtLogLoss(p.value)} (${p.week.n} matches)`;

  return (
    <div className="chart-card">
      <ul className="chart-legend" aria-label="Legend">
        <li><LegendSwatch kind="model" /> Model</li>
        <li><LegendSwatch kind="book" /> Bookmaker odds</li>
      </ul>

      <div className="chart-wrap" ref={wrapRef}>
        <svg
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          role="img"
          aria-labelledby="chart-title chart-desc"
          className="chart-svg"
        >
          <title id="chart-title">Weekly log-loss: model vs bookmaker</title>
          <desc id="chart-desc">{desc}</desc>

          {/* Gridlines and y axis */}
          {axis.ticks.map((t) => (
            <g key={t}>
              <line x1={MARGIN.left} x2={MARGIN.left + innerW} y1={y(t)} y2={y(t)} className="chart-grid" />
              <text x={MARGIN.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="chart-tick">
                {t.toFixed(2)}
              </text>
            </g>
          ))}
          <text
            transform={`translate(14 ${MARGIN.top + innerH / 2}) rotate(-90)`}
            textAnchor="middle"
            className="chart-axis-title"
          >
            Log-loss (lower is better)
          </text>

          {/* X axis */}
          <line x1={MARGIN.left} x2={MARGIN.left + innerW} y1={bottomY} y2={bottomY} className="chart-axis" />
          {timeline.map((t, i) =>
            i % labelStep === 0 ? (
              <g key={t.weekStart}>
                <line x1={x(i)} x2={x(i)} y1={bottomY} y2={bottomY + 5} className="chart-axis" />
                <text x={x(i)} y={bottomY + 20} textAnchor="middle" className="chart-tick">
                  {fmtShortDate(t.weekStart)}
                </text>
              </g>
            ) : null,
          )}
          <text
            x={MARGIN.left + innerW / 2}
            y={HEIGHT - 8}
            textAnchor="middle"
            className="chart-axis-title"
          >
            Week starting
          </text>

          {/* Series: bookmaker first so the model line sits on top. */}
          {segments(book).map((run) => (
            <path key={`b${run[0].week.weekStart}`} d={pathOf(run)} className="series-line book" />
          ))}
          {segments(model).map((run) => (
            <path key={`m${run[0].week.weekStart}`} d={pathOf(run)} className="series-line model" />
          ))}

          {book.map((p) =>
            p.y === null ? null : (
              <g key={`bp${p.week.weekStart}`}>
                <title>{tip(p, 'Bookmaker odds')}</title>
                <rect x={p.x - 4} y={p.y - 4} width="8" height="8" className="series-point book" />
                <circle cx={p.x} cy={p.y} r="12" className="chart-hit" />
              </g>
            ),
          )}
          {model.map((p) =>
            p.y === null ? null : (
              <g key={`mp${p.week.weekStart}`}>
                <title>{tip(p, 'Model')}</title>
                <circle cx={p.x} cy={p.y} r="4.5" className="series-point model" />
                <circle cx={p.x} cy={p.y} r="12" className="chart-hit" />
              </g>
            ),
          )}
        </svg>
      </div>

      <details className="chart-data">
        <summary>Show chart data as a table</summary>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="sr-only">Weekly log-loss, model vs bookmaker</caption>
            <thead>
              <tr>
                <th scope="col">Week starting</th>
                <th scope="col" className="num">Matches</th>
                <th scope="col" className="num">Model log-loss</th>
                <th scope="col" className="num">Bookmaker log-loss</th>
              </tr>
            </thead>
            <tbody>
              {timeline.map((t) => (
                <tr key={t.weekStart}>
                  <th scope="row">{fmtShortDate(t.weekStart)}</th>
                  <td className="num">{t.n}</td>
                  <td className="num">{fmtLogLoss(t.logLoss)}</td>
                  <td className="num">{fmtLogLoss(t.bookmakerLogLoss)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

export default LogLossChart;
