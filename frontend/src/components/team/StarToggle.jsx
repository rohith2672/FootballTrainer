import { MAX_FAVOURITES } from '../../lib/favourites.js';
import { StarIcon } from '../icons';

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
