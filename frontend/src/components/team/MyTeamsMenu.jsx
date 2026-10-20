import { useEffect, useId, useRef, useState } from 'react';
import { useFavourites } from '../../hooks/useFavourites';
import { orderFavourites } from '../../lib/picker.js';
import { teamHref } from '../../lib/teams.js';

/**
 * "My teams" nav entry: a disclosure menu with links to favourite team pages
 * (primary first) and a "Choose teams…" entry that opens the picker.
 */
function MyTeamsMenu({ currentTeam, onOpenPicker }) {
  const { teams, primary } = useFavourites();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const buttonRef = useRef(null);
  const menuId = useId();
  const ordered = orderFavourites(teams, primary);
  const active = Boolean(currentTeam && teams.includes(currentTeam));

  // Close on outside click / focus leaving the menu.
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false);
    };
    const onFocus = (e) => {
      if (!rootRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('focusin', onFocus);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('focusin', onFocus);
    };
  }, [open]);

  const onKeyDown = (e) => {
    if (e.key === 'Escape' && open) {
      e.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    }
  };

  return (
    <div className="my-teams" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        className={`nav-tab my-teams-btn ${active ? 'active' : ''}`}
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((o) => !o)}
      >
        My teams
        {teams.length ? (
          <span className="my-teams-count">
            {teams.length}
            <span className="sr-only"> {teams.length === 1 ? 'favourite' : 'favourites'}</span>
          </span>
        ) : null}
        <span className="my-teams-chevron" aria-hidden="true">{open ? '▴' : '▾'}</span>
      </button>
      <div id={menuId} className="my-teams-menu" hidden={!open}>
        {ordered.length ? (
          <ul className="my-teams-list" aria-label="Favourite teams">
            {ordered.map((name) => (
              <li key={name}>
                <a
                  href={teamHref(name)}
                  className="my-teams-link"
                  aria-current={name === currentTeam ? 'page' : undefined}
                  onClick={() => setOpen(false)}
                >
                  <span className="my-teams-name">{name}</span>
                  {name === primary ? <span className="primary-tag small">Primary</span> : null}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="my-teams-empty">No favourite teams yet.</p>
        )}
        <button
          type="button"
          className="btn btn-small my-teams-choose"
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
    </div>
  );
}

export default MyTeamsMenu;
