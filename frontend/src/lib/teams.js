// Pure helpers for team pages, team search and favourite-aware fixture lists.
// Team names are exact canonical names as stored by the backend
// (football-data.org style, e.g. "Manchester United FC").
import { LEAGUES, normalizeText } from './matches.js';

export const DASH = '—';
export const OTHER_LEAGUE_LABEL = 'Other / Europe';

/**
 * Common short names per canonical name. Used by team search, short display
 * names and news matching. Entries listed in NEWS_AMBIGUOUS (e.g. "Inter",
 * "Milan") still help search but never count as a news mention.
 */
export const TEAM_ALIASES = {
  // Premier League (and recent members)
  'AFC Bournemouth': ['Bournemouth'],
  'Arsenal FC': ['Arsenal', 'Gunners'],
  'Aston Villa FC': ['Aston Villa', 'Villa'],
  'Brentford FC': ['Brentford'],
  'Brighton & Hove Albion FC': ['Brighton', 'Brighton & Hove Albion', 'Brighton and Hove Albion'],
  'Burnley FC': ['Burnley'],
  'Chelsea FC': ['Chelsea'],
  'Crystal Palace FC': ['Crystal Palace', 'Palace'],
  'Everton FC': ['Everton'],
  'Fulham FC': ['Fulham'],
  'Ipswich Town FC': ['Ipswich', 'Ipswich Town'],
  'Leeds United FC': ['Leeds', 'Leeds United'],
  'Leicester City FC': ['Leicester', 'Leicester City'],
  'Liverpool FC': ['Liverpool'],
  'Luton Town FC': ['Luton', 'Luton Town'],
  'Manchester City FC': ['Man City', 'Manchester City'],
  'Manchester United FC': ['Man Utd', 'Man United', 'Manchester United'],
  'Newcastle United FC': ['Newcastle', 'Newcastle United'],
  'Nottingham Forest FC': ['Nottingham Forest', "Nott'm Forest", 'Forest'],
  'Sheffield United FC': ['Sheffield United', 'Sheff Utd', 'Blades'],
  'Southampton FC': ['Southampton', 'Saints'],
  'Sunderland AFC': ['Sunderland'],
  'Tottenham Hotspur FC': ['Spurs', 'Tottenham', 'Tottenham Hotspur'],
  'West Ham United FC': ['West Ham', 'West Ham United'],
  'Wolverhampton Wanderers FC': ['Wolves', 'Wolverhampton'],
  'West Bromwich Albion FC': ['West Brom', 'West Bromwich Albion'],
  'Watford FC': ['Watford'],
  'Norwich City FC': ['Norwich', 'Norwich City'],
  // La Liga
  'FC Barcelona': ['Barcelona', 'Barca', 'Barça'],
  'Real Madrid CF': ['Real Madrid'],
  'Club Atlético de Madrid': ['Atletico Madrid', 'Atlético Madrid', 'Atletico', 'Atleti'],
  'Athletic Club': ['Athletic Bilbao', 'Athletic Club', 'Bilbao'],
  'Real Sociedad de Fútbol': ['Real Sociedad'],
  'Real Betis Balompié': ['Real Betis', 'Betis'],
  'Villarreal CF': ['Villarreal'],
  'Sevilla FC': ['Sevilla', 'Seville'],
  'Valencia CF': ['Valencia'],
  'RC Celta de Vigo': ['Celta Vigo', 'Celta de Vigo', 'Celta'],
  'RCD Espanyol de Barcelona': ['Espanyol'],
  'Rayo Vallecano de Madrid': ['Rayo Vallecano', 'Rayo'],
  'CA Osasuna': ['Osasuna'],
  'Getafe CF': ['Getafe'],
  'Girona FC': ['Girona'],
  'RCD Mallorca': ['Mallorca'],
  'Deportivo Alavés': ['Alaves', 'Alavés'],
  'UD Las Palmas': ['Las Palmas'],
  'CD Leganés': ['Leganes', 'Leganés'],
  'Real Valladolid CF': ['Valladolid', 'Real Valladolid'],
  // Serie A
  'FC Internazionale Milano': ['Inter Milan', 'Internazionale', 'Inter'],
  'AC Milan': ['AC Milan', 'Milan'],
  'Juventus FC': ['Juventus', 'Juve'],
  'SSC Napoli': ['Napoli'],
  'AS Roma': ['Roma'],
  'SS Lazio': ['Lazio'],
  'Atalanta BC': ['Atalanta'],
  'ACF Fiorentina': ['Fiorentina'],
  'Bologna FC 1909': ['Bologna'],
  'Torino FC': ['Torino'],
  'Udinese Calcio': ['Udinese'],
  'Genoa CFC': ['Genoa'],
  'Hellas Verona FC': ['Hellas Verona', 'Verona'],
  'US Sassuolo Calcio': ['Sassuolo'],
  'Cagliari Calcio': ['Cagliari'],
  'US Lecce': ['Lecce'],
  'Como 1907': ['Como'],
  'Parma Calcio 1913': ['Parma'],
  'Empoli FC': ['Empoli'],
  'AC Monza': ['Monza'],
  'Venezia FC': ['Venezia'],
  // Bundesliga
  'FC Bayern München': ['Bayern Munich', 'Bayern', 'Bayern München'],
  'Borussia Dortmund': ['Dortmund', 'BVB'],
  'Bayer 04 Leverkusen': ['Bayer Leverkusen', 'Leverkusen'],
  'RB Leipzig': ['Leipzig'],
  'Eintracht Frankfurt': ['Eintracht Frankfurt', 'Frankfurt'],
  'VfB Stuttgart': ['Stuttgart'],
  'VfL Wolfsburg': ['Wolfsburg'],
  'Borussia Mönchengladbach': ['Gladbach', 'Monchengladbach', 'Borussia Monchengladbach'],
  'SC Freiburg': ['Freiburg'],
  'TSG 1899 Hoffenheim': ['Hoffenheim'],
  'SV Werder Bremen': ['Werder Bremen', 'Bremen'],
  '1. FC Union Berlin': ['Union Berlin'],
  '1. FC Köln': ['Cologne', 'Koln', 'Köln'],
  '1. FSV Mainz 05': ['Mainz'],
  'FC Augsburg': ['Augsburg'],
  'VfL Bochum 1848': ['Bochum'],
  '1. FC Heidenheim 1846': ['Heidenheim'],
  'FC St. Pauli 1910': ['St Pauli', 'St. Pauli'],
  'Holstein Kiel': ['Holstein Kiel', 'Kiel'],
  'Hamburger SV': ['Hamburg', 'HSV'],
  'FC Schalke 04': ['Schalke'],
  // Ligue 1
  'Paris Saint-Germain FC': ['PSG', 'Paris Saint-Germain', 'Paris St-Germain'],
  'Olympique de Marseille': ['Marseille', 'OM'],
  'Olympique Lyonnais': ['Lyon', 'OL'],
  'AS Monaco FC': ['Monaco'],
  'Lille OSC': ['Lille'],
  'OGC Nice': ['OGC Nice', 'Nice'],
  'RC Lens': ['Lens'],
  'Stade Rennais FC 1901': ['Rennes'],
  'Stade Brestois 29': ['Brest'],
  'RC Strasbourg Alsace': ['Strasbourg'],
  'FC Nantes': ['Nantes'],
  'Toulouse FC': ['Toulouse'],
  'Stade de Reims': ['Reims'],
  'Montpellier HSC': ['Montpellier'],
  'AJ Auxerre': ['Auxerre'],
  'Angers SCO': ['Angers'],
  'Le Havre AC': ['Le Havre'],
  'AS Saint-Étienne': ['Saint-Etienne', 'St Etienne'],
  'FC Lorient': ['Lorient'],
  'FC Metz': ['Metz'],
  'Paris FC': ['Paris FC'],
};

