import { useCallback, useState } from 'react';

export type ThemeChoice = 'system' | 'light' | 'dark';

const KEY = 'pharos-theme';

function read(): ThemeChoice {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

function apply(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

function keep(choice: ThemeChoice): void {
  apply(choice);
  try {
    if (choice === 'system') window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, choice);
  } catch {
    // private window: the choice lasts for this visit only
  }
}

/** Light or dark follows the system unless the person picks one; the pick is kept on this device. */
export function useTheme(): { choice: ThemeChoice; set: (next: ThemeChoice) => void; cycle: () => void } {
  const [choice, setChoice] = useState<ThemeChoice>(read);
  const set = useCallback((next: ThemeChoice) => {
    keep(next);
    setChoice(next);
  }, []);
  const cycle = useCallback(() => {
    setChoice((c) => {
      const next: ThemeChoice = c === 'system' ? 'light' : c === 'light' ? 'dark' : 'system';
      keep(next);
      return next;
    });
  }, []);
  return { choice, set, cycle };
}
