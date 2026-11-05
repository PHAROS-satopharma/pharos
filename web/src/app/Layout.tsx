import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { ROLE_LABEL } from '../lib/labels';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { Monogram } from '../ui/Monogram';
import { PharosMark } from '../ui/PharosMark';
import { SatoCopyright, SatoCredit } from '../ui/SatoCredit';
import { ThemeSwitch } from '../ui/ThemeSwitch';
import { cx } from '../ui/cx';

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

export function Layout() {
  const { person, isAdmin, signOut } = useAuth();
  const nav: NavItem[] = [
    { to: '/', label: 'Notifications', end: true },
    { to: '/signals', label: 'Signals' },
    { to: '/ingredients', label: 'Ingredients' },
    { to: '/sources', label: 'Sources' },
    { to: '/reports', label: 'Reports' },
  ];
  if (isAdmin) nav.push({ to: '/people', label: 'People' });

  // On a phone the sections fold behind a Menu button; any move to another page folds them again.
  const { pathname } = useLocation();
  const [openOn, setOpenOn] = useState<string | null>(null);
  const menuOpen = openOn === pathname;
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenOn(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);

  return (
    <div className="app">
      <a href="#main" className="skip">
        Skip to content
      </a>
      <header className={cx('topbar', menuOpen && 'is-menu-open')}>
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label="PHAROS, home">
            <PharosMark height={50} />
          </Link>
          <nav id="main-nav" className="nav" aria-label="Main">
            {nav.map((n, i) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) => cx('nav-link', isActive && 'is-active')}
              >
                <span className="nav-index" aria-hidden="true">
                  {String(i + 1).padStart(2, '0')}
                </span>
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
            <ThemeSwitch className="bar-only" />
            <button type="button" className="bar-button bar-only" onClick={() => void signOut()}>
              Sign out
            </button>
            <button
              type="button"
              className="menu-button"
              aria-expanded={menuOpen}
              aria-controls="main-nav"
              onClick={() => setOpenOn(menuOpen ? null : pathname)}
            >
              <span className="menu-icon" aria-hidden="true" />
              {menuOpen ? 'Close' : 'Menu'}
            </button>
          </div>
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        {/* A page that fails to render keeps the header and footer; moving to another page starts fresh. */}
        <ErrorBoundary key={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
      <footer className="footer">
        <div className="footer-inner">
          <span className="micro footer-mark">PHAROS · Pharmaceutical Alerts &amp; Regulatory Observation System</span>
          <SatoCredit tone="reverse" />
        </div>
        <div className="footer-base">
          <SatoCopyright />
          <span className="micro">All times are Cairo local time</span>
        </div>
      </footer>
    </div>
  );
}
