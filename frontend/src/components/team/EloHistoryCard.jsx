import { useMemo } from 'react';
import LineChart, { Marker } from '../charts/LineChart';
import { describeTeamError } from '../../api';
import { formatElo, formatEloChange } from '../../lib/teams.js';
import { RESULT_LABELS, eloChartPoints, eloRange, fmtDate } from '../../lib/teamPage.js';
import { Card, ResultChip, SectionNotice, Skeleton } from './common';

const MARGIN = { top: 16, right: 16, bottom: 44, left: 52 };

const COLUMNS = [
  { key: 'date', label: 'Date' },
  { key: 'opponent', label: 'Opponent' },
  { key: 'result', label: 'Result' },
  { key: 'elo', label: 'Elo after', num: true },
];

function Legend() {
  return (
    <ul className="chart-legend" aria-label="Legend">
      {Object.entries(RESULT_LABELS).map(([code, label]) => (
        <li key={code}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <Marker shape={code} x={8} y={8} r={5} className={`lc-marker result-${code}`} />
          </svg>
          {label}
        </li>
      ))}
    </ul>
  );
}

/** Elo rating after each match over the last year, markers by result. */
function EloHistoryCard({ name, eloHistory, error, onRetry, busy }) {
  const points = useMemo(() => eloChartPoints(eloHistory?.points), [eloHistory]);
  const range = useMemo(() => eloRange(points), [points]);

  const chartPoints = useMemo(
    () =>
      points.map((p) => ({
        key: p.key,
        xLabel: p.xLabel,
        y: p.elo,
        tooltip: p.tooltip,
        marker: p.result ?? undefined,
        className: `lc-marker result-${p.result ?? 'none'}`,
      })),
    [points],
  );

  const table = useMemo(
    () => ({
      caption: `${name} Elo rating after each match`,
      columns: COLUMNS,
      rows: points.map((p) => ({
        key: p.key,
        cells: [fmtDate(p.date), p.opponent ?? '—', <ResultChip key="r" result={p.result} />, formatElo(p.elo)],
      })),
    }),
    [points, name],
  );

  let body;
  if (!eloHistory && error) {
    const { title, message } = describeTeamError(error);
    body = <SectionNotice title={title} message={message} onRetry={onRetry} busy={busy} />;
  } else if (!eloHistory) {
    body = <Skeleton lines={5} tall />;
  } else if (!points.length) {
    body = <p className="tp-muted">No finished matches in the last 12 months.</p>;
  } else {
    const desc =
      `Line chart of ${name}’s Elo rating after each match from ${fmtDate(points[0].date)} to ` +
      `${fmtDate(points[points.length - 1].date)}: ${points.length} matches, from ${formatElo(range.first)} ` +
      `to ${formatElo(range.last)} (high ${formatElo(range.high)}, low ${formatElo(range.low)}). ` +
      'Markers show the result: triangle up for a win, square for a draw, triangle down for a loss. ' +
      'The same figures are in the table below the chart.';
    body = (
      <>
        <p className="team-note elo-summary">
          <span>
            Now <strong>{formatElo(range.last)}</strong>
          </span>
          <span>
            12-month change <strong>{formatEloChange(range.change)}</strong>
          </span>
          <span>
            High <strong>{formatElo(range.high)}</strong> · Low <strong>{formatElo(range.low)}</strong>
          </span>
        </p>
        <LineChart
          title={`${name} Elo rating`}
          desc={desc}
          points={chartPoints}
          seriesClass="elo"
          yFormat={(t) => String(Math.round(t))}
          minSpan={10}
          height={260}
          margin={MARGIN}
          legend={<Legend />}
          table={table}
          className="elo-chart"
        />
        <p className="team-note">
          One point per finished match (all competitions), showing the rating after it. Hover, tap or
          use the arrow keys on the chart to inspect a match.
        </p>
      </>
    );
  }

  return (
    <Card title="Elo rating, last 12 months" wide busy={busy}>
      {eloHistory && error ? (
        <SectionNotice
          title="Couldn’t refresh the rating history"
          message="Showing the last loaded data."
          onRetry={onRetry}
          busy={busy}
        />
      ) : null}
      {body}
    </Card>
  );
}

export default EloHistoryCard;
