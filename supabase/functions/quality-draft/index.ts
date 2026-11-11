// PHAROS — ask for a drafted root cause and CAPA (migration 0109). A reviewer or an administrator, signed in, asks
// on a deviation or an audit observation; quality_draft_ask() (as that person) records the ask, then the GitHub
// repository_dispatch event 'quality-draft' starts .github/workflows/quality-draft.yml with only the draft's id.
// Without the dispatch settings (GITHUB_DISPATCH_TOKEN, GITHUB_REPO, the same ones case-intake uses) the next
// 4-hourly collection drafts it, so the answer says {dispatched: false} and no error.
import { HttpError, json, readJson, serve } from "../_shared/cors.ts";
import { requirePerson } from "../_shared/auth.ts";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Body {
  kind?: string;
  id?: string;
}

async function dispatch(draftId: string): Promise<boolean> {
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
        "User-Agent": "pharos-quality",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ event_type: "quality-draft", client_payload: { draft_id: draftId } }),
      signal: AbortSignal.timeout(10000),
    });
    if (res.status !== 204) console.error("repository_dispatch", res.status, await res.text().catch(() => ""));
    return res.status === 204;
  } catch {
    return false;
  }
}

serve(async (req) => {
  const caller = await requirePerson(req);
  if (caller.person.role === "reader") {
    throw new HttpError(403, "Only a reviewer or an administrator can ask for a draft.");
  }
  const body = await readJson<Body>(req);
  const kind = String(body.kind ?? "");
  if (kind !== "deviation" && kind !== "observation") {
    throw new HttpError(400, "A draft is for a deviation or an audit observation.");
  }
  const id = String(body.id ?? "").trim();
  if (!UUID_RE.test(id)) throw new HttpError(400, "The record is not valid.");
  const { data, error } = await caller.db.rpc("quality_draft_ask", { p_kind: kind, p_id: id });
  if (error || !data) {
    const status = error?.code === "42501" ? 403 : 400;
    throw new HttpError(status, error?.message ?? "The draft could not be asked for.");
  }
  const draftId = String(data);
  return json(req, { draft_id: draftId, dispatched: await dispatch(draftId) });
});
