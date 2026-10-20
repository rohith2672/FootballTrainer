import { useEffect, useId, useRef, useState } from 'react';
import { useFavourites } from '../../hooks/useFavourites';
import { orderFavourites } from '../../lib/picker.js';
import { dashboardHash } from '../../lib/routes.js';
import { teamHref } from '../../lib/teams.js';
import { ChevronDownIcon, StarIcon } from '../icons';

/**
 * "My teams" nav entry: a disclosure menu with links to favourite team pages
 * (primary first), the Upcoming view filtered to those teams, and a
 * "Choose teams…" entry that opens the picker. With no favourites yet the
 * button opens the picker directly. On phones the menu opens upward from the
 * bottom tab bar (see shell.css).
 */
function MyTeamsMenu({ currentTeam, onOpenPicker }) {
  const { teams, primary } = useFavourites();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const menuId = useId();
  const ordered = orderFavourites(teams, primary);
  const active = Boolean(currentTeam && teams.includes(currentTeam));
  const hasTeams = teams.length > 0;
  const expanded = open && hasTeams;

  // Close on outside click / focus leaving the menu.
  useEffect(() => {
    if (!expanded) return undefined;
    const onOutside = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener('pointerdown', onOutside);
    document.addEventListener('focusin', onOutside);
    return () => {
      document.removeEventListener('pointerdown', onOutside);
      document.removeEventListener('focusin', onOutside);
    };
  }, [expanded]);

  const onKeyDown = (e) => {
    if (e.key === 'Escape' && expanded) {
      e.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    }
  };

  const close = () => setOpen(false);

  return (
    <div className="nav-teams" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        className={`nav-tab nav-teams-btn ${active ? 'active' : ''}`}
        aria-expanded={hasTeams ? expanded : undefined}
        aria-controls={hasTeams ? menuId : undefined}
        aria-haspopup={hasTeams ? undefined : 'dialog'}
        onClick={() => (hasTeams ? setOpen((o) => !o) : onOpenPicker())}
      >
        <StarIcon filled={hasTeams} size={18} className="nav-icon" />
        <span className="nav-label">My teams</span>
        {hasTeams ? (
          <span className="nav-teams-count">
            {teams.length}
            <span className="sr-only"> {teams.length === 1 ? 'favourite' : 'favourites'}</span>
          </span>
        ) : null}
        {hasTeams ? <ChevronDownIcon up={expanded} size={14} className="nav-teams-chevron" /> : null}
      </button>
      {hasTeams ? (
        <div id={menuId} className="nav-teams-menu" hidden={!expanded}>
          <ul className="nav-teams-list" aria-label="Favourite teams">
            {ordered.map((name) => (
              <li key={name}>
                <a
                  href={teamHref(name)}
                  className="nav-teams-link"
                  aria-current={name === currentTeam ? 'page' : undefined}
                  onClick={close}
                >
                  <span className="nav-teams-name">{name}</span>
                  {name === primary ? <span className="tp-primary-tag small">Primary</span> : null}
                </a>
              </li>
            ))}
          </ul>
          <a className="nav-teams-link nav-teams-fixtures" href={dashboardHash({ mine: true })} onClick={close}>
            Upcoming fixtures for my teams
          </a>
          <button
            type="button"
            className="btn btn-small nav-teams-choose"
            onClick={() => {
              setOpen(false);
              // The picker returns focus to whatever was focused when it opened;
              // this button is about to be hidden, so hand focus to the menu button.
              buttonRef.current?.focus();
              onOpenPicker();
            }}
          >
            Choose teams…
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default MyTeamsMenu;
