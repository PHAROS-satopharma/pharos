import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { supabase } from './supabase';
import { unwrap } from './api';
import type { Person, PersonRole } from './types';

interface AuthState {
  /** The stored session has been read. */
  ready: boolean;
  session: Session | null;
  person: Person | null;
  personLoading: boolean;
  personError: string | null;
  /** Your own person record could not be read at all (network or server error) — not the same as
   * "no active person": the screen offers a retry instead of saying the account is not active. */
  personFailed: boolean;
  /** Reading the person record again after a failure is in progress. */
  personRetrying: boolean;
  retryPerson: () => void;
  role: PersonRole | null;
  isAdmin: boolean;
  /** Admins and reviewers record decisions (Concerns us, Doesn't concern us). */
  canReview: boolean;
  signOut: () => Promise<void>;
  refreshPerson: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const qc = useQueryClient();

  useEffect(() => {
    let alive = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (!alive) return;
      setSession(data.session);
      setReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setReady(true);
    });
    return () => {
      alive = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const userId = session?.user.id ?? null;

  const personQ = useQuery({
    queryKey: ['me', userId],
    enabled: userId !== null,
    staleTime: 5 * 60_000,
    queryFn: async () =>
      unwrap<Person | null>(
        await supabase.from('person').select('*').eq('auth_user_id', userId ?? '').maybeSingle(),
      ),
  });

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    qc.clear();
  }, [qc]);

  const refreshPerson = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['me'] });
  }, [qc]);

  const { refetch: refetchPerson } = personQ;
  const retryPerson = useCallback(() => {
    void refetchPerson();
  }, [refetchPerson]);

  const value = useMemo<AuthState>(() => {
    const person = personQ.data ?? null;
    const role = person && person.active ? person.role : null;
    return {
      ready,
      session,
      person,
      personLoading: userId !== null && personQ.isPending,
      personError: personQ.error ? personQ.error.message : null,
      personFailed: userId !== null && personQ.isError && personQ.data === undefined,
      personRetrying: personQ.isError && personQ.isFetching,
      retryPerson,
      role,
      isAdmin: role === 'admin',
      canReview: role === 'admin' || role === 'reviewer',
      signOut,
      refreshPerson,
    };
  }, [
    ready,
    session,
    userId,
    personQ.data,
    personQ.isPending,
    personQ.isError,
    personQ.isFetching,
    personQ.error,
    signOut,
    refreshPerson,
    retryPerson,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
