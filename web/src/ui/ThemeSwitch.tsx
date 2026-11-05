import { useTheme, type ThemeChoice } from '../lib/theme';
import { cx } from './cx';

const THEMES: { value: ThemeChoice; label: string; title: string }[] = [
  { value: 'light', label: 'Light', title: 'Navy masthead over a light page (the default)' },
  { value: 'dark', label: 'Dark', title: 'Always dark' },
  { value: 'system', label: 'Auto', title: 'Follow this device’s light or dark setting' },
];

/** Light / Dark / Auto: three words in one ruled box, the chosen one in navy. */
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
