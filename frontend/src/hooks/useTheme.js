import { useCallback, useEffect, useState } from 'react';
import { THEME_KEY, applyThemePref, normalizeThemePref, readThemePref, writeThemePref } from '../lib/theme.js';

const getStorage = () => window.localStorage;

/**
 * Theme preference ('system' | 'light' | 'dark') persisted in localStorage.
 * The inline script in index.html applied it before paint; changing it here
 * updates <html data-theme> immediately. Other tabs follow via storage events.
 */
export function useTheme() {
  const [pref, setPrefState] = useState(() => readThemePref(getStorage));

  const setPref = useCallback((next) => {
    const value = normalizeThemePref(next);
    writeThemePref(getStorage, value);
    applyThemePref(document.documentElement, value);
    setPrefState(value);
  }, []);

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key !== null && e.key !== THEME_KEY) return;
      const value = readThemePref(getStorage);
      applyThemePref(document.documentElement, value);
      setPrefState(value);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  return [pref, setPref];
}
