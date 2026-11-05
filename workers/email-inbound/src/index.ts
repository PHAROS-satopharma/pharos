// Cloudflare Email Worker for the PV mailbox aliases (fimea@, tga@ …) routed here by Email Routing.
// 1. Stores the raw message, unchanged, in R2 at inbound/<YYYY-MM-DD>/<uuid>.eml (the bucket lock keeps it).
// 2. Parses text and HTML with postal-mime.
// 3. Inserts an inbound_email row through Supabase REST with the service key; the email_inbox parser of the
//    collectors turns the newsletter into items and sets processed_at. As on the IMAP path, the From line
//    proves nothing by itself: the row carries its source only when the From domain is on that source's
//    SOURCE_DOMAINS list AND the receiving server's own Authentication-Results (mx.cloudflare.net, above
//    the hop where the message came in) shows DMARC, DKIM or SPF passing for it. Anything else is kept
//    with no source_id, which the parser never reads.
// 4. Optionally forwards a copy to the PV mailbox (FORWARD_TO, a verified Email Routing destination), so
//    people still see subscription confirmations.
import PostalMime from "postal-mime";

export interface Env {
  ARCHIVE: R2Bucket;
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  /** "fimea=fimea-email,tga=tga-email": recipient alias (local part) → source id. */
  ALIAS_SOURCES: string;
  /** "fimea-email=fimea.fi,tga-email=tga.gov.au|health.gov.au": the From domains each source accepts. */
  SOURCE_DOMAINS?: string;
  /** The receiving server whose Authentication-Results count (default mx.cloudflare.net). */
  AUTHSERV?: string;
  FORWARD_TO?: string;
}

type Header = { key: string; value: string };

function domainMatches(domain: string, allowed: string[]): boolean {
  const d = domain.toLowerCase().replace(/^\.+|\.+$/g, "");
  return allowed.some((a) => d === a || d.endsWith(`.${a}`));
}

function sourceDomains(spec: string | undefined, sourceId: string): string[] {
  for (const pair of (spec ?? "").split(",")) {
    const [source, domains] = pair.split("=").map((s) => s.trim().toLowerCase());
    if (source === sourceId && domains) return domains.split("|").map((d) => d.trim()).filter(Boolean);
  }
  return [];
}

function isPublicIp(ip: string): boolean {
  const v4 = ip.match(/^(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}$/);
  if (v4) {
    const [a, b] = [Number(v4[1]), Number(v4[2])];
    return !(a === 10 || a === 127 || a === 0 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127));
  }
  const v6 = ip.toLowerCase();
  return v6.includes(":") && !(v6 === "::1" || v6.startsWith("fc") || v6.startsWith("fd") || v6.startsWith("fe80"));
}

/** The receiving server's verdict passes for an allowed domain (the rules of collectors/core/imap_inbox.py). */
function senderVerified(headers: Header[], allowed: string[], authserv: string): boolean {
  const flat = headers.map((h) => ({ key: h.key.toLowerCase(), value: h.value.replace(/\s+/g, " ").trim() }));
  const top = flat.findIndex((h) => h.key === "authentication-results");
  if (top < 0 || !allowed.length) return false;
  // A header below the hop where the message came in from outside came with it: the sender wrote it.
  const entry = flat.findIndex((h) => h.key === "received"
    && [...h.value.split(" by ")[0].matchAll(/[[(](?:IPv6:)?([0-9A-Fa-f:.]{3,})[\])]/g)].some((m) => isPublicIp(m[1])));
  if (entry >= 0 && top > entry) return false;
  const [server, ...clauses] = flat[top].value.split(";");
  if (!domainMatches(server.trim().split(" ")[0] ?? "", [authserv])) return false;
  const keys: Record<string, string[]> = { dmarc: ["header.from"], dkim: ["header.d", "header.i"], spf: ["smtp.mailfrom"] };
  return clauses.some((clause) => {
    const m = clause.match(/(?<![\w.-])(dmarc|dkim|spf)\s*=\s*([a-z]+)/i);
    if (!m || m[2].toLowerCase() !== "pass") return false;
    return keys[m[1].toLowerCase()].some((k) => {
      const p = clause.match(new RegExp(`(?<![\\w.-])${k.replace(".", "\\.")}\\s*=\\s*([^\\s;()]+)`, "i"));
      const v = p?.[1].replace(/^[<"]+|[>"]+$/g, "").toLowerCase();
      return !!v && domainMatches(v.includes("@") ? v.split("@").pop()! : v, allowed);
    });
  });
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
    let verified = false;
    try {
      const parsed = await PostalMime.parse(raw);
      subject = parsed.subject ?? subject;
      text = parsed.text ?? null;
      html = parsed.html ?? null;
      from = (parsed.from as { address?: string } | undefined)?.address ?? from;
      const allowed = sourceDomains(env.SOURCE_DOMAINS, sourceId);
      verified = domainMatches(from.split("@").pop() ?? "", allowed)
        && senderVerified(parsed.headers as Header[], allowed, (env.AUTHSERV ?? "mx.cloudflare.net").toLowerCase());
    } catch (e) {
      // The raw message is safe in R2; the parser can re-read it from there.
      console.error("postal-mime failed", r2Key, String(e));
    }

    if (!verified) console.warn("sender not verified; kept without a source", r2Key);
    const row = {
      source_id: verified ? sourceId : null,
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
