// Who is calling: a signed-in, active person (and, when asked, an admin).
import { HttpError } from "./cors.ts";
import { serviceClient, userClient, type SupabaseClient } from "./supabase.ts";

export type Role = "admin" | "reviewer" | "reader";

export interface Caller {
  userId: string;
  person: { id: string; full_name: string; email: string | null; role: Role };
  jwt: string;
  /** Acts as the caller (row-level security applies). */
  db: SupabaseClient;
  /** Service role (bypasses row-level security). */
  svc: SupabaseClient;
}

export async function requirePerson(req: Request, opts: { admin?: boolean } = {}): Promise<Caller> {
  const header = req.headers.get("Authorization") ?? "";
  const m = header.match(/^Bearer\s+(.+)$/i);
  if (!m) throw new HttpError(401, "Sign in first.");
  const jwt = m[1].trim();

  const svc = serviceClient();
  const { data, error } = await svc.auth.getUser(jwt);
  if (error || !data?.user) throw new HttpError(401, "Your session has ended. Sign in again.");

  const { data: person, error: pErr } = await svc
    .from("person")
    .select("id, full_name, email, role")
    .eq("auth_user_id", data.user.id)
    .eq("active", true)
    .maybeSingle();
  if (pErr) throw new Error(`person lookup failed: ${pErr.message}`);
  if (!person) throw new HttpError(403, "Your account has no access to PHAROS.");
  if (opts.admin && person.role !== "admin") {
    throw new HttpError(403, "Only an administrator can do this.");
  }

  return { userId: data.user.id, person: person as Caller["person"], jwt, db: userClient(jwt), svc };
}
