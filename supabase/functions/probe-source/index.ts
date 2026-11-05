// probe-source — an admin's "test link" for a new source.
// {url} → {probe_id}. Queues a probe_result row (as the admin, so the audit is truthful) and fires the
// GitHub repository_dispatch event 'probe'; probe.yml runs the same Python parsers and fills the row in.
// The web app polls probe_result by id. Only the id travels to GitHub, never the URL.
import { HttpError, json, readJson, serve } from "../_shared/cors.ts";
import { requirePerson } from "../_shared/auth.ts";

function checkUrl(raw: string): string {
  let u: URL;
  try {
    u = new URL(raw.trim());
  } catch {
    throw new HttpError(400, "That is not a web address.");
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") throw new HttpError(400, "Only http and https addresses can be probed.");
  if (u.username || u.password) throw new HttpError(400, "Addresses with a user name or password cannot be probed.");
  const h = u.hostname.toLowerCase();
  // A first quick refusal only: URL() already turns 2130706433 / 0x7f.1 / 127.1 into 127.0.0.1. The
  // collector checks what every host (and every redirect) really resolves to before it connects.
  const privateHost = h === "localhost" || h.endsWith(".localhost") || h.endsWith(".local") ||
    h.endsWith(".internal") ||
    /^(127\.|10\.|192\.168\.|169\.254\.|0\.)/.test(h) || /^172\.(1[6-9]|2\d|3[01])\./.test(h) ||
    /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(h) || /^(22[4-9]|2[3-5]\d)\./.test(h) ||
    h.startsWith("[") || !h.includes(".");
  if (privateHost) throw new HttpError(400, "Only public regulator websites can be probed.");
  if (u.href.length > 2000) throw new HttpError(400, "That address is too long.");
  return u.href;
}

serve(async (req) => {
  const caller = await requirePerson(req, { admin: true });
  const body = await readJson<{ url?: string }>(req);
  const url = checkUrl(String(body.url ?? ""));

  const { data: row, error } = await caller.db
    .from("probe_result")
    .insert({ url, requested_by: caller.person.id, status: "queued" })
    .select("id")
    .single();
  if (error || !row) throw new Error(`probe_result insert failed: ${error?.message}`);
  const probeId = row.id as string;

  const token = Deno.env.get("GITHUB_DISPATCH_TOKEN");
  const repo = Deno.env.get("GITHUB_REPO");
  const fail = async (message: string) => {
    await caller.svc.from("probe_result")
      .update({ status: "failed", error: message, finished_at: new Date().toISOString() })
      .eq("id", probeId);
    throw new HttpError(502, message);
  };
  if (!token || !repo || !/^[\w.-]+\/[\w.-]+$/.test(repo)) {
    await fail("The probe is not set up yet (GitHub dispatch token or repository missing).");
  }

  let res: Response;
  try {
    res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pharos-probe",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ event_type: "probe", client_payload: { probe_id: probeId } }),
      signal: AbortSignal.timeout(10000),
    });
  } catch {
    return await fail("GitHub could not be reached. Try again in a minute.");
  }
  if (res.status !== 204) {
    console.error("repository_dispatch", res.status, await res.text().catch(() => ""));
    await fail(`GitHub refused the probe (HTTP ${res.status}).`);
  }

  return json(req, { probe_id: probeId });
});
