import { createClient } from '@supabase/supabase-js';

// Only the project origin: a pasted API address such as https://<ref>.supabase.co/rest/v1/ would send
// sign-in to /rest/v1/auth/v1/… ("Invalid path specified in request URL").
const url = (import.meta.env.VITE_SUPABASE_URL ?? '').trim().replace(/\/(rest|auth)\/v1\/?$/, '').replace(/\/+$/, '');
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

/** False when the build was made without the two Supabase variables; the app then says so plainly. */
export const supabaseConfigured = Boolean(url && anonKey);

// An invitation or password-reset link signs the person in without a password. Note it before the client
// reads (and clears) the link's #type=…, so the app can ask for a password first.
const CHOOSE_PASSWORD = 'pharos-choose-password';
try {
  const linkType = new URLSearchParams(window.location.hash.slice(1)).get('type');
  if (linkType === 'invite' || linkType === 'recovery') window.sessionStorage.setItem(CHOOSE_PASSWORD, '1');
} catch {
  // No session storage (private window): the person can still set a password under My account.
}

export function mustChoosePassword(): boolean {
  try {
    return window.sessionStorage.getItem(CHOOSE_PASSWORD) === '1';
  } catch {
    return false;
  }
}

export function passwordChosen(): void {
  try {
    window.sessionStorage.removeItem(CHOOSE_PASSWORD);
  } catch {
    // Nothing stored.
  }
}

// createClient throws on an empty URL, so an unconfigured build gets a placeholder it never calls.
export const supabase = createClient(url || 'http://localhost:54321', anonKey || 'not-configured', {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

export const telegramBotUsername = (import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? '').replace(/^@/, '');
