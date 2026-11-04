import { createClient } from '@supabase/supabase-js';

// Only the project origin: a pasted API address such as https://<ref>.supabase.co/rest/v1/ would send
// sign-in to /rest/v1/auth/v1/… ("Invalid path specified in request URL").
const url = (import.meta.env.VITE_SUPABASE_URL ?? '').trim().replace(/\/(rest|auth)\/v1\/?$/, '').replace(/\/+$/, '');
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

/** False when the build was made without the two Supabase variables; the app then says so plainly. */
export const supabaseConfigured = Boolean(url && anonKey);

// createClient throws on an empty URL, so an unconfigured build gets a placeholder it never calls.
export const supabase = createClient(url || 'http://localhost:54321', anonKey || 'not-configured', {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

export const telegramBotUsername = (import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? '').replace(/^@/, '');
