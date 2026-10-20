import { useMemo } from 'react';
import { useNews } from '../../hooks/useNews';
import { filterNewsForTeams, publicationAge, teamNewsState } from '../../lib/news.js';
import { ROUTES } from '../../lib/routes.js';
import { Card, Skeleton } from './common';

const MAX_HEADLINES = 5;

/** Up to five cached headlines that mention the team. */
function TeamNews({ name }) {
  const { data, loading, error } = useNews();
  const articles = useMemo(
    () => (data ? filterNewsForTeams(data.articles, [name]).slice(0, MAX_HEADLINES) : []),
    [data, name],
  );

  const state = teamNewsState({ data, loading, error, matched: articles });

  let body;
  if (state === 'loading') {
    body = <Skeleton lines={3} />;
  } else if (state === 'error') {
    body = <p className="tp-muted">Headlines are unavailable right now.</p>;
  } else if (state === 'unavailable') {
    body = (
      <p className="tp-muted">
        Headlines aren’t available yet. The news service will try again at its next scheduled check.
      </p>
    );
  } else if (state === 'no-headlines') {
    body = <p className="tp-muted">No headlines have been saved yet.</p>;
  } else if (state === 'no-match') {
    body = <p className="tp-muted">No recent headlines mention {name}.</p>;
  } else {
    body = (
      <ul className="team-news">
        {articles.map((a) => (
          <li key={a.id} className="team-news-item">
            <a href={a.url} target="_blank" rel="noopener noreferrer">
              {a.title}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
            <span className="team-news-meta">
              {a.publisher} · {publicationAge(a.published_at)}
            </span>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <Card title={`News mentioning ${name}`}>
      {body}
      {data?.stale && (state === 'list' || state === 'no-match') ? <p className="team-note">The headline cache is out of date.</p> : null}
      <p className="team-note">
        Matched by team name in headlines. <a href={ROUTES.news}>All football news</a>
      </p>
    </Card>
  );
}

export default TeamNews;
