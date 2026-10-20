import { useMemo } from 'react';
import { useNews } from '../../hooks/useNews';
import { filterNewsForTeams, publicationAge } from '../../lib/news.js';
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

  let body;
  if (!data && loading) {
    body = <Skeleton lines={3} />;
  } else if (!data && error) {
    body = <p className="tp-muted">Headlines are unavailable right now.</p>;
  } else if (!articles.length) {
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
      {data?.stale ? <p className="team-note">The headline cache is out of date.</p> : null}
      <p className="team-note">
        Matched by team name in headlines. <a href={ROUTES.news}>All football news</a>
      </p>
    </Card>
  );
}

export default TeamNews;
