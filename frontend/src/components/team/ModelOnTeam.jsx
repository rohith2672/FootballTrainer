import { useMemo } from 'react';
import { describeTrackRecordError } from '../../api';
import { useTrackRecord } from '../../hooks/useTrackRecord';
import { ROUTES } from '../../lib/routes.js';
import { fmtLogLoss, fmtPercent, normalizeTrackRecord } from '../../lib/trackRecord';
import { plural, teamModelSummary } from '../../lib/teamPage.js';
import { Card, SectionNotice, Skeleton } from './common';

const WEEKS = 52;

/** How the model's saved pre-match predictions involving this team have scored. */
function ModelOnTeam({ name }) {
  const { data, loading, error, reload } = useTrackRecord({ weeks: WEEKS, team: name });
  const summary = useMemo(() => (data ? teamModelSummary(normalizeTrackRecord(data)) : null), [data]);
  const title = `Model on ${name}`;

  let body;
  if (!summary && error) {
    const { title: errTitle, message } = describeTrackRecordError(error);
    body = <SectionNotice title={errTitle} message={message} onRetry={reload} busy={loading} />;
  } else if (!summary) {
    body = <Skeleton lines={3} />;
  } else if (summary.empty) {
    body = (
      <div className="model-empty">
        <p>
          No settled predictions involving {name} in the last {WEEKS} weeks yet. Predictions are saved before
          kickoff and only scored once the result is in
          {summary.nPredictions > 0
            ? ` — ${plural(summary.nPredictions, 'prediction')} ${summary.nPredictions === 1 ? 'is' : 'are'} waiting for results`
            : ''}
          .
        </p>
      </div>
    );
  } else {
    body = (
      <>
        <dl className="model-tiles">
          <div className="season-tile">
            <dt>Settled</dt>
            <dd>{summary.nSettled}</dd>
          </div>
          <div className="season-tile">
            <dt>Accuracy</dt>
            <dd>{fmtPercent(summary.accuracy)}</dd>
          </div>
          <div className="season-tile">
            <dt>Log-loss</dt>
            <dd>{fmtLogLoss(summary.logLoss)}</dd>
          </div>
          <div className="season-tile">
            <dt>Uniform</dt>
            <dd>{fmtLogLoss(summary.uniform)}</dd>
          </div>
        </dl>
        {summary.verdict ? <p className="model-verdict">{summary.verdict}</p> : null}
        {summary.smallSample ? (
          <p className="team-note">
            Small sample: with fewer than 20 settled matches these figures can swing a lot.
          </p>
        ) : null}
      </>
    );
  }

  return (
    <Card title={title} busy={loading && !!summary}>
      {body}
      <p className="team-note">
        Live predictions from the last {WEEKS} weeks only. <a href={ROUTES.trackRecord}>Full track record</a>
      </p>
    </Card>
  );
}

export default ModelOnTeam;
