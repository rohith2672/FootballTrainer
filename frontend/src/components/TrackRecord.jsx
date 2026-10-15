import { useMemo, useState } from 'react';
import LogLossChart from './LogLossChart';
import { useTrackRecord } from '../hooks/useTrackRecord';
import { describeTrackRecordError } from '../api';
import { ALL_LEAGUES, LEAGUES, leagueInfo } from '../lib/matches';
import { DASH } from '../lib/explain';
import {
  DEFAULT_WEEKS,
  WEEK_OPTIONS,
  baselineLabel,
  fmtGap,
  fmtLogLoss,
  fmtLongDate,
  fmtPct0,
  fmtPercent,
  gapOf,
  normalizeTrackRecord,
  predictedCode,
  resultLabel,
} from '../lib/trackRecord';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function Tile({ label, value, note, wide = false }) {
  return (
    <div className={`metric-tile ${wide ? 'wide' : ''}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {note ? <div className="metric-note">{note}</div> : null}
    </div>
  );
}

function Headline({ record }) {
  const { overall, baselines, nSettled, nPredictions, modelVersion } = record;
  const gap = gapOf(overall.logLoss, baselines.bookmaker.logLoss);
  return (
    <section className="tr-section" aria-labelledby="tr-headline">
      <h2 id="tr-headline" className="tr-heading">Live performance</h2>
      <p className="tr-intro">
        Scored only on predictions stored before kickoff and settled after the result.{' '}
        <strong>Log-loss: lower is better.</strong>
      </p>
      <div className="metric-grid">
        <Tile label="Model log-loss" value={fmtLogLoss(overall.logLoss)} note="Lower is better" />
        <Tile
          label="Bookmaker log-loss"
          value={fmtLogLoss(baselines.bookmaker.logLoss)}
          note={
            baselines.bookmaker.n != null
              ? `${plural(baselines.bookmaker.n, 'match')} with odds · lower is better`
              : 'Lower is better'
          }
        />
        <Tile
          label="Class-prior log-loss"
          value={fmtLogLoss(baselines.classPrior.logLoss)}
          note="Always predicting base rates · lower is better"
        />
        <Tile label="Accuracy" value={fmtPercent(overall.accuracy)} note="Share of results called correctly" />
        <Tile
          label="Settled predictions"
          value={nSettled}
          note={`of ${nPredictions} recorded`}
        />
        <Tile label="Model version" value={modelVersion ?? DASH} wide />
      </div>
      <p className="tr-note">
        Gap to bookmaker (model − bookmaker): <strong>{fmtGap(gap)}</strong>
        {gap === null ? '' : ' — negative means the model’s log-loss is lower than the bookmaker’s.'}
      </p>
    </section>
  );
}

function LeagueTable({ rows }) {
  if (rows.length === 0) return null;
  return (
    <section className="tr-section" aria-labelledby="tr-leagues">
      <h2 id="tr-leagues" className="tr-heading">By league</h2>
      <div className="table-scroll" role="region" aria-label="Per-league results" tabIndex={0}>
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">League</th>
              <th scope="col" className="num">Settled</th>
              <th scope="col" className="num">Accuracy</th>
              <th scope="col" className="num">Model log-loss</th>
              <th scope="col" className="num">Bookmaker log-loss</th>
              <th scope="col" className="num" title="Model minus bookmaker; negative means the model is lower">
                Gap
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.league}>
                <th scope="row">{leagueInfo(r.league).name}</th>
                <td className="num">{r.n}</td>
                <td className="num">{fmtPercent(r.accuracy)}</td>
                <td className="num">{fmtLogLoss(r.logLoss)}</td>
                <td className="num">{fmtLogLoss(r.bookmakerLogLoss)}</td>
                <td className="num">{fmtGap(gapOf(r.logLoss, r.bookmakerLogLoss))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tr-note">Gap = model log-loss − bookmaker log-loss. Negative: the model was lower (better).</p>
    </section>
  );
}

function Recent({ rows }) {
  if (rows.length === 0) return null;
  return (
    <section className="tr-section" aria-labelledby="tr-recent">
      <h2 id="tr-recent" className="tr-heading">Recent settled predictions</h2>
      <ul className="recent-list">
        {rows.map((r, i) => {
          const code = predictedCode(r);
          const probs = [
            { code: 'H', label: 'Home', value: r.home_win },
            { code: 'D', label: 'Draw', value: r.draw },
            { code: 'A', label: 'Away', value: r.away_win },
          ];
          return (
            <li className="recent-item" key={r.fixture_id ?? `${r.date}-${r.home_team}-${i}`}>
              <div className="recent-meta">
                {fmtLongDate(r.date)} · {leagueInfo(r.league).name}
              </div>
              <div className="recent-teams">
                {r.home_team} <span className="recent-vs">v</span> {r.away_team}
              </div>
              <div className="recent-probs">
                <span className="sr-only">Predicted probabilities: </span>
                {probs.map((p) => (
                  <span key={p.code} className={`recent-prob ${p.code === code ? 'top' : ''}`}>
                    {p.label} {fmtPct0(p.value)}
                  </span>
                ))}
              </div>
              <div className="recent-outcome">
                <span>
                  Result: <strong>{resultLabel(r.result)}</strong>
                  {code ? <> · predicted {resultLabel(code)}</> : null}
                </span>
                {r.correct === true || r.correct === false ? (
                  <span className={`verdict ${r.correct ? 'yes' : 'no'}`}>
                    <span aria-hidden="true">{r.correct ? '✓' : '✗'}</span>{' '}
                    {r.correct ? 'Correct' : 'Incorrect'}
                  </span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Backtest({ backtest }) {
  if (!backtest) return null;
  const modelName = backtest.bestModel ? backtest.bestModel.replace(/_/g, ' ') : 'Model';
  return (
    <section className="tr-section backtest" aria-labelledby="tr-backtest">
      <h2 id="tr-backtest" className="tr-heading">
        Backtest <span className="badge">Not live performance</span>
      </h2>
      <p className="tr-intro">
        This is how the model scored on a historical holdout it was not trained on
        {backtest.window?.length === 2
          ? `, covering ${fmtLongDate(backtest.window[0])} to ${fmtLongDate(backtest.window[1])}`
          : ''}
        . It says nothing about predictions made since. <strong>Log-loss: lower is better.</strong>
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <caption className="sr-only">Backtest log-loss by predictor</caption>
          <thead>
            <tr>
              <th scope="col">Predictor</th>
              <th scope="col" className="num">Log-loss</th>
              <th scope="col" className="num">Accuracy</th>
            </tr>
          </thead>
          <tbody>
            <tr className="row-model">
              <th scope="row">Model ({modelName})</th>
              <td className="num">{fmtLogLoss(backtest.logLoss)}</td>
              <td className="num">{fmtPercent(backtest.accuracy)}</td>
            </tr>
            {backtest.baselines.map((b) => (
              <tr key={b.key}>
                <th scope="row">{baselineLabel(b.key)}</th>
                <td className="num">{fmtLogLoss(b.logLoss)}</td>
                <td className="num">{DASH}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {backtest.source ? <p className="tr-note">Source: {backtest.source}</p> : null}
    </section>
  );
}

function TrackRecord() {
  const [league, setLeague] = useState(ALL_LEAGUES);
  const [weeks, setWeeks] = useState(DEFAULT_WEEKS);
  const { data, loading, error, reload } = useTrackRecord({
    league: league === ALL_LEAGUES ? null : league,
    weeks,
  });

  const record = useMemo(() => (data ? normalizeTrackRecord(data) : null), [data]);

  const controls = (
    <div className="tr-controls">
      <div className="league-selector" role="group" aria-label="League">
        {[ALL_LEAGUES, ...Object.keys(LEAGUES)].map((code) => {
          const isAll = code === ALL_LEAGUES;
          const info = isAll ? { name: 'All leagues', emoji: '\u{1F30D}' } : leagueInfo(code);
          return (
            <button
              type="button"
              key={code}
              className={`league-pill ${league === code ? 'active' : ''}`}
              aria-pressed={league === code}
              aria-label={info.name}
              onClick={() => setLeague(code)}
            >
              <span className="league-emoji" aria-hidden="true">{info.emoji}</span>
              <span className="league-name">{info.name}</span>
            </button>
          );
        })}
      </div>
      <div className="filters tr-filters">
        <div className="field">
          <label htmlFor="tr-weeks">Time window</label>
          <select id="tr-weeks" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            {WEEK_OPTIONS.map((w) => (
              <option key={w} value={w}>Last {w} weeks</option>
            ))}
          </select>
        </div>
        <button type="button" className="btn field-action" onClick={reload} disabled={loading} aria-busy={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>
    </div>
  );

  let body;
  if (!record && error) {
    const { title, message } = describeTrackRecordError(error);
    body = (
      <div className="error-card" role="alert">
        <div className="error-icon" aria-hidden="true">{'⚠️'}</div>
        <h2>{title}</h2>
        <p>{message}</p>
        <button type="button" className="btn btn-primary" onClick={reload}>
          Retry
        </button>
      </div>
    );
  } else if (!record) {
    body = (
      <div className="loader-container" role="status" aria-live="polite">
        <div className="spinner-ring" aria-hidden="true"></div>
        <p className="loader-text">Loading track record…</p>
      </div>
    );
  } else {
    const staleBanner = error ? (
      <div className="inline-alert" role="alert">
        <span>
          <strong>{describeTrackRecordError(error).title}.</strong> Showing the data from the last
          successful update.
        </span>
        <button type="button" className="btn" onClick={reload} disabled={loading}>
          Retry
        </button>
      </div>
    ) : null;

    const scope = league === ALL_LEAGUES ? '' : ` in ${leagueInfo(league).name}`;
    const hasLive = record.nSettled > 0;
    body = (
      <div className="tr-content" aria-busy={loading}>
        {staleBanner}
        {hasLive ? (
          <>
            <Headline record={record} />
            <section className="tr-section" aria-labelledby="tr-weekly">
              <h2 id="tr-weekly" className="tr-heading">Log-loss by week</h2>
              <LogLossChart timeline={record.timeline} />
            </section>
            <LeagueTable rows={record.byLeague} />
            <Recent rows={record.recent} />
          </>
        ) : (
          <div className="empty-state">
            <div className="empty-icon" aria-hidden="true">{'\u{1F4CA}'}</div>
            <h2>No settled live predictions yet</h2>
            <p>
              The model’s live record is built from predictions saved before kickoff and scored once
              the result is known. Nothing has been settled{scope} in this window yet
              {record.nPredictions > 0
                ? `, though ${plural(record.nPredictions, 'prediction')} ${record.nPredictions === 1 ? 'is' : 'are'} recorded and waiting for results`
                : ''}
              .
            </p>
            {record.modelVersion ? <p className="tr-note">Current model: {record.modelVersion}</p> : null}
          </div>
        )}
        <Backtest backtest={record.backtest} />
      </div>
    );
  }

  return (
    <div className="dashboard-container track-record">
      {controls}
      {body}
    </div>
  );
}

export default TrackRecord;
