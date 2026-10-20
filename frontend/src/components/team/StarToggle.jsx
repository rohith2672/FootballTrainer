import { MAX_FAVOURITES } from '../../lib/favourites.js';

export function StarIcon({ filled }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false" className="star-icon">
      <path
        d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2l-5.7 3.1 1.2-6.4-4.7-4.4 6.4-.8z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Favourite toggle for one team (pass the object from useFavourites()).
 * Disabled for a new team when the list is full. `label` shows visible text
 * next to the star (e.g. on the team page header).
 */
function StarToggle({ name, favourites, label = false, className = '' }) {
  const on = favourites.isFavourite(name);
  const full = !on && favourites.teams.length >= MAX_FAVOURITES;
  return (
    <button
      type="button"
      className={`star-toggle ${on ? 'on' : ''} ${label ? 'with-label' : ''} ${className}`.trim()}
      aria-pressed={on}
      aria-label={label ? undefined : on ? `Remove ${name} from favourites` : `Add ${name} to favourites`}
      title={full ? `You can follow up to ${MAX_FAVOURITES} teams` : undefined}
      disabled={full}
      onClick={() => favourites.toggle(name)}
    >
      <StarIcon filled={on} />
      {/* Constant text: the pressed state, not the label, says whether it is on. */}
      {label ? <span>Favourite</span> : null}
    </button>
  );
}

export default StarToggle;
