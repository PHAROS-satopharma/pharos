// Cloudflare Email Worker for the PV mailbox aliases (fimea@, tga@ …) routed here by Email Routing.
// 1. Stores the raw message, unchanged, in R2 at inbound/<YYYY-MM-DD>/<uuid>.eml (the bucket lock keeps it).
// 2. Parses text and HTML with postal-mime.
// 3. Inserts an inbound_email row through Supabase REST with the service key; the email_inbox parser of the
//    collectors turns the newsletter into items and sets processed_at.
// 4. Optionally forwards a copy to the PV mailbox (FORWARD_TO, a verified Email Routing destination), so
//    people still see subscription confirmations.
import PostalMime from "postal-mime";

export interface Env {
  ARCHIVE: R2Bucket;
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  /** "fimea=fimea-email,tga=tga-email": recipient alias (local part) → source id. */
  ALIAS_SOURCES: string;
  FORWARD_TO?: string;
}

function aliasMap(spec: string): Map<string, string> {
  const m = new Map<string, string>();
  for (const pair of (spec ?? "").split(",")) {
    const [alias, source] = pair.split("=").map((s) => s.trim().toLowerCase());
    if (alias && source) m.set(alias, source);
  }
  return m;
}

function restHeaders(env: Env): Record<string, string> {
  const key = env.SUPABASE_SERVICE_ROLE_KEY;
  const h: Record<string, string> = {
    apikey: key,
    "Content-Type": "application/json",
    Prefer: "return=minimal",
  };
  // A legacy service_role key is a JWT and also goes in Authorization; a new sb_secret_ key goes in apikey only.
  if (key.startsWith("eyJ")) h.Authorization = `Bearer ${key}`;
  return h;
}

async function insertRow(env: Env, row: Record<string, unknown>): Promise<Response> {
  return await fetch(`${env.SUPABASE_URL.replace(/\/$/, "")}/rest/v1/inbound_email`, {
    method: "POST",
    headers: restHeaders(env),
    body: JSON.stringify(row),
  });
}

const MAX_BODY_CHARS = 2_000_000;

export default {
  async email(message: ForwardableEmailMessage, env: Env, _ctx: ExecutionContext): Promise<void> {
    const to = message.to.toLowerCase();
    const alias = to.split("@")[0].split("+")[0];
    const sourceId = aliasMap(env.ALIAS_SOURCES).get(alias);
    if (!sourceId) {
      message.setReject("Unknown recipient");
      return;
    }

    const raw = await new Response(message.raw).arrayBuffer();
    const now = new Date();
    const r2Key = `inbound/${now.toISOString().slice(0, 10)}/${crypto.randomUUID()}.eml`;
    await env.ARCHIVE.put(r2Key, raw, {
      httpMetadata: { contentType: "message/rfc822" },
      customMetadata: { to, from: message.from, source_id: sourceId },
    });

    let subject: string | null = message.headers.get("subject");
    let text: string | null = null;
    let html: string | null = null;
    let from = message.from;
    try {
      const parsed = await PostalMime.parse(raw);
      subject = parsed.subject ?? subject;
      text = parsed.text ?? null;
      html = parsed.html ?? null;
      from = (parsed.from as { address?: string } | undefined)?.address ?? from;
    } catch (e) {
      // The raw message is safe in R2; the parser can re-read it from there.
      console.error("postal-mime failed", r2Key, String(e));
    }

    const row = {
      source_id: sourceId,
      received_at: now.toISOString(),
      from_addr: from,
      subject,
      r2_key: r2Key,
      text_body: text ? text.slice(0, MAX_BODY_CHARS) : null,
      html_body: html ? html.slice(0, MAX_BODY_CHARS) : null,
    };
    let res = await insertRow(env, row);
    if (res.status === 409 || res.status === 400) {
      // 23503: the source row does not exist yet (collectors not synced). Keep the mail without it.
      const detail = await res.text();
      if (detail.includes("23503")) res = await insertRow(env, { ...row, source_id: null });
      else console.error("inbound_email insert refused", res.status, detail.slice(0, 500));
    }
    if (!res.ok) {
      // Throwing makes Email Routing report a temporary failure; the raw message is already in R2.
      throw new Error(`inbound_email insert failed: HTTP ${res.status} (${r2Key})`);
    }

    if (env.FORWARD_TO) {
      try {
        await message.forward(env.FORWARD_TO);
      } catch (e) {
        console.error("forward failed", String(e));
      }
    }
  },
};