// Words that are never enough on their own to say a headline is about a club.
// Compared after folding (lower case, no accents/punctuation).
export const NEWS_AMBIGUOUS = new Set([
  // Shared by several clubs ("Manchester", "United", "Madrid", "Milan", "Paris", ...).
  'city', 'united', 'utd', 'town', 'albion', 'rovers', 'wanderers', 'athletic', 'sporting',
  'real', 'club', 'west', 'manchester', 'man', 'sheffield', 'bristol', 'nottingham',
  'birmingham', 'london', 'milan', 'inter', 'madrid', 'paris', 'stade', 'olympique',
  'borussia', 'bayer', 'eintracht', 'calcio',
  // Nicknames or ordinary words that often mean something else in a headline.
  'nice', 'forest', 'villa', 'palace', 'saints', 'blades', 'gunners', 'om', 'ol',
]);

// Leading/trailing tokens dropped to get a team's plain name
// ("SSC Napoli" -> "Napoli", "Bologna FC 1909" -> "Bologna").
const AFFIXES = new Set([
  'fc', 'afc', 'cf', 'cfc', 'ssc', 'sc', 'ac', 'acf', 'as', 'ss', 'bc', 'ud', 'cd', 'rc',
  'rcd', 'sd', 'us', 'osc', 'ogc', 'hsc', 'sco', 'fco', 'tsg', 'vfl', 'vfb', 'fsv', 'sv',
  'aj', 'ca', 'calcio', 'balompie', 'spvgg', 'dsc', 'bsc',
]);

