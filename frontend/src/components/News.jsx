import { useMemo, useState } from 'react';
import { useNews } from '../hooks/useNews';
import { useFavourites } from '../hooks/useFavourites';
import { mentionedTeams, publicationAge } from '../lib/news';
import { shortTeamName, teamHref } from '../lib/teams';
import { StarIcon } from './icons';
import '../styles/favourites.css';
import '../styles/news.css';

function DateTime({ value, fallback = 'Not yet available' }) {
  return value ? <time dateTime={value}>{new Date(value).toLocaleString()}</time> : fallback;
}

/**
 * `onOpenPicker` (optional): opens the team picker from the "My teams"
 * explanation when no teams are followed. Without it the button is hidden.
 */
export default function News({ onOpenPicker }) {
  const { data, loading, error, reload } = useNews();
  const { teams } = useFavourites();
  const [mode, setMode] = useState('all');

  const articles = useMemo(() => data?.articles ?? [], [data]);
  const unavailable = data?.status === 'unavailable';
  const stale = data?.stale || (error && data);

  const hasFavourites = teams.length > 0;
  // Clearing favourites while filtered falls back to everything.
  const effectiveMode = hasFavourites ? mode : 'all';

  // Team tags per headline (mention matching is not free, so compute once).
  const tagged = useMemo(
    () => articles.map((article) => ({ article, tags: hasFavourites ? mentionedTeams(article, teams) : [] })),
    [articles, teams, hasFavourites],
  );
  const shown = effectiveMode === 'mine' ? tagged.filter((t) => t.tags.length) : tagged;

  return (
    <section className="news-container" aria-labelledby="news-heading">
      <div className="news-intro">
        <h2 id="news-heading">Football news</h2>
        <p>Headlines from <a href="https://www.bbc.com/sport/football" target="_blank" rel="noopener noreferrer">BBC Sport<span className="sr-only"> (opens in a new tab)</span></a>. Our service checks for new stories every hour.</p>
      </div>
      <div className="refresh-bar news-refresh">
        <div className="news-sync">
          <p>Last checked: <DateTime value={data?.last_attempt_at} /></p>
          <p>Last successful update: <DateTime value={data?.last_success_at} /></p>
          {data?.next_check_at ? <p>Next scheduled check: <DateTime value={data.next_check_at} /></p> : null}
        </div>
        <button className="btn" type="button" onClick={reload} disabled={loading} aria-busy={loading}>
          {loading ? 'Refreshing…' : 'Refresh news'}
        </button>
      </div>
      <p className="news-note">Refresh loads the latest saved headlines. This page checks for updates every five minutes while open.</p>

      <div className="news-filter">
        <div className="segmented" role="group" aria-label="Headlines to show">
          <button
            type="button"
            className={`segment ${effectiveMode === 'all' ? 'active' : ''}`}
            aria-pressed={effectiveMode === 'all'}
            onClick={() => setMode('all')}
          >
            All
          </button>
          <button
            type="button"
            className={`segment ${effectiveMode === 'mine' ? 'active' : ''}`}
            aria-pressed={effectiveMode === 'mine'}
            aria-disabled={hasFavourites ? undefined : true}
            aria-describedby={hasFavourites ? undefined : 'news-mine-hint'}
            onClick={() => {
              if (hasFavourites) setMode('mine');
            }}
          >
            <StarIcon filled size={15} />My teams
          </button>
        </div>
        {hasFavourites ? null : (
          <p className="news-filter-hint" id="news-mine-hint">
            Follow teams to filter headlines: tap the <StarIcon size={15} className="inline-icon" />
            <span className="sr-only">star</span> next to a team on a match card
            {onOpenPicker ? ' or ' : '.'}
            {onOpenPicker ? (
              <button type="button" className="link-button" onClick={onOpenPicker}>
                choose your teams
              </button>
            ) : null}
            {onOpenPicker ? '.' : null}
          </p>
        )}
      </div>

      {loading && !data ? <p className="news-status" role="status">Loading football news…</p> : null}
      {error ? (
        <div className="inline-alert" role="alert">
          <p><strong>Couldn’t load news.</strong> {articles.length ? 'Showing previously loaded headlines. ' : ''}Try refreshing shortly.</p>
        </div>
      ) : null}
      {!error && (unavailable || stale) ? (
        <div className="inline-alert" role="status">
          <p><strong>{unavailable ? 'News temporarily unavailable.' : 'News updates are delayed.'}</strong>{articles.length ? ' Showing the latest saved headlines.' : ' The service will try again at the next scheduled check.'}</p>
        </div>
      ) : null}
      {data && !articles.length && !unavailable ? (
        <div className="empty-state"><h3>No headlines yet</h3><p>New football stories will appear after the next successful update.</p></div>
      ) : null}
      {articles.length && !shown.length ? (
        <div className="empty-state news-empty-mine">
          <h3>No headlines mention your teams right now</h3>
          <p>
            {articles.length === 1
              ? 'The latest headline does not mention a team you follow.'
              : `None of the ${articles.length} latest headlines mention a team you follow.`}
          </p>
          <button type="button" className="btn btn-primary" onClick={() => setMode('all')}>
            Show all headlines
          </button>
        </div>
      ) : null}
      {shown.length ? (
        <>
          <p className="news-note" role="status">
            {shown.length} {shown.length === 1 ? 'headline' : 'headlines'}
            {effectiveMode === 'mine' ? ' mentioning your teams' : ''} · newest first
          </p>
          <ul className="news-list">
            {shown.map(({ article, tags }) => (
              <li key={article.url}>
                <article className={`news-card ${tags.length ? 'mentions-favourite' : ''}`}>
                  <div className="news-meta">
                    <span>{article.publisher}</span>
                    {article.published_at ? <time dateTime={article.published_at} title={new Date(article.published_at).toLocaleString()}>{publicationAge(article.published_at)}</time> : <span>Publication time unavailable</span>}
                  </div>
                  <h3><a href={article.url} target="_blank" rel="noopener noreferrer">{article.title}<span className="sr-only"> (opens in a new tab)</span></a></h3>
                  {tags.length ? (
                    <ul className="team-tags" aria-label="Your teams in this headline">
                      {tags.map((name) => (
                        <li key={name}>
                          <a className="team-tag" href={teamHref(name)}>
                            <StarIcon filled size={13} />
                            {shortTeamName(name)}
                            <span className="sr-only"> team page</span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </article>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
