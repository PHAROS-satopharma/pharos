// case-intake — individual case reports (0059).
//   {action: "upload", file_name, data (base64), day_zero, ingredient_id?} → {case_id}
//       stores the document in the archive under sha256/ (never overwritten) and opens the case;
//   {action: "paper", document_id}          → {case_id}   opens a case from a literature paper;
//   {action: "read",  case_id, seen}        → {case_id}   reads the document again;
//   {action: "e2b",   case_id, seen}        → {case_id}   makes the E2B(R3) file of a confirmed case.
// The database functions run as the caller (a reviewer or an administrator), so the audit log names them. Then
// the GitHub repository_dispatch event 'case-read' (or 'case-e2b') starts .github/workflows/case-read.yml, which
// runs collectors/cases. Only the case id travels to GitHub. If GitHub cannot be reached the case still waits:
// the next collection run (within four hours) reads it, so the answer says {dispatched: false} and no error.
import { HttpError, json, readJson, serve } from "../_shared/cors.ts";
import { requirePerson } from "../_shared/auth.ts";
import { presignR2 } from "../archive-url/sigv4.ts";
import { sniff } from "./sniff.ts";

const MAX_BYTES = 10 * 1024 * 1024;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

interface Body {
  action?: string;
  file_name?: string;
  data?: string;
  day_zero?: string;
  ingredient_id?: string | null;
  document_id?: string;
  case_id?: string;
  seen?: string;
}

function uuidOf(v: unknown, what: string): string {
  const s = String(v ?? "").trim();
  if (!UUID_RE.test(s)) throw new HttpError(400, `The ${what} is not valid.`);
  return s;
}

function decodeBase64(data: string): Uint8Array<ArrayBuffer> {
  const clean = data.replace(/^data:[^,]*,/, "").replace(/\s+/g, "");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(clean)) throw new HttpError(400, "The file did not arrive whole. Try again.");
  if (clean.length > Math.ceil(MAX_BYTES / 3) * 4 + 4) throw new HttpError(413, "A case document is at most 10 MB.");
  const bin = atob(clean);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function sha256Hex(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Stores the original under sha256/<2>/<sha256>; an object already there is the same bytes and is left alone. */
async function archive(bytes: Uint8Array<ArrayBuffer>, sha: string, mime: string): Promise<void> {
  const accountId = Deno.env.get("R2_ACCOUNT_ID");
  const accessKeyId = Deno.env.get("R2_ACCESS_KEY_ID");
  const secretAccessKey = Deno.env.get("R2_SECRET_ACCESS_KEY");
  const bucket = Deno.env.get("R2_BUCKET");
  if (!accountId || !accessKeyId || !secretAccessKey || !bucket) {
    throw new HttpError(503, "The archive is not connected yet.");
  }
  const p = { accountId, accessKeyId, secretAccessKey, bucket, key: `sha256/${sha.slice(0, 2)}/${sha}`, expiresSeconds: 300 };
  const head = await fetch(await presignR2("HEAD", p), { method: "HEAD", signal: AbortSignal.timeout(15000) });
  if (head.ok) return;
  if (head.status !== 404) throw new HttpError(502, `The archive answered ${head.status}. Try again in a minute.`);
  const put = await fetch(await presignR2("PUT", p), {
    method: "PUT",
    // Only the host is signed, so no x-amz-* header may be sent (R2, like S3, refuses an unsigned one).
    headers: { "Content-Type": mime },
    body: bytes,
    signal: AbortSignal.timeout(60000),
  });
  if (!put.ok) {
    console.error("r2 put", put.status, await put.text().catch(() => ""));
    throw new HttpError(502, `The archive refused the file (HTTP ${put.status}). Try again in a minute.`);
  }
}

/** Fires the GitHub event; false when it could not (the next collection run picks the case up). */
async function dispatch(event: "case-read" | "case-e2b", caseId: string): Promise<boolean> {
  const token = Deno.env.get("GITHUB_DISPATCH_TOKEN");
  const repo = Deno.env.get("GITHUB_REPO");
  if (!token || !repo || !/^[\w.-]+\/[\w.-]+$/.test(repo)) return false;
  try {
    const res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pharos-cases",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ event_type: event, client_payload: { case_id: caseId } }),
      signal: AbortSignal.timeout(10000),
    });
    if (res.status !== 204) console.error("repository_dispatch", res.status, await res.text().catch(() => ""));
    return res.status === 204;
  } catch {
    return false;
  }
}

function dbError(error: { message?: string; code?: string } | null): never {
  const message = error?.message ?? "The case could not be saved.";
  const status = error?.code === "42501" ? 403 : error?.code === "PH409" ? 409 : error?.code === "23505" ? 409 : 400;
  throw new HttpError(status, message.replace(/^STALE_CASE:\s*/, ""));
}

serve(async (req) => {
  const caller = await requirePerson(req);
  if (caller.person.role === "reader") throw new HttpError(403, "Only a reviewer or an administrator can open a case.");
  const body = await readJson<Body>(req);
  const action = String(body.action ?? "");

  if (action === "upload") {
    const name = String(body.file_name ?? "").trim().slice(0, 200) || "document";
    const day = String(body.day_zero ?? "");
    if (!DAY_RE.test(day)) throw new HttpError(400, "Choose day zero: the day the company received the report.");
    const ingredient = body.ingredient_id ? uuidOf(body.ingredient_id, "ingredient") : null;
    const bytes = decodeBase64(String(body.data ?? ""));
    if (bytes.length === 0) throw new HttpError(400, "The file is empty.");
    if (bytes.length > MAX_BYTES) throw new HttpError(413, "A case document is at most 10 MB.");
    const mime = sniff(bytes, name);
    if (!mime) {
      throw new HttpError(415, "PHAROS reads PDF, photos (PNG, JPEG, GIF, WebP), Word (.docx), saved emails (.eml) and text files.");
    }
    const sha = await sha256Hex(bytes);
    await archive(bytes, sha, mime);
    const { data, error } = await caller.db.rpc("create_upload_case", {
      p_file_name: name, p_mime: mime, p_sha256: sha, p_bytes: bytes.length, p_day_zero: day, p_ingredient: ingredient,
    });
    if (error || !data) dbError(error);
    const caseId = String(data);
    return json(req, { case_id: caseId, dispatched: await dispatch("case-read", caseId) });
  }

  if (action === "paper") {
    const documentId = uuidOf(body.document_id, "paper");
    const { data, error } = await caller.db.rpc("create_paper_case", { p_document: documentId });
    if (error || !data) dbError(error);
    const caseId = String(data);
    return json(req, { case_id: caseId, dispatched: await dispatch("case-read", caseId) });
  }

  if (action === "read" || action === "e2b") {
    const caseId = uuidOf(body.case_id, "case");
    const seen = String(body.seen ?? "");
    if (!seen || Number.isNaN(Date.parse(seen))) throw new HttpError(400, "Reload the case and try again.");
    const fn = action === "read" ? "ask_case_read" : "ask_case_e2b";
    const { error } = await caller.db.rpc(fn, { p_case: caseId, p_seen: seen });
    if (error) dbError(error);
    return json(req, { case_id: caseId, dispatched: await dispatch(action === "read" ? "case-read" : "case-e2b", caseId) });
  }

  throw new HttpError(400, "Unknown action.");
});
