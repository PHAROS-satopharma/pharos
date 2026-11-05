import { useTheme, type ThemeChoice } from '../lib/theme';
import { cx } from './cx';

const THEMES: { value: ThemeChoice; label: string; title: string }[] = [
  { value: 'system', label: 'Auto', title: 'Follow this device’s light or dark setting' },
  { value: 'light', label: 'Light', title: 'Always light' },
  { value: 'dark', label: 'Dark', title: 'Always dark' },
];

/** Auto / Light / Dark: three words in one ruled box, the chosen one in navy. */
export function ThemeSwitch({ className }: { className?: string }) {
  const theme = useTheme();
  return (
    <div className={cx('theme-switch', className)} role="group" aria-label="Light or dark">
      {THEMES.map((t) => (
        <button
          key={t.value}
          type="button"
          aria-pressed={theme.choice === t.value}
          title={t.title}
          onClick={() => theme.set(t.value)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