const isAffix = (token) => AFFIXES.has(normalizeText(token).replace(/\./g, '')) || /^\d+\.?$/.test(token);

/** "SSC Napoli" -> "Napoli", "1. FC Köln" -> "Köln", "Arsenal FC" -> "Arsenal". */
export function stripTeamAffixes(name) {
  const tokens = String(name ?? '').trim().split(/\s+/).filter(Boolean);
  let start = 0;
  let end = tokens.length;
  while (start < end - 1 && isAffix(tokens[start])) start += 1;
  while (end - 1 > start && isAffix(tokens[end - 1])) end -= 1;
  return tokens.slice(start, end).join(' ');
}

export const teamAliases = (name) => TEAM_ALIASES[name] ?? [];

/** Compact display name: first alias, else the name without "FC"-style affixes. */
export function shortTeamName(name) {
  return teamAliases(name)[0] ?? (stripTeamAffixes(name) || String(name ?? ''));
}

// ---- Routes -----------------------------------------------------------------

export const TEAM_ROUTE_PREFIX = '#/team/';

export function teamHref(name) {
  return `${TEAM_ROUTE_PREFIX}${encodeURIComponent(String(name ?? ''))}`;
}

/** Team name from "#/team/<encoded>" (trailing slash allowed), else null. */
export function parseTeamRoute(hash) {
  const value = String(hash ?? '');
  if (!value.startsWith(TEAM_ROUTE_PREFIX)) return null;
  const encoded = value.slice(TEAM_ROUTE_PREFIX.length).replace(/\/+$/, '');
  if (!encoded || encoded.includes('/')) return null;
  try {
    const name = decodeURIComponent(encoded).trim();
    return name || null;
  } catch {
    return null; // malformed percent-encoding
  }
}

// ---- Team index -------------------------------------------------------------

const entryName = (entry) => (typeof entry === 'string' ? entry : entry?.name);
const entryLeague = (entry) => (typeof entry === 'object' && entry ? entry.league ?? null : null);

function cleanIndex(index) {
  if (!Array.isArray(index)) return [];
  const seen = new Set();
  const out = [];
  for (const entry of index) {
    const name = entryName(entry);
    if (typeof name !== 'string' || !name.trim() || seen.has(name)) continue;
    seen.add(name);
    const league = entryLeague(entry);
    out.push({ name, league: typeof league === 'string' && league ? league : null });
  }
  return out;
}

/**
 * Group `/teams/index` items by league: known leagues in LEAGUES order, then
 * unknown codes alphabetically, then teams without a league ("Other / Europe").
 * Returns [{ league: code|null, label, teams: [{name, league}] }].
 */
export function groupTeamsByLeague(index) {
  const groups = new Map();
  for (const team of cleanIndex(index)) {
    if (!groups.has(team.league)) groups.set(team.league, []);
    groups.get(team.league).push(team);
  }
  const known = Object.keys(LEAGUES).filter((code) => groups.has(code));
  const unknown = [...groups.keys()].filter((code) => code !== null && !(code in LEAGUES)).sort();
  const order = [...known, ...unknown, ...(groups.has(null) ? [null] : [])];
  return order.map((league) => ({
    league,
    label: league === null ? OTHER_LEAGUE_LABEL : LEAGUES[league]?.name ?? league,
    teams: groups.get(league).sort((a, b) => a.name.localeCompare(b.name)),
  }));
}

