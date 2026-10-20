import { DASH, formatRecord } from '../../lib/teams.js';
import { fmtGoalDiff, fmtSeason, isCurrentSeason, seasonSplitRows, seasonTableCaption } from '../../lib/teamPage.js';
import { leagueInfo } from '../../lib/matches.js';
import { Card } from './common';

const val = (v) => (Number.isInteger(v) ? v : DASH);

/** Domestic league season: totals plus a home / away split. */
function SeasonCard({ season, league }) {
  if (!season || typeof season !== 'object') {
    return (
      <Card title="Domestic league season">
        <p className="tp-muted">
          No domestic league season on record — this team only appears in Champions League history.
        </p>
      </Card>
    );
  }
  const rows = seasonSplitRows(season);
  const leagueName = league ? leagueInfo(league).name : 'League';
  const current = isCurrentSeason(season.season);

  return (
    <Card title={`${leagueName} ${fmtSeason(season.season)}`}>
      <dl className="season-tiles">
        <div className="season-tile">
          <dt>Played</dt>
          <dd>{val(season.played)}</dd>
        </div>
        <div className="season-tile">
          <dt>Record</dt>
          <dd>{formatRecord(season)}</dd>
        </div>
        <div className="season-tile">
          <dt>Goals</dt>
          <dd>
            {Number.isInteger(season.gf) && Number.isInteger(season.ga) ? `${season.gf}–${season.ga}` : DASH}
            <span className="season-sub"> ({fmtGoalDiff(season.gf, season.ga)})</span>
          </dd>
        </div>
        <div className="season-tile">
          <dt>Points</dt>
          <dd>{val(season.pts)}</dd>
        </div>
      </dl>

      {rows.length ? (
        <div className="table-scroll" role="region" aria-label="Home and away split" tabIndex={0}>
          <table className="data-table season-table">
            <caption className="sr-only">{seasonTableCaption(season.season)}</caption>
            <thead>
              <tr>
                <th scope="col">Venue</th>
                <th scope="col" className="num"><abbr title="Played">P</abbr></th>
                <th scope="col" className="num"><abbr title="Won">W</abbr></th>
                <th scope="col" className="num"><abbr title="Drawn">D</abbr></th>
                <th scope="col" className="num"><abbr title="Lost">L</abbr></th>
                <th scope="col" className="num"><abbr title="Goals for">GF</abbr></th>
                <th scope="col" className="num"><abbr title="Goals against">GA</abbr></th>
                <th scope="col" className="num"><abbr title="Points">Pts</abbr></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className={r.key === 'total' ? 'row-total' : undefined}>
                  <th scope="row">{r.label}</th>
                  <td className="num">{val(r.played)}</td>
                  <td className="num">{val(r.w)}</td>
                  <td className="num">{val(r.d)}</td>
                  <td className="num">{val(r.l)}</td>
                  <td className="num">{val(r.gf)}</td>
                  <td className="num">{val(r.ga)}</td>
                  <td className="num">{val(r.pts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {Number.isInteger(season.season) && !current ? (
        <p className="team-note">
          Their most recent {league ? leagueName : 'domestic league'} season on record, not the current season.
        </p>
      ) : null}
      <p className="team-note">Domestic league matches only; cup and European games are excluded.</p>
    </Card>
  );
}

export default SeasonCard;
