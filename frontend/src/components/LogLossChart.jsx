import { useMemo } from 'react';
import LineChart from './charts/LineChart';
import { fmtLogLoss, fmtShortDate, isNum } from '../lib/trackRecord';

function LegendSwatch() {
  return (
    <svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true" focusable="false">
      <line x1="1" y1="6" x2="33" y2="6" className="series-line model" />
      <circle cx="17" cy="6" r="4" className="series-point model" />
    </svg>
  );
}

const LEGEND = (
  <ul className="chart-legend" aria-label="Legend">
    <li><LegendSwatch /> Model</li>
  </ul>
);

const COLUMNS = [
  { key: 'week', label: 'Week starting' },
  { key: 'n', label: 'Matches', num: true },
  { key: 'logLoss', label: 'Model log-loss', num: true },
];

/**
 * Per-week log-loss for the model, drawn with the shared LineChart. Lower is
 * better, which the axis title says explicitly.
 */
function LogLossChart({ timeline }) {
  const points = useMemo(
    () =>
      timeline.map((t) => ({
        key: t.weekStart,
        xLabel: fmtShortDate(t.weekStart),
        y: isNum(t.logLoss) ? t.logLoss : null,
        tooltip: `Model, week of ${fmtShortDate(t.weekStart)}: log-loss ${fmtLogLoss(t.logLoss)} (${t.n} matches)`,
      })),
    [timeline],
  );

  const table = useMemo(
    () => ({
      caption: 'Weekly model log-loss',
      columns: COLUMNS,
      rows: timeline.map((t) => ({
        key: t.weekStart,
        cells: [fmtShortDate(t.weekStart), t.n, fmtLogLoss(t.logLoss)],
      })),
    }),
    [timeline],
  );

  if (!timeline.length) {
    return <p className="explain-note">No weekly log-loss values to chart yet.</p>;
  }

  const first = timeline[0].weekStart;
  const last = timeline[timeline.length - 1].weekStart;
  const desc =
    `Line chart of the model’s weekly log-loss from ${fmtShortDate(first)} to ${fmtShortDate(last)}. ` +
    'Lower values are better. ' +
    'The same figures are available in the table below the chart.';

  return (
    <LineChart
      title="Weekly model log-loss"
      desc={desc}
      points={points}
      seriesClass="model"
      yFormat={(t) => t.toFixed(2)}
      yAxisTitle="Log-loss (lower is better)"
      xAxisTitle="Week starting"
      minSpan={0.02}
      legend={LEGEND}
      table={table}
      emptyMessage="No weekly log-loss values to chart yet."
    />
  );
}

export default LogLossChart;