const searchFold = (value) =>
  normalizeText(value)
    .replace(/[.'’]/g, '')
    .replace(/[-‐-―&]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

/**
 * Filter (and rank) index items by a free-text query. Case- and
 * accent-insensitive; matches canonical names, plain names and aliases
 * ("barca", "spurs", "inter", "man utd"). Empty query returns every team.
 * Ranking: exact name/alias, then prefix (of the name or a word), then substring.
 */
export function searchTeams(index, query) {
  const teams = cleanIndex(index);
  const q = searchFold(query);
  if (!q) return teams;
  const scored = [];
  for (const team of teams) {
    const candidates = [team.name, stripTeamAffixes(team.name), ...teamAliases(team.name)].map(searchFold);
    let best = Infinity;
    for (const c of candidates) {
      if (c === q) best = Math.min(best, 0);
      else if (c.startsWith(q)) best = Math.min(best, 1);
      else if (c.split(' ').some((word) => word.startsWith(q))) best = Math.min(best, 2);
      else if (c.includes(q)) best = Math.min(best, 3);
    }
    if (best !== Infinity) scored.push({ team, best });
  }
  return scored
    .sort((a, b) => a.best - b.best || a.team.name.localeCompare(b.team.name))
    .map((s) => s.team);
}

// ---- Formatting ---------------------------------------------------------------

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

export const FORM_LABELS = { W: 'Win', D: 'Draw', L: 'Loss' };

/** "WDL" (newest last) -> [{result: 'W', label: 'Win'}, ...]; other chars ignored. */
export function formDots(last5) {
  return [...String(last5 ?? '').toUpperCase()]
    .filter((c) => c in FORM_LABELS)
    .map((result) => ({ result, label: FORM_LABELS[result] }));
}

/** Spoken summary for a form string, e.g. "Last 3: Win, Draw, Loss (most recent last)". */
export function formSummary(last5) {
  const dots = formDots(last5);
  if (!dots.length) return 'No recent matches';
  return `Last ${dots.length}: ${dots.map((d) => d.label).join(', ')} (most recent last)`;
}

/** Elo rating as a whole number ("1712"). */
export const formatElo = (v) => (isNum(v) ? String(Math.round(v)) : DASH);

/** Signed Elo change with one decimal ("+14.6", "−3.2", "0.0"). */
export function formatEloChange(v) {
  if (!isNum(v)) return DASH;
  const rounded = Math.round(v * 10) / 10;
  if (rounded === 0) return '0.0';
  return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toFixed(1)}`;
}

/** A 0..1 rate as a percentage ("40%"); `digits` decimals. */
export const formatRate = (v, digits = 0) => (isNum(v) ? `${(v * 100).toFixed(digits)}%` : DASH);

/** Alias of formatRate for probabilities. */
export const formatPercent = formatRate;

/** Average with fixed decimals ("1.9"). */
export const formatAverage = (v, digits = 1) => (isNum(v) ? v.toFixed(digits) : DASH);

export function ordinal(n) {
  if (!Number.isInteger(n)) return DASH;
  const mod100 = Math.abs(n) % 100;
  const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : { 1: 'st', 2: 'nd', 3: 'rd' }[Math.abs(n) % 10] ?? 'th';
  return `${n}${suffix}`;
}

/** "2nd of 20", "2nd" without a size, "—" without a rank. */
export function formatRank(rank, size) {
  if (!Number.isInteger(rank)) return DASH;
  return Number.isInteger(size) ? `${ordinal(rank)} of ${size}` : ordinal(rank);
}

/** "5W 2D 1L" from a season/venue record. */
export function formatRecord(record) {
  if (!record || typeof record !== 'object') return DASH;
  const { w, d, l } = record;
  if (![w, d, l].every(Number.isInteger)) return DASH;
  return `${w}W ${d}D ${l}L`;
}

// ---- Favourites + fixtures ------------------------------------------------------

const asSet = (teams) => (teams instanceof Set ? teams : new Set(Array.isArray(teams) ? teams : []));

/** True when either side of a fixture is one of `teams` (array or Set). */
export function isFavouriteFixture(fixture, teams) {
  if (!fixture) return false;
  const set = asSet(teams);
  return set.has(fixture.home_team) || set.has(fixture.away_team);
}

/**
 * Stable sort: fixtures involving `primary` first, then other favourites, then
 * the rest; the original order is kept inside each band. Returns a new array.
 */
export function sortFixturesFavouritesFirst(fixtures, teams, primary = null) {
  const set = asSet(teams);
  const band = (f) => {
    if (primary && (f?.home_team === primary || f?.away_team === primary)) return 0;
    return isFavouriteFixture(f, set) ? 1 : 2;
  };
  return (Array.isArray(fixtures) ? fixtures : [])
    .map((fixture, i) => ({ fixture, i, band: band(fixture) }))
    .sort((a, b) => a.band - b.band || a.i - b.i)
    .map((x) => x.fixture);
}
