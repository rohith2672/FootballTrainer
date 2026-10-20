import { LEAGUES, leagueInfo } from '../../lib/matches.js';

/**
 * Short text badge for a competition ("PL", "LL", "CL", ...) on its league
 * colour. Decorative by default (the league name is next to it); pass
 * `labelled` to expose the full name when the badge stands alone.
 * `size`: 'sm' | 'md' | 'lg'.
 */
function LeagueBadge({ code, size = 'md', labelled = false, className = '' }) {
  const info = leagueInfo(code);
  const known = code in LEAGUES;
  return (
    <span
      className={`lg-badge lg-${size} ${known ? `lg-${code}` : 'lg-other'} ${className}`.trim()}
      aria-hidden={labelled ? undefined : 'true'}
      role={labelled ? 'img' : undefined}
      aria-label={labelled ? info.name : undefined}
      title={labelled ? info.name : undefined}
    >
      {info.short}
    </span>
  );
}

export default LeagueBadge;
