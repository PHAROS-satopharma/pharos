import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

/** False when the build was made without the two Supabase variables; the app then says so plainly. */
export const supabaseConfigured = Boolean(url && anonKey);

// createClient throws on an empty URL, so an unconfigured build gets a placeholder it never calls.
export const supabase = createClient(url || 'http://localhost:54321', anonKey || 'not-configured', {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});

export const telegramBotUsername = (import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? '').replace(/^@/, '');
