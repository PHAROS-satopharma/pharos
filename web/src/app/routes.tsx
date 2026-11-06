import { useState, type ReactNode } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { mustChoosePassword, supabaseConfigured } from '../lib/supabase';
import { Layout } from './Layout';
import { SignIn } from '../features/signin/SignIn';
import { IngredientsPage } from '../features/ingredients/IngredientsPage';
import { IngredientScreen } from '../features/screen/IngredientScreen';
import { SourcesPage } from '../features/sources/SourcesPage';
import { PeoplePage } from '../features/people/PeoplePage';
import { MePage, PasswordForm } from '../features/me/MePage';
import { ReportsPage } from '../features/reports/ReportsPage';
import { CasesPage } from '../features/cases/CasesPage';
import { CaseView } from '../features/cases/CaseView';
import { Button } from '../ui/Button';
import { Empty, Loading } from '../ui/States';
import { PharosMark } from '../ui/PharosMark';
import { HOME, REMOVED_PATHS } from './nav';

function Bare({ children }: { children: ReactNode }) {
  return (
    <div className="bare">
      <PharosMark className="bare-logo" height={72} />
      {children}
    </div>
  );
}

function NotConfigured() {
  return (
    <Bare>
      <Empty title="This copy of PHAROS is not connected to its database.">
        <p>
          The build was made without <span className="mono">VITE_SUPABASE_URL</span> and{' '}
          <span className="mono">VITE_SUPABASE_ANON_KEY</span>. Set both in the Cloudflare Pages project and deploy again.
        </p>
      </Empty>
    </Bare>
  );
}

function NotInvited() {
  const { session, signOut, personError } = useAuth();
  return (
    <Bare>
      <Empty
        title="Your account is not active in PHAROS."
        action={<Button onClick={() => void signOut()}>Sign out</Button>}
      >
        <p>
          You are signed in as {session?.user.email ?? 'an unknown address'}, but no active person is linked to it.
          Access is by invitation only: ask an administrator to invite this address, or to switch your account back on.
        </p>
        {personError ? <p className="soft">Details: {personError}</p> : null}
      </Empty>
    </Bare>
  );
}

function CannotReach() {
  const { personError, personRetrying, retryPerson, signOut } = useAuth();
  return (
    <Bare>
      <Empty
        title="Could not reach PHAROS. Check the connection."
        action={
          <>
            <Button variant="primary" busy={personRetrying} onClick={retryPerson}>
              Retry
            </Button>{' '}
            <Button variant="quiet" onClick={() => void signOut()}>
              Sign out
            </Button>
          </>
        }
      >
        <p>Your account could not be loaded, so PHAROS cannot tell yet what you may see.</p>
        {personError ? <p className="soft">Details: {personError}</p> : null}
      </Empty>
    </Bare>
  );
}

function ChoosePassword({ onDone }: { onDone: () => void }) {
  const { session } = useAuth();
  return (
    <Bare>
      <Empty title="Choose your password.">
        <p>
          You opened PHAROS from an email link as {session?.user.email ?? 'your work email'}. Choose the password you
          will sign in with from now on.
        </p>
        <PasswordForm onDone={onDone} />
      </Empty>
    </Bare>
  );
}

function NotFound() {
  return (
    <Empty title="There is nothing at this address." action={<Link to="/">Back to Ingredients</Link>}>
      <p>The link may be old, or the page was moved.</p>
    </Empty>
  );
}

export function AppRoutes() {
  const { ready, session, person, personLoading, personFailed, managesPeople } = useAuth();
  const [choosePassword, setChoosePassword] = useState(mustChoosePassword);

  if (!supabaseConfigured) return <NotConfigured />;
  if (!ready) return <Loading label="Opening PHAROS" />;
  if (!session) return <SignIn />;
  if (personLoading) return <Loading label="Opening PHAROS" />;
  // A failed read is not an inactive account: say so, and offer to try again.
  if (personFailed) return <CannotReach />;
  if (!person || !person.active) return <NotInvited />;
  if (choosePassword) return <ChoosePassword onDone={() => setChoosePassword(false)} />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to={HOME} replace />} />
        <Route path="ingredients" element={<IngredientsPage />} />
        <Route path="ingredients/:id" element={<IngredientScreen />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:id" element={<CaseView />} />
        <Route path="people" element={managesPeople ? <PeoplePage /> : <Navigate to="/" replace />} />
        <Route path="me" element={<MePage />} />
        {/* The screens removed in November 2026: an old link opens Ingredients, never an empty page. */}
        {REMOVED_PATHS.map((p) => (
          <Route key={p} path={p} element={<Navigate to="/" replace />} />
        ))}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
