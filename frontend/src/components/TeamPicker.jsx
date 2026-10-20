import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { describeTeamError } from '../api';
import { useFavourites } from '../hooks/useFavourites';
import { useTeamsIndex } from '../hooks/useTeamsIndex';
import { MAX_FAVOURITES } from '../lib/favourites.js';
import { leagueInfo } from '../lib/matches.js';
import { groupTeamsByLeague, searchTeams, teamHref } from '../lib/teams.js';
import { focusableWithin, orderFavourites, pickerCountText, pickerResultsText } from '../lib/picker.js';
import StarToggle from './team/StarToggle';
import '../styles/team.css';

function YourTeams({ favourites, onNavigate }) {
  const { teams, primary } = favourites;
  if (!teams.length) {
    return (
      <p className="picker-hint">
        Star a team below to follow it. Your first team becomes your primary team; its fixtures are
        listed first.
      </p>
    );
  }
  const ordered = orderFavourites(teams, primary);
  return (
    <section className="picker-section" aria-labelledby="picker-yours">
      <h3 id="picker-yours" className="picker-group-title">Your teams</h3>
      <ul className="picker-list">
        {ordered.map((name) => (
          <li key={name} className="picker-row">
            <a className="picker-team" href={teamHref(name)} onClick={onNavigate}>
              {name}
            </a>
            {name === primary ? (
              <span className="tp-primary-tag">
                <span aria-hidden="true">★ </span>Primary
              </span>
            ) : (
              <button
                type="button"
                className="btn btn-small"
                onClick={() => favourites.setPrimary(name)}
                aria-label={`Make ${name} your primary team`}
              >
                Make primary
              </button>
            )}
            <StarToggle name={name} favourites={favourites} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function PickerBody({ onClose }) {
  const dialogRef = useRef(null);
  const searchRef = useRef(null);
  const [query, setQuery] = useState('');
  const favourites = useFavourites();
  const { teams, loading, error, reload } = useTeamsIndex();
  const titleId = useId();
  const descId = useId();
  const searchId = useId();

  const groups = useMemo(() => groupTeamsByLeague(searchTeams(teams, query)), [teams, query]);
  const resultCount = groups.reduce((n, g) => n + g.teams.length, 0);

  // Open as a modal (the rest of the page becomes inert) and restore focus on close.
  useEffect(() => {
    const dialog = dialogRef.current;
    const opener = document.activeElement;
    const hash = window.location.hash;
    if (dialog && !dialog.open) {
      try {
        dialog.showModal();
      } catch {
        dialog.setAttribute('open', '');
      }
    }
    searchRef.current?.focus();
    return () => {
      if (dialog?.open) dialog.close();
      // Following a team link changes the route; the app then moves focus itself.
      if (window.location.hash === hash && opener instanceof HTMLElement && opener.isConnected) {
        opener.focus();
      }
    };
  }, []);

  const onCancel = (e) => {
    e.preventDefault(); // React state decides whether the dialog is open.
    onClose();
  };

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key !== 'Tab') return;
    const items = focusableWithin(dialogRef.current);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  // A click on the backdrop lands on the <dialog> element itself.
  const onClick = (e) => {
    if (e.target === dialogRef.current) onClose();
  };

  let results;
  if (loading && !teams.length) {
    results = (
      <div className="picker-status" role="status">
        <span className="mini-spinner" aria-hidden="true" /> Loading teams…
      </div>
    );
  } else if (error && !teams.length) {
    const { title, message } = describeTeamError(error);
    results = (
      <div className="picker-status picker-error" role="alert">
        <p><strong>{title}.</strong> {message}</p>
        <button type="button" className="btn" onClick={reload}>Retry</button>
      </div>
    );
  } else if (!resultCount) {
    results = (
      <p className="picker-status">
        {query.trim() ? `No teams match “${query.trim()}”.` : 'No teams are available yet.'}
      </p>
    );
  } else {
    results = groups.map((group) => {
      const info = group.league ? leagueInfo(group.league) : null;
      const headingId = `${searchId}-${group.league ?? 'other'}`;
      return (
        <section key={group.league ?? 'other'} className="picker-section" aria-labelledby={headingId}>
          <h3 id={headingId} className="picker-group-title">
            {info ? <span aria-hidden="true">{info.emoji} </span> : null}
            {group.label}
          </h3>
          <ul className="picker-list">
            {group.teams.map((team) => (
              <li key={team.name} className="picker-row">
                <a className="picker-team" href={teamHref(team.name)} onClick={onClose}>
                  {team.name}
                </a>
                <StarToggle name={team.name} favourites={favourites} />
              </li>
            ))}
          </ul>
        </section>
      );
    });
  }

  return (
    <dialog
      ref={dialogRef}
      className="team-picker"
      aria-labelledby={titleId}
      aria-describedby={descId}
      onCancel={onCancel}
      onKeyDown={onKeyDown}
      onClick={onClick}
    >
      <div className="picker-inner">
        <div className="picker-head">
          <h2 id={titleId} className="picker-title">Choose your teams</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close team picker">
            <span aria-hidden="true">✕</span>
          </button>
        </div>
        <p id={descId} className="picker-count" aria-live="polite">
          {pickerCountText(favourites.teams.length, MAX_FAVOURITES)}
        </p>

        <div className="picker-scroll">
          <YourTeams favourites={favourites} onNavigate={onClose} />

          <div className="field picker-search">
            <label htmlFor={searchId}>Search all teams</label>
            <input
              ref={searchRef}
              id={searchId}
              type="search"
              value={query}
              placeholder="e.g. Arsenal, Barça, Spurs"
              autoComplete="off"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <p className="sr-only" aria-live="polite">
            {teams.length ? pickerResultsText(resultCount, query) : ''}
          </p>
          {results}
        </div>

        <div className="picker-foot">
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </dialog>
  );
}

/**
 * Modal team picker: search every known team (grouped by league), star
 * favourites and choose the primary team. Favourites persist in localStorage.
 * Rendered only while `open`; Esc, the close button, "Done" or a click on the
 * backdrop call `onClose`, and focus returns to whatever opened it.
 */
export default function TeamPicker({ open, onClose }) {
  if (!open) return null;
  return <PickerBody onClose={onClose} />;
}
