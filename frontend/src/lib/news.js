import { NEWS_AMBIGUOUS, TEAM_ALIASES, stripTeamAffixes, teamAliases } from './teams.js';

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

// ---- Team mentions in headlines ----------------------------------------------
//
// A headline mentions a team when it contains one of the team's keys: its
// canonical name, the name without "FC"-style affixes ("SSC Napoli" ->
// "Napoli") or a known alias ("Man Utd"). Guards against false positives:
// - keys that are ambiguous on their own ("Manchester", "United", "City",
//   "Milan", "Madrid", "Paris", "Inter", "Nice") are never used;
// - matching is on whole words (Unicode-aware), so "Villarreal" is not "Villa";
// - capitalised key words must be capitalised in the headline, so the verb in
//   "Saka spurs Arsenal on" is not Tottenham;
// - a match inside a longer match of another club is ignored, so
//   "Espanyol de Barcelona" is not FC Barcelona.

/** Accent-free, punctuation-light text that keeps letter case. */
function foldHeadline(value) {
  return String(value ?? '')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .replace(/[‘’`´]/g, "'")
    .replace(/\./g, '')
    .replace(/[-‐-―]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const isUpper = (ch) => !!ch && ch !== ch.toLowerCase() && ch === ch.toUpperCase();

const keyCache = new Map();

/** Folded, unambiguous key strings for one canonical team name (cached). */
function teamKeys(name) {
  if (keyCache.has(name)) return keyCache.get(name);
  const keys = new Set();
  for (const raw of [name, stripTeamAffixes(name), ...teamAliases(name)]) {
    const key = foldHeadline(raw);
    if (key.length < 3 || NEWS_AMBIGUOUS.has(key.toLowerCase())) continue;
    keys.add(key);
  }
  const entry = { keys: [...keys], lower: [...keys].map((k) => k.toLowerCase()), matchers: null };
  keyCache.set(name, entry);
  return entry;
}

/** Compiled matchers for one team, built on first use. */
function teamMatchers(name) {
  const entry = teamKeys(name);
  entry.matchers ??= entry.keys.map((key) => ({
    words: key.split(' '),
    regex: new RegExp(
      `(?<![\\p{L}\\p{N}])${key.split(' ').map(escapeRegExp).join('\\s+')}(?![\\p{L}\\p{N}])`,
      'giu',
    ),
  }));
  return entry.matchers;
}

/** [{start, end}] spans where `name` is mentioned in an already folded title. */
function findMentions(folded, name) {
  const spans = [];
  for (const { words, regex } of teamMatchers(name)) {
    regex.lastIndex = 0;
    for (const m of folded.matchAll(regex)) {
      const found = m[0].split(/\s+/);
      const casingOk = words.every((word, i) => !isUpper(word[0]) || isUpper(found[i]?.[0]));
      if (casingOk) spans.push({ start: m.index, end: m.index + m[0].length });
    }
  }
  return spans;
}

const articleTitle = (article) => (typeof article === 'string' ? article : article?.title);

/** The subset of `teams` (canonical names, in their given order) a headline mentions. */
export function mentionedTeams(article, teams) {
  const title = articleTitle(article);
  const list = [...new Set(Array.isArray(teams) || teams instanceof Set ? teams : [])].filter(
    (t) => typeof t === 'string' && t.trim(),
  );
  if (typeof title !== 'string' || !title.trim() || !list.length) return [];
  const folded = foldHeadline(title);

  const candidates = list
    .map((name) => ({ name, spans: findMentions(folded, name) }))
    .filter((c) => c.spans.length);
  if (!candidates.length) return [];

  // A span is shadowed by a longer mention of another known club containing
  // it ("Barcelona" inside "Espanyol de Barcelona"). Only clubs with a longer
  // key that contains the span's text can do that, so only those are scanned.
  const others = [...new Set([...Object.keys(TEAM_ALIASES), ...list])];
  const shadowed = (name, span) => {
    const text = folded.slice(span.start, span.end).toLowerCase().replace(/\s+/g, ' ');
    const length = span.end - span.start;
    return others.some(
      (other) =>
        other !== name &&
        teamKeys(other).lower.some((key) => key.length > text.length && key.includes(text)) &&
        findMentions(folded, other).some(
          (o) => o.start <= span.start && o.end >= span.end && o.end - o.start > length,
        ),
    );
  };

  return candidates
    .filter((c) => c.spans.some((span) => !shadowed(c.name, span)))
    .map((c) => c.name);
}

/** True when the article's headline mentions at least one of `teams`. */
export function matchesTeams(article, teams) {
  return mentionedTeams(article, teams).length > 0;
}

/** Articles whose headline mentions any of `teams` (order preserved). */
export function filterNewsForTeams(articles, teams) {
  if (!Array.isArray(articles)) return [];
  return articles.filter((article) => matchesTeams(article, teams));
}

/**
 * What the team page's news card shows:
 * - 'loading' / 'error': nothing loaded yet (first request pending / failed);
 * - 'list': at least one cached headline mentions the team;
 * - 'unavailable': the news cache is unavailable (status "unavailable"), so
 *   nothing can be said about mentions;
 * - 'no-headlines': the cache is reachable but holds no headlines at all;
 * - 'no-match': headlines exist and none mention the team.
 * `matched` is the already filtered list for the team.
 */
export function teamNewsState({ data, loading = false, error = null, matched = [] } = {}) {
  if (!data) return loading || !error ? 'loading' : 'error';
  if (matched.length) return 'list';
  if (data.status === 'unavailable') return 'unavailable';
  if (!Array.isArray(data.articles) || !data.articles.length) return 'no-headlines';
  return 'no-match';
}
