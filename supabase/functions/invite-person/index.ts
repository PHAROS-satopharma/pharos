// invite-person — an admin gives a colleague access.
// {email, full_name, role} → {person_id}. Supabase Auth sends its invitation email (through the custom SMTP
// set up in docs/setup.md); the person row is written with the admin's own session, so the audit log names
// the admin who invited. If the person row cannot be written, the new sign-in is removed again.
import { HttpError, json, readJson, serve } from "../_shared/cors.ts";
import { requirePerson } from "../_shared/auth.ts";

const ROLES = ["admin", "reviewer", "reader"] as const;
type Role = (typeof ROLES)[number];

serve(async (req) => {
  const caller = await requirePerson(req, { admin: true, people: true });
  const body = await readJson<{ email?: string; full_name?: string; role?: string }>(req);

  const email = String(body.email ?? "").trim().toLowerCase();
  const fullName = String(body.full_name ?? "").trim().replace(/\s+/g, " ");
  const role = String(body.role ?? "reader") as Role;
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email) || email.length > 254) {
    throw new HttpError(400, "Type a valid email address.");
  }
  if (fullName.length < 2 || fullName.length > 200) throw new HttpError(400, "Type the person's full name.");
  if (!ROLES.includes(role)) throw new HttpError(400, "The role must be admin, reviewer or reader.");

  const { data: existing, error: exErr } = await caller.svc
    .from("person")
    .select("id, auth_user_id")
    .eq("email", email)
    .maybeSingle();
  if (exErr) throw new Error(`person lookup failed: ${exErr.message}`);
  if (existing?.auth_user_id) throw new HttpError(409, "This person already has access.");

  const siteUrl = Deno.env.get("SITE_URL") ?? undefined;
  const { data: invited, error: invErr } = await caller.svc.auth.admin.inviteUserByEmail(email, {
    redirectTo: siteUrl,
    data: { full_name: fullName },
  });
  if (invErr || !invited?.user) {
    const msg = invErr?.message ?? "";
    if (/already.*(registered|exists)/i.test(msg)) throw new HttpError(409, "This email address already has a sign-in.");
    console.error("inviteUserByEmail", msg);
    throw new HttpError(502, "The invitation email could not be sent. Check the email (SMTP) settings in Supabase.");
  }
  const authUserId = invited.user.id;

  const write = existing
    ? caller.db.from("person").update({ auth_user_id: authUserId, full_name: fullName, role, active: true })
      .eq("id", existing.id).select("id").single()
    : caller.db.from("person").insert({ auth_user_id: authUserId, full_name: fullName, email, role })
      .select("id").single();
  const { data: person, error: pErr } = await write;
  if (pErr || !person) {
    await caller.svc.auth.admin.deleteUser(authUserId).catch(() => undefined);
    console.error("person write", pErr?.message);
    throw new HttpError(500, "The person could not be saved, so the invitation was withdrawn. Try again.");
  }

  return json(req, { person_id: person.id });
});
