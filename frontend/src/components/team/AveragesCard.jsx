import { DASH } from '../../lib/teams.js';
import { averagesRows, plural } from '../../lib/teamPage.js';
import { Card } from './common';

/** Per-match averages and rates over the last 10 matches (all competitions). */
function AveragesCard({ averages }) {
  const { rows, n, shotsNote } = averagesRows(averages);
  const title = n ? `Last ${plural(n, 'match', 'matches')}` : 'Recent averages';
  if (!n) {
    return (
      <Card title={title}>
        <p className="tp-muted">No finished matches yet, so there is nothing to average.</p>
      </Card>
    );
  }
  return (
    <Card title={title}>
      <dl className="avg-grid">
        {rows.map((r) => (
          <div key={r.key} className={`avg-item ${r.shots ? 'shots' : ''}`}>
            <dt>{r.label}</dt>
            <dd>
              <span className="avg-value">{r.value}</span>
              {r.value === DASH ? (
                <span className="sr-only"> not available</span>
              ) : (
                <span className="avg-unit"> {r.unit}</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {shotsNote ? <p className="team-note">{shotsNote}</p> : null}
      <p className="team-note">All competitions. Rates are shares of these matches.</p>
    </Card>
  );
}

export default AveragesCard;
