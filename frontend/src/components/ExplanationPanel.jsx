import { useId, useState } from 'react';
import { outcomeLabel } from '../lib/matches';
import {
  DETAIL_ROWS,
  fmtContribution,
  fmtRawValue,
  formBasis,
  h2hSummary,
} from '../lib/explain';

function Factors({ match, factors }) {
  const max = Math.max(...factors.map((f) => Math.abs(f.contribution)), 1e-9);
  return (
    <section className="explain-block" aria-label="Top factors">
      <h5 className="explain-heading">Top factors</h5>
      <p className="explain-note">
        Bars to the right push toward <strong>{outcomeLabel(match)}</strong>; bars to the left push
        against it.
      </p>
      <ul className="factor-list">
        {factors.map((f) => {
          const width = (Math.abs(f.contribution) / max) * 50;
          const direction = f.contribution >= 0 ? 'pos' : 'neg';
          return (
            <li className="factor" key={f.key}>
              <div className="factor-head">
                <span className="factor-label">{f.label}</span>
                <span className="factor-value" title="Raw feature value">
                  {fmtRawValue(f.value)}
                </span>
              </div>
              <div className="factor-row">
                <div className="factor-bar" aria-hidden="true">
                  <span className={`factor-fill ${direction}`} style={{ width: `${width}%` }} />
                </div>
                <span className="factor-contrib">
                  {fmtContribution(f.contribution)}
                  <span className="sr-only">
                    {f.contribution >= 0 ? ' toward the predicted outcome' : ' against the predicted outcome'}
                  </span>
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Comparison({ match, details }) {
  const summary = h2hSummary(details.h2h, match.home_team);
  const basis = formBasis(details);
  return (
    <section className="explain-block" aria-label="Team comparison">
      <h5 className="explain-heading">Team comparison</h5>
      <div className="table-scroll">
        <table className="compare-table">
          <thead>
            <tr>
              <th scope="col" className="compare-home">{match.home_team}</th>
              <th scope="col"><span className="sr-only">Measure</span></th>
              <th scope="col" className="compare-away">{match.away_team}</th>
            </tr>
          </thead>
          <tbody>
            {DETAIL_ROWS.map(({ key, label, format }) => (
              <tr key={key}>
                <td className="compare-home">{format(details.home[key])}</td>
                <th scope="row" className="compare-label">{label}</th>
                <td className="compare-away">{format(details.away[key])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {summary ? <p className="explain-note">{summary}</p> : null}
      {basis ? <p className="explain-note">{basis}</p> : null}
    </section>
  );
}

/**
 * Collapsed-by-default disclosure. The caller decides whether to render it
 * (see explanationContent) so a card without explanation data stays plain.
 */
function ExplanationPanel({ match, factors, details }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const label = factors.length > 0 ? 'Why this prediction?' : 'Team comparison';

  return (
    <div className="explain">
      <button
        type="button"
        className="explain-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
      >
        <span>{label}</span>
        <span className="explain-chevron" aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      <div id={panelId} className="explain-body" hidden={!open}>
        {factors.length > 0 ? <Factors match={match} factors={factors} /> : null}
        {details ? <Comparison match={match} details={details} /> : null}
      </div>
    </div>
  );
}

export default ExplanationPanel;
