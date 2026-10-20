import { useNews } from '../hooks/useNews';
import { publicationAge } from '../lib/news';

function DateTime({ value, fallback = 'Not yet available' }) {
  return value ? <time dateTime={value}>{new Date(value).toLocaleString()}</time> : fallback;
}

export default function News() {
  const { data, loading, error, reload } = useNews();
  const articles = data?.articles ?? [];
  const unavailable = data?.status === 'unavailable';
  const stale = data?.stale || (error && data);

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
      {articles.length ? (
        <>
          <p className="news-note" role="status">{articles.length} {articles.length === 1 ? 'headline' : 'headlines'} · newest first</p>
          <ul className="news-list">
            {articles.map((article) => (
              <li key={article.url}>
                <article className="news-card">
                  <div className="news-meta">
                    <span>{article.publisher}</span>
                    {article.published_at ? <time dateTime={article.published_at} title={new Date(article.published_at).toLocaleString()}>{publicationAge(article.published_at)}</time> : <span>Publication time unavailable</span>}
                  </div>
                  <h3><a href={article.url} target="_blank" rel="noopener noreferrer">{article.title}<span className="sr-only"> (opens in a new tab)</span></a></h3>
                </article>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
