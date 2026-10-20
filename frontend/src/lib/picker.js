// Small helpers for the team picker dialog and the "My teams" menu.

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** Visible, focusable descendants of `root` in DOM order (for a focus trap). */
export function focusableWithin(root) {
  if (!root?.querySelectorAll) return [];
  return [...root.querySelectorAll(FOCUSABLE)].filter(
    (el) => !el.hidden && !el.closest('[hidden]') && el.getClientRects().length > 0,
  );
}

/** "3 of 20 favourite teams" / "No favourite teams yet (up to 20)" / "... — list full". */
export function pickerCountText(count, max) {
  if (!count) return `No favourite teams yet (you can follow up to ${max}).`;
  const base = `${count} of ${max} favourite ${max === 1 ? 'team' : 'teams'}`;
  return count >= max ? `${base} — the list is full. Remove one to add another.` : `${base}.`;
}

/** Screen-reader summary of the search results. */
export function pickerResultsText(count, query) {
  const q = String(query ?? '').trim();
  const teams = `${count} ${count === 1 ? 'team' : 'teams'}`;
  if (!q) return `${teams} listed.`;
  return count ? `${teams} match “${q}”.` : `No teams match “${q}”.`;
}

/** Favourites with the primary team first (input order otherwise). */
export function orderFavourites(teams, primary) {
  const list = Array.isArray(teams) ? teams : [];
  if (!primary || !list.includes(primary)) return [...list];
  return [primary, ...list.filter((t) => t !== primary)];
}
