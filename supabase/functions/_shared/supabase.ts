// Supabase clients. SUPABASE_URL, SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY are injected by the
// Edge Runtime; never set them as function secrets.
import { createClient, type SupabaseClient } from "https://esm.sh/@supabase/supabase-js@2.117.3";

export type { SupabaseClient };

function env(name: string): string {
  const v = Deno.env.get(name);
  if (!v) throw new Error(`Missing environment variable ${name}`);
  return v;
}

const noSession = { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false };

/** Service-role client: bypasses row-level security. Use only after the caller has been checked. */
export function serviceClient(): SupabaseClient {
  return createClient(env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY"), { auth: noSession });
}

/** A client that acts as the signed-in person, so row-level security and the audit log see them. */
export function userClient(jwt: string): SupabaseClient {
  return createClient(env("SUPABASE_URL"), env("SUPABASE_ANON_KEY"), {
    auth: noSession,
    global: { headers: { Authorization: `Bearer ${jwt}` } },
  });
}
