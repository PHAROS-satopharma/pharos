import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { NewCount } from '../features/sources/NewCount';
import { useAuth } from '../lib/auth';
import { ROLE_LABEL } from '../lib/labels';
import { ErrorBoundary } from '../ui/ErrorBoundary';
import { Monogram } from '../ui/Monogram';
import { PharosMark } from '../ui/PharosMark';
import { SatoCopyright, SatoCredit } from '../ui/SatoCredit';
import { ThemeSwitch } from '../ui/ThemeSwitch';
import { cx } from '../ui/cx';
import { tabsFor } from './nav';
import '../styles/tabbar.css';

export function Layout() {
  const { person, isAdmin, signOut } = useAuth();
  const tabs = tabsFor(isAdmin);
  const { pathname } = useLocation();

  return (
    <div className="app">
      <a href="#main" className="skip">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" aria-label="PHAROS, home">
            <PharosMark height={50} />
          </Link>
          <nav className="nav" aria-label="Main">
            {tabs.map((t) => (
              <NavLink key={t.to} to={t.to} className={({ isActive }) => cx('nav-link', isActive && 'is-active')}>
                {t.label}
                {t.to === '/sources' ? <NewCount /> : null}
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
      {/* On a phone the same tabs sit at the foot of the screen, in reach of the thumb (tabbar.css). */}
      <nav className="tabbar" aria-label="Main">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => cx('tabbar-link', isActive && 'is-active')}>
            <span className="tabbar-label">{t.label}</span>
            {t.to === '/sources' ? <NewCount /> : null}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
