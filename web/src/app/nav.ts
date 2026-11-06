/** One section of PHAROS: where it lives and the word on its tab. */
export interface Tab {
  to: string;
  label: string;
}

/**
 * The three screening tabs, in the order she works: one ingredient across every source (vertical), each
 * authority's new items (horizontal), then the weekly report. Everyone sees them.
 */
export const SCREENING_TABS: readonly Tab[] = [
  { to: '/ingredients', label: 'Ingredients' },
  { to: '/sources', label: 'Sources' },
  { to: '/reports', label: 'Reports' },
];

/** The tabs a person sees: the three screening tabs, and People (a setting) for the administrator who manages the
 *  people only (person.manages_people, migration 0053: Dr Sama is an administrator without it). */
export function tabsFor(managesPeople: boolean): Tab[] {
  return managesPeople ? [...SCREENING_TABS, { to: '/people', label: 'People' }] : [...SCREENING_TABS];
}

/** The page `/` opens. */
export const HOME = '/ingredients';

/**
 * Addresses of the screens removed in November 2026 (notifications, the notice page, signals, oversight,
 * PSUR, our labels). They open `/`, so an old bookmark or link never shows an empty page.
 * Each pattern also covers the addresses under it (`issue/*` takes `/issue/<id>`).
 */
export const REMOVED_PATHS: readonly string[] = [
  'notifications/*',
  'issues/*',
  'issue/*',
  'signals/*',
  'oversight/*',
  'psur/*',
  'labels/*',
];
