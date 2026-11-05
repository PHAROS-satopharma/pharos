import { Link, NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { ROLE_LABEL } from '../lib/labels';
import { useTheme } from '../lib/theme';
import { PharosMark } from '../ui/PharosMark';
import { cx } from '../ui/cx';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

const THEME_LABEL = { system: 'Theme: system', light: 'Theme: light', dark: 'Theme: dark' } as const;

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
            <NavLink to="/me" className={({ isActive }) => cx('who-name', isActive && 'is-active')}>
              <span>{person?.full_name ?? 'Me'}</span>
              {person ? <span className="who-role">{ROLE_LABEL[person.role]}</span> : null}
            </NavLink>
            <button type="button" className="bar-button" onClick={theme.cycle} title="Switch between system, light and dark">
              {THEME_LABEL[theme.choice]}
            </button>
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
