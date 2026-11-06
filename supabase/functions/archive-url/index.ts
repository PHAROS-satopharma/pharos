// archive-url — a 10-minute link to one archived original in R2.
// {r2_key} → {url}. Only for a signed-in person, and only for a key that a row they can read points to
// (document, attachment, SPC snapshot, inbound mail, weekly or monthly report, a pack made on request, EURD
// list). Database backups are never served.
import { HttpError, json, readJson, serve } from "../_shared/cors.ts";
import { requirePerson } from "../_shared/auth.ts";
import { presignR2Get } from "./sigv4.ts";

const KEY_RE = /^[A-Za-z0-9][A-Za-z0-9._\-\/]{0,510}$/;

serve(async (req) => {
  const caller = await requirePerson(req);
  const body = await readJson<{ r2_key?: string }>(req);
  const r2Key = String(body.r2_key ?? "").trim();
  if (!KEY_RE.test(r2Key) || r2Key.includes("..") || r2Key.includes("//")) {
    throw new HttpError(400, "That archive key is not valid.");
  }
  if (r2Key.startsWith("backups/")) throw new HttpError(403, "Backups cannot be downloaded from the app.");

  // Is the key referenced by something this person may read? (row-level security applies via caller.db)
  const db = caller.db;
  const checks = await Promise.all([
    db.from("document").select("id", { count: "exact", head: true }).eq("r2_key", r2Key),
    db.from("attachment").select("id", { count: "exact", head: true }).eq("r2_key", r2Key),
    db.from("spc_snapshot").select("id", { count: "exact", head: true }).eq("r2_key", r2Key),
    db.from("inbound_email").select("id", { count: "exact", head: true }).eq("r2_key", r2Key),
    db.from("monthly_report").select("id", { count: "exact", head: true }).eq("xlsx_r2_key", r2Key),
    db.from("monthly_report").select("id", { count: "exact", head: true }).eq("pdf_r2_key", r2Key),
    db.from("weekly_report").select("id", { count: "exact", head: true }).eq("xlsx_r2_key", r2Key),
    db.from("weekly_report").select("id", { count: "exact", head: true }).eq("pdf_r2_key", r2Key),
    // A PSUR or inspection pack made on request (0048, collectors/report_pack.py).
    db.from("report_request").select("id", { count: "exact", head: true }).eq("xlsx_r2_key", r2Key),
    db.from("report_request").select("id", { count: "exact", head: true }).eq("pdf_r2_key", r2Key),
    // EMA's EURD list as archived by collectors/eurd.py (0045: the readiness line reads its rows).
    db.from("eurd_entry").select("eurd_id", { count: "exact", head: true }).eq("r2_key", r2Key),
  ]);
  const known = checks.some((c) => !c.error && (c.count ?? 0) > 0);
  if (!known) throw new HttpError(404, "That file is not in the archive.");

  const accountId = Deno.env.get("R2_ACCOUNT_ID");
  const accessKeyId = Deno.env.get("R2_ACCESS_KEY_ID");
  const secretAccessKey = Deno.env.get("R2_SECRET_ACCESS_KEY");
  const bucket = Deno.env.get("R2_BUCKET");
  if (!accountId || !accessKeyId || !secretAccessKey || !bucket) {
    throw new HttpError(503, "The archive is not connected yet.");
  }

  const url = await presignR2Get({ accountId, accessKeyId, secretAccessKey, bucket, key: r2Key, expiresSeconds: 600 });
  return json(req, { url });
});
