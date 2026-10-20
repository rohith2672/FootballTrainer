// Colour theme preference: 'system' follows prefers-color-scheme, 'light' and
// 'dark' pin the theme by setting data-theme on <html>. index.html applies the
// stored choice before first paint with an inline copy of applyThemePref.

export const THEME_KEY = 'ft.theme.v1';
export const THEME_PREFS = ['system', 'light', 'dark'];
export const THEME_LABELS = { system: 'System', light: 'Light', dark: 'Dark' };

/** Any stored value → a known preference ('system' when unknown). */
export function normalizeThemePref(value) {
  return THEME_PREFS.includes(value) ? value : 'system';
}

function resolveStorage(storage) {
  try {
    const value = typeof storage === 'function' ? storage() : storage;
    return value && typeof value.getItem === 'function' ? value : null;
  } catch {
    return null; // SecurityError when site data is blocked
  }
}

/** Stored preference; storage may be missing or throw. */
export function readThemePref(storage) {
  try {
    return normalizeThemePref(resolveStorage(storage)?.getItem(THEME_KEY));
  } catch {
    return 'system';
  }
}

/** Persist a preference ('system' clears the key). Returns false when storage failed. */
export function writeThemePref(storage, pref) {
  try {
    const store = resolveStorage(storage);
    if (!store) return false;
    const value = normalizeThemePref(pref);
    if (value === 'system') store.removeItem(THEME_KEY);
    else store.setItem(THEME_KEY, value);
    return true;
  } catch {
    return false; // quota exceeded or storage blocked
  }
}

/** The theme actually shown: an explicit choice, else the system setting. */
export function resolveTheme(pref, systemPrefersDark) {
  const value = normalizeThemePref(pref);
  if (value !== 'system') return value;
  return systemPrefersDark === false ? 'light' : 'dark';
}

/** data-theme value for a preference: null for 'system' (attribute removed). */
export function themeAttribute(pref) {
  const value = normalizeThemePref(pref);
  return value === 'system' ? null : value;
}

/** Set or remove data-theme on `root` (document.documentElement). */
export function applyThemePref(root, pref) {
  const attr = themeAttribute(pref);
  if (!root) return attr;
  if (attr) root.setAttribute('data-theme', attr);
  else root.removeAttribute('data-theme');
  return attr;
}
