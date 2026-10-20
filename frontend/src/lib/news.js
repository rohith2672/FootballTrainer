/** News responses are cached server-side; client refresh never contacts publishers. */
export const NEWS_POLL_MS = 5 * 60 * 1000;
export const NEWS_STALE_MS = 90 * 60 * 1000;
export const NEWS_EXPIRE_MS = 24 * 60 * 60 * 1000;

function freshnessTime(data) {
  return Date.parse(data.last_success_at) || Math.max(0, ...data.articles.map((a) => Date.parse(a.fetched_at) || 0));
}

/** A long-open page must not keep presenting expired cache during an outage. */
export function ageNewsCache(data, now = Date.now()) {
  if (!data) return null;
  const lastSuccess = freshnessTime(data);
  const expired = !lastSuccess || now - lastSuccess >= NEWS_EXPIRE_MS;
  return {
    ...data,
    articles: expired ? [] : data.articles.filter((article) => {
      const fetched = Date.parse(article.fetched_at) || lastSuccess;
      return now - fetched < NEWS_EXPIRE_MS;
    }),
    stale: data.stale || !lastSuccess || now - lastSuccess >= NEWS_STALE_MS,
    status: expired ? 'unavailable' : data.status,
  };
}

/** Set a local boundary timer so stale/expiry changes do not rely on requests succeeding. */
export function nextNewsBoundary(data, now = Date.now()) {
  if (!data) return null;
  const success = freshnessTime(data);
  const boundaries = [success + NEWS_STALE_MS, success + NEWS_EXPIRE_MS,
    ...data.articles.map((article) => (Date.parse(article.fetched_at) || success) + NEWS_EXPIRE_MS)];
  const pending = boundaries.filter((value) => value > now);
  return pending.length ? Math.min(...pending) - now : null;
}

export function safeArticleUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      ? url.href : null;
  } catch {
    return null;
  }
}

function timestamp(value) {
  return typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : null;
}

export function normalizeNews(raw) {
  if (!raw || !Array.isArray(raw.articles) || !['ok', 'stale', 'unavailable'].includes(raw.status)) {
    throw new Error('The news service returned an unexpected response.');
  }
  const seen = new Set();
  const articles = raw.articles.flatMap((article) => {
    if (!article || typeof article.title !== 'string' || !article.title.trim()) return [];
    const url = safeArticleUrl(article.url);
    if (!url || seen.has(url)) return [];
    seen.add(url);
    return [{
      id: String(article.id ?? url),
      title: article.title.trim(),
      url,
      publisher: typeof article.publisher === 'string' && article.publisher.trim()
        ? article.publisher.trim() : 'Source',
      published_at: timestamp(article.published_at),
      fetched_at: timestamp(article.fetched_at),
    }];
  }).sort((a, b) => (Date.parse(b.published_at) || 0) - (Date.parse(a.published_at) || 0));
  return {
    articles,
    status: raw.status,
    stale: raw.stale === true || raw.status === 'stale',
    last_attempt_at: timestamp(raw.last_attempt_at),
    last_success_at: timestamp(raw.last_success_at),
    next_check_at: timestamp(raw.next_check_at),
  };
}

export function publicationAge(value, now = Date.now()) {
  const published = Date.parse(value);
  if (!Number.isFinite(published)) return 'Publication time unavailable';
  const minutes = Math.floor(Math.max(0, now - published) / 60000);
  if (minutes < 1) return 'Just published';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return `${days} ${days === 1 ? 'day' : 'days'} ago`;
}

/** Injected browser/timer dependencies keep visibility behavior easy to verify. */
export function subscribeNewsPolling(load, page = document, clock = globalThis) {
  const refreshVisible = () => { if (page.visibilityState === 'visible') load(); };
  const timer = clock.setInterval(refreshVisible, NEWS_POLL_MS);
  page.addEventListener('visibilitychange', refreshVisible);
  return () => {
    clock.clearInterval(timer);
    page.removeEventListener('visibilitychange', refreshVisible);
  };
}
