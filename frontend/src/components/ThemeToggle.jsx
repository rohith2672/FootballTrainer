import { useTheme } from '../hooks/useTheme';
import { THEME_LABELS, THEME_PREFS } from '../lib/theme.js';
import { MonitorIcon, MoonIcon, SunIcon } from './icons';

const ICONS = { system: MonitorIcon, light: SunIcon, dark: MoonIcon };

/** System / Light / Dark switch; the pressed button is the current preference. */
function ThemeToggle() {
  const [pref, setPref] = useTheme();
  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {THEME_PREFS.map((value) => {
        const Icon = ICONS[value];
        return (
          <button
            key={value}
            type="button"
            className={`theme-btn ${pref === value ? 'active' : ''}`}
            aria-pressed={pref === value}
            title={`${THEME_LABELS[value]} theme`}
            onClick={() => setPref(value)}
          >
            <Icon size={18} />
            <span className="sr-only">{THEME_LABELS[value]}</span>
          </button>
        );
      })}
    </div>
  );
}

export default ThemeToggle;
