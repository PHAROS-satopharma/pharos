import { Link, NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { ROLE_LABEL } from '../lib/labels';
import { useTheme, type ThemeChoice } from '../lib/theme';
import { Monogram } from '../ui/Monogram';
import { PharosMark } from '../ui/PharosMark';
import { cx } from '../ui/cx';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

const THEMES: { value: ThemeChoice; label: string; title: string }[] = [
  { value: 'system', label: 'Auto', title: 'Follow this device’s light or dark setting' },
  { value: 'light', label: 'Light', title: 'Always light' },
  { value: 'dark', label: 'Dark', title: 'Always dark' },
];

export function Layout() {
  const { person, isAdmin, signOut } = useAuth();
  const theme = useTheme();
  const nav: NavItem[] = [
    { to: '/', label: 'Notifications', end: true },
    { to: '/ingredients', label: 'Ingredients' },
    { to: '/sources', label: 'Sources' },
    { to: '/reports', label: 'Reports' },
  ];
  if (isAdmin) nav.push({ to: '/people', label: 'People' });

  return (
    <div className="app">
      <a href="#main" className="skip">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label="PHAROS, home">
            <PharosMark height={46} />
          </Link>
          <nav className="nav" aria-label="Main">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) => cx('nav-link', isActive && 'is-active')}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="who">
            <NavLink
              to="/me"
              className={({ isActive }) => cx('who-name', isActive && 'is-active')}
              aria-label={`My account: ${person?.full_name ?? 'me'}`}
            >
              <Monogram name={person?.full_name ?? 'Me'} />
              <span className="who-text">
                <span className="who-person">{person?.full_name ?? 'Me'}</span>
                {person ? <span className="who-role">{ROLE_LABEL[person.role]}</span> : null}
              </span>
            </NavLink>
            <div className="theme-switch" role="group" aria-label="Light or dark">
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
            <button type="button" className="bar-button" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="footer">
        <div className="footer-inner">
          <span className="micro footer-mark">PHAROS · Pharmaceutical Alerts &amp; Regulatory Observation System</span>
          <span className="micro muted">Times in Cairo local · by Sato Pharma</span>
        </div>
      </footer>
    </div>
  );
}
