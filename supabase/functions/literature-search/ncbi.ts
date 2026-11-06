// NCBI E-utilities for literature-search: one count per search and database, by publication date, exactly as
// the PubMed and PubMed Central websites count it. Checked on 6 November 2026 for levofloxacin, publication
// dates 1-31 October 2026: esearch gave PubMed 89 / PMC 357 for "levofloxacin", 233 / 475 for
// "fluoroquinolones" and 187 / 491 for "nonsteroidal anti-inflammatory", the same numbers both websites show for
// the links built below.

const EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi";
const contact = Deno.env.get("CONTACT_EMAIL");
const apiKey = Deno.env.get("NCBI_API_KEY");
const UA = `PHAROS/1.0 (pharmacovigilance screening aid${contact ? `; ${contact}` : ""})`;
/** NCBI allows 3 requests a second without an API key and 10 with one. */
export const GAP_MS = apiKey ? 110 : 350;
const RETRY_WAITS_MS = [1000, 3000];

export type Db = "pubmed" | "pmc";

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "2026-10-01" → the same string when it is a real calendar day, else null. */
export function parseDay(value: unknown): string | null {
  const m = DAY_RE.exec(String(value ?? "").trim());
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const t = new Date(Date.UTC(y, mo - 1, d));
  if (t.getUTCFullYear() !== y || t.getUTCMonth() !== mo - 1 || t.getUTCDate() !== d) return null;
  return m[0];
}

/** "2026-10-01" → "2026/10/01", NCBI's way of writing a day. */
export function ncbiDay(day: string): string {
  return day.replaceAll("-", "/");
}

/** The same search on the website: PubMed's publication-date filter, or PMC's [pdat] field. */
export function websiteUrl(db: Db, query: string, from: string, to: string): string {
  if (db === "pubmed") {
    return `https://pubmed.ncbi.nlm.nih.gov/?term=${encodeURIComponent(query)}` +
      `&filter=dates.${ncbiDay(from)}-${ncbiDay(to)}`;
  }
  // Never wrap the words in brackets: "(nonsteroidal anti-inflammatory) AND …" counts 492, not 491.
  return `https://pmc.ncbi.nlm.nih.gov/search/?term=` +
    encodeURIComponent(`${query} AND ${ncbiDay(from)}:${ncbiDay(to)}[pdat]`);
}

export function esearchUrl(db: Db, query: string, from: string, to: string): string {
  const p = new URLSearchParams({
    db,
    term: query,
    retmode: "json",
    retmax: "0",
    datetype: "pdat",
    mindate: ncbiDay(from),
    maxdate: ncbiDay(to),
    tool: "pharos",
  });
  if (contact) p.set("email", contact);
  if (apiKey) p.set("api_key", apiKey);
  return `${EUTILS}?${p.toString()}`;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** How many papers ``query`` finds in ``db`` among those published from…to. Waits out NCBI's passing errors
 * (HTTP 429 and 5xx, or HTTP 200 saying the search backend is down) twice before giving up. */
export async function count(db: Db, query: string, from: string, to: string): Promise<number> {
  let last = "";
  for (const wait of [0, ...RETRY_WAITS_MS]) {
    if (wait) await sleep(wait);
    let res: Response;
    try {
      res = await fetch(esearchUrl(db, query, from, to), {
        headers: { "User-Agent": UA, Accept: "application/json" },
        signal: AbortSignal.timeout(15000),
      });
    } catch (e) {
      last = e instanceof Error ? e.name : "network error";
      continue;
    }
    if (res.status === 429 || res.status >= 500) {
      last = `HTTP ${res.status}`;
      await res.body?.cancel();
      continue;
    }
    if (!res.ok) throw new Error(`NCBI answered HTTP ${res.status}`);
    const data = await res.json() as { esearchresult?: { count?: string; ERROR?: string } };
    const r = data?.esearchresult;
    if (r?.ERROR) {
      last = "search unavailable";
      continue;
    }
    const n = Number(r?.count);
    if (r?.count === undefined || !Number.isInteger(n) || n < 0) throw new Error("NCBI answer has no count");
    return n;
  }
  throw new Error(`NCBI did not answer (${last})`);
}

export const pause = () => sleep(GAP_MS);
