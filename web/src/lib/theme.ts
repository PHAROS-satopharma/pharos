import { useSyncExternalStore } from 'react';

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

// One choice for the whole page, so every switch (the top bar, My account) shows the same state.
let current: ThemeChoice = read();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function setTheme(next: ThemeChoice): void {
  current = next;
  apply(next);
  try {
    if (next === 'system') window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, next);
  } catch {
    // private window: the choice lasts for this visit only
  }
  listeners.forEach((l) => l());
}

/** Light or dark follows the system unless the person picks one; the pick is kept on this device. */
export function useTheme(): { choice: ThemeChoice; set: (next: ThemeChoice) => void; cycle: () => void } {
  const choice = useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  );
  return {
    choice,
    set: setTheme,
    cycle: () => setTheme(current === 'system' ? 'light' : current === 'light' ? 'dark' : 'system'),
  };
}
