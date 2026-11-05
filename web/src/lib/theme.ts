import { useSyncExternalStore } from 'react';

export type ThemeChoice = 'system' | 'light' | 'dark';

const KEY = 'pharos-theme';

function read(): ThemeChoice {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === 'dark' || v === 'system' ? v : 'light';
  } catch {
    return 'light';
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
    window.localStorage.setItem(KEY, next);
  } catch {
    // private window: the choice lasts for this visit only
  }
  listeners.forEach((l) => l());
}

/** Light (navy masthead over a light page) unless the person picks Dark or Auto; the pick is kept on this device. */
export function useTheme(): { choice: ThemeChoice; set: (next: ThemeChoice) => void; cycle: () => void } {
  const choice = useSyncExternalStore(
    subscribe,
    () => current,
    () => current,
  );
  return {
    choice,
    set: setTheme,
    cycle: () => setTheme(current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light'),
  };
}
