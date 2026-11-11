// Outside reference sources for ingredient lookup. Every call has a short timeout and fails soft: a source
// that does not answer becomes a warning, never an error, and never an automatic choice.
import { serviceClient } from "../_shared/supabase.ts";
import { key, similarity } from "./text.ts";

export const LANGS = ["en", "de", "fr", "it", "es", "pt", "nl", "da", "nb", "sv", "fi", "is", "ja", "ko", "ar"];
/** EU/EEA languages in LANGS: an EU-wide (centrally authorised) brand name is proposed in each of them. */
export const EEA_LANGS = ["en", "de", "fr", "it", "es", "pt", "nl", "da", "nb", "sv", "fi", "is"];

const contact = Deno.env.get("CONTACT_EMAIL");
const UA = `PHAROS/1.0 (pharmacovigilance screening aid${contact ? `; ${contact}` : ""})`;

async function getJson<T>(url: string, timeoutMs = 8000, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json", ...headers },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`${new URL(url).host} answered ${res.status}`);
  return (await res.json()) as T;
}

// ───────────────────────────── Wikidata ─────────────────────────────

export interface WikidataItem {
  qid: string;
  atc: string[];
  rxcui: string[];
  cid: string[];
  description: string | null;
  labels: Record<string, string>;
  alt: Record<string, string[]>;
  taxon: string[];              // a plant's scientific name (P225): "ivy" finds the plant Hedera helix
}

interface SearchHit { id: string; label?: string; description?: string }

export async function wikidataSearch(q: string, limit = 7): Promise<string[]> {
  const lang = /[぀-ヿ㐀-鿿]/.test(q)
    ? "ja"
    : /[가-힯]/.test(q)
    ? "ko"
    : /[؀-ۿ]/.test(q)
    ? "ar"
    : "en";
  const url = "https://www.wikidata.org/w/api.php?" + new URLSearchParams({
    action: "wbsearchentities",
    search: q,
    language: lang,
    uselang: "en",
    type: "item",
    limit: String(limit),
    format: "json",
  });
  const data = await getJson<{ search?: SearchHit[] }>(url);
  return (data.search ?? []).map((h) => h.id).filter((id) => /^Q\d+$/.test(id));
}

export async function wikidataByAtc(atc: string): Promise<string[]> {
  const query = `SELECT ?item WHERE { ?item wdt:P267 "${atc.replace(/[^A-Z0-9]/gi, "")}" } LIMIT 5`;
  const data = await sparql(query);
  return data.map((b) => qidOf(b.item?.value)).filter((x): x is string => !!x);
}

type Binding = Record<string, { value: string; "xml:lang"?: string } | undefined>;

async function sparql(query: string): Promise<Binding[]> {
  const url = "https://query.wikidata.org/sparql?" + new URLSearchParams({ query, format: "json" });
  const data = await getJson<{ results: { bindings: Binding[] } }>(url, 12000, {
    Accept: "application/sparql-results+json",
  });
  return data.results?.bindings ?? [];
}

function qidOf(uri: string | undefined): string | null {
  const m = uri?.match(/\/(Q\d+)$/);
  return m ? m[1] : null;
}

/** Labels and alternative labels in LANGS, plus ATC (P267), RxNorm CUI (P3345), PubChem CID (P662) and a
 *  plant's scientific name (P225). */
export async function wikidataDetails(qids: string[]): Promise<Map<string, WikidataItem>> {
  const out = new Map<string, WikidataItem>();
  const ids = [...new Set(qids)].filter((q) => /^Q\d+$/.test(q)).slice(0, 20);
  if (!ids.length) return out;
  const langs = LANGS.map((l) => `"${l}"`).join(",");
  const query = `
SELECT ?item ?kind ?val WHERE {
  VALUES ?item { ${ids.map((q) => `wd:${q}`).join(" ")} }
  { ?item wdt:P267 ?val . BIND("atc" AS ?kind) }
  UNION { ?item wdt:P3345 ?val . BIND("rxcui" AS ?kind) }
  UNION { ?item wdt:P662 ?val . BIND("cid" AS ?kind) }
  UNION { ?item wdt:P225 ?val . BIND("taxon" AS ?kind) }
  UNION { ?item rdfs:label ?val . FILTER(LANG(?val) IN (${langs})) BIND("label" AS ?kind) }
  UNION { ?item skos:altLabel ?val . FILTER(LANG(?val) IN (${langs})) BIND("alt" AS ?kind) }
  UNION { ?item schema:description ?val . FILTER(LANG(?val) = "en") BIND("desc" AS ?kind) }
}`;
  for (const b of await sparql(query)) {
    const qid = qidOf(b.item?.value);
    const kind = b.kind?.value;
    const val = b.val?.value;
    if (!qid || !kind || !val) continue;
    let it = out.get(qid);
    if (!it) {
      it = { qid, atc: [], rxcui: [], cid: [], description: null, labels: {}, alt: {}, taxon: [] };
      out.set(qid, it);
    }
    const lang = b.val?.["xml:lang"] ?? "";
    if (kind === "atc" && !it.atc.includes(val)) it.atc.push(val);
    else if (kind === "rxcui" && !it.rxcui.includes(val)) it.rxcui.push(val);
    else if (kind === "cid" && !it.cid.includes(val)) it.cid.push(val);
    else if (kind === "taxon" && !it.taxon.includes(val)) it.taxon.push(val);
    else if (kind === "desc") it.description = val;
    else if (kind === "label" && lang) it.labels[lang] = val;
    else if (kind === "alt" && lang) (it.alt[lang] ??= []).push(val);
  }
  return out;
}

// ───────────────────────────── EMA substance lists (cached per instance) ─────────────────────────────

export interface EmaSubstance {
  name: string;                 // as EMA writes it, e.g. "lornoxicam", "Ivy leaf"
  atc: Set<string>;
  lists: Set<string>;           // ema-psusa, ema-dhpc, ema-medicines, ema-herbal
  brands: Set<string>;          // centrally authorised medicine names (ema-medicines, ema-dhpc)
  herbal?: Herbal;              // an HMPC herbal substance (ema-herbal)
}

/** A herbal substance from EMA's HMPC list: "Ivy leaf" is Hederae helicis folium, from Hedera helix L. */
export interface Herbal {
  latin: string;                // Hederae helicis folium
  plants: string[];             // Hedera helix (the botanical names without their authors)
}

/** "Hedera helix L." → Hedera helix; "Fragaria vescaL.;Fragaria x ananassa (Weston) Duchesne" → both plants. */
export function botanicalNames(s: string | undefined): string[] {
  const out = new Set<string>();
  for (const part of (s ?? "").split(";")) {
    const w = part.trim().split(/\s+/);
    const hybrid = w[1] === "x" || w[1] === "×";
    const genus = w[0] ?? "";
    // the epithet, cut where an author's name is written against it ("vescaL." → vesca)
    const epithet = (hybrid ? w[2] : w[1])?.match(/^[a-z][a-z-]+/)?.[0] ?? "";
    if (!/^[A-Z][a-z]+$/.test(genus) || epithet.length < 3) continue;
    out.add(hybrid ? `${genus} x ${epithet}` : `${genus} ${epithet}`);
  }
  return [...out];
}

// Words that name a part of a plant or a preparation, never the herb: "ivy extract" is ivy, and "root" alone is
// no herb at all.
const PREPARATION_WORDS = new Set([
  "leaf", "leaves", "root", "roots", "herb", "herbs", "flower", "flowers", "fruit", "fruits", "seed", "seeds",
  "bark", "oil", "extract", "extracts", "dry", "dried", "liquid", "tincture", "syrup", "powder", "tea", "the",
  "and", "folium", "radix", "herba", "flos", "fructus", "semen", "cortex", "aetheroleum",
]);

function words(s: string): string[] {
  return s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().split(/[^\p{L}]+/u).filter((w) => w.length >= 3);
}

/** How well what was typed names a herbal substance: its closest name, or 0.8 when every word typed (leaving out
 *  the part and the preparation) is a word of its names: "ivy", "ivy extract" and "ivy syrup" all name Ivy leaf
 *  (11 November 2026). */
export function herbalMatch(q: string, s: EmaSubstance): number {
  const names = herbalNames(s);
  const best = Math.max(...names.map((n) => similarity(q, n)));
  if (!s.herbal) return best;
  const typed = words(q).filter((w) => !PREPARATION_WORDS.has(w));
  if (!typed.length) return best;
  const own = new Set(names.flatMap(words));
  return typed.every((w) => own.has(w)) ? Math.max(best, 0.8) : best;
}

/** Every name a herbal substance goes by: the common name (and its plural), the Latin name and the plants. */
export function herbalNames(s: EmaSubstance): string[] {
  if (!s.herbal) return [s.name];
  const plural = s.name.replace(/\bleaf$/i, (m) => (m[0] === "L" ? "Leaves" : "leaves"))
    .replace(/\b(root|flower|fruit|seed|herb)$/i, "$1s");
  return [...new Set([s.name, plural, s.herbal.latin, ...s.herbal.plants].filter(Boolean))];
}

const EMA = "https://www.ema.europa.eu/en/documents/report/";
const EMA_FILES = {
  "ema-psusa": EMA + "medicines-output-periodic_safety_update_report_single_assessments-output-json-report_en.json",
  "ema-dhpc": EMA + "dhpc-output-json-report_en.json",
  "ema-medicines": EMA + "medicines-output-medicines_json-report_en.json",
} as const;
// The HMPC herbal substances (ivy leaf, thyme, pelargonium …) are in none of the three lists above. EMA's site
// answers their file with "429 Too Many Requests" (11 November 2026), so the collection loads it once a day into
// herbal_substance (collectors/herbal.py, migration 0111) and the lookup reads it from there.
const HERBAL = "ema-herbal";
const EMA_TTL_MS = 12 * 3600 * 1000;
// A load where a list failed is kept only this long, so the next lookup soon tries that list again.
const EMA_RETRY_MS = 5 * 60 * 1000;

/** One row of herbal_substance: "Ivy leaf", "Hederae helicis folium", "Hedera helix L.". */
export interface HerbalRow {
  name: string;
  latin: string;
  botanical: string | null;
}

/** Put the herbal substances into the EMA index; a combination of several herbs is never one row there. */
export function addHerbals(index: Map<string, EmaSubstance>, rows: HerbalRow[]): void {
  for (const row of rows) {
    const name = row.name?.trim();
    const latin = row.latin?.trim();
    if (!name || !latin || name.length > 80) continue;
    const k = key(name);
    let s = index.get(k);
    if (!s) {
      s = { name, atc: new Set(), lists: new Set(), brands: new Set() };
      index.set(k, s);
    }
    s.lists.add(HERBAL);
    s.herbal = { latin, plants: botanicalNames(row.botanical ?? undefined) };
  }
}

async function herbalRows(): Promise<HerbalRow[]> {
  const { data, error } = await serviceClient().from("herbal_substance").select("name, latin, botanical");
  if (error) throw new Error(`herbal_substance: ${error.message}`);
  if (!data?.length) throw new Error("herbal_substance is empty");
  return data as HerbalRow[];
}

/** Where the herbal rows come from: the database; a test puts its own rows here, as it replaces fetch. */
export const herbalStore = { read: herbalRows };

let emaCache: { at: number; index: Map<string, EmaSubstance>; failed: string[] } | null = null;
let emaLoading: Promise<{ index: Map<string, EmaSubstance>; failed: string[] }> | null = null;

type Row = Record<string, string | undefined>;

function splitSubstances(s: string | undefined): string[] {
  return (s ?? "")
    .split(/;|\s\/\s/)
    .map((x) => x.trim())
    .filter((x) => x.length >= 3 && x.length <= 80);
}

export async function emaIndex(): Promise<{ index: Map<string, EmaSubstance>; failed: string[] }> {
  if (emaCache && Date.now() - emaCache.at < (emaCache.failed.length ? EMA_RETRY_MS : EMA_TTL_MS)) return emaCache;
  if (emaLoading) return emaLoading;
  emaLoading = (async () => {
    const index = new Map<string, EmaSubstance>();
    const failed: string[] = [];
    const add = (name: string, list: string, atc?: string, brand?: string) => {
      const k = key(name);
      let s = index.get(k);
      if (!s) {
        s = { name, atc: new Set(), lists: new Set(), brands: new Set() };
        index.set(k, s);
      }
      s.lists.add(list);
      if (atc && /^[A-Z]\d{2}[A-Z]{2}\d{2}$/.test(atc.trim())) s.atc.add(atc.trim());
      if (brand) s.brands.add(brand.trim());
    };
    const herbalLoad = Promise.allSettled([herbalStore.read()]);
    const results = await Promise.allSettled(
      Object.entries(EMA_FILES).map(async ([list, url]) => {
        const data = await getJson<{ data?: Row[] }>(url, 20000);
        return { list, rows: data.data ?? [] };
      }),
    );
    const [herbals] = await herbalLoad;
    results.forEach((r, i) => {
      const list = Object.keys(EMA_FILES)[i];
      if (r.status === "rejected") {
        failed.push(list);
        return;
      }
      for (const row of r.value.rows) {
        if (row.category && row.category !== "Human") continue;
        if (list === "ema-psusa") {
          for (const n of splitSubstances(row.active_substance)) add(n, list);
          for (const n of splitSubstances(row.active_substances_in_scope_of_procedure)) add(n, list);
        } else if (list === "ema-dhpc") {
          const subs = splitSubstances(row.active_substances);
          for (const n of subs) {
            add(n, list, subs.length === 1 ? row.atc_code_human : undefined, subs.length === 1 ? row.name_of_medicine : undefined);
          }
        } else {
          const inns = splitSubstances(row.international_non_proprietary_name_common_name);
          const single = inns.length === 1;
          for (const n of inns) add(n, list, single ? row.atc_code_human : undefined, single ? row.name_of_medicine : undefined);
          for (const n of splitSubstances(row.active_substance)) add(n, list, single ? row.atc_code_human : undefined);
        }
      }
    });
    if (herbals.status === "fulfilled") addHerbals(index, herbals.value);
    else {
      failed.push(HERBAL);
      console.warn(herbals.reason);
    }
    // A load where every EMA file failed is not kept; one where some failed is kept for EMA_RETRY_MS only.
    if (results.some((r) => r.status === "fulfilled")) emaCache = { at: Date.now(), index, failed };
    return { index, failed };
  })();
  try {
    return await emaLoading;
  } finally {
    emaLoading = null;
  }
}

// ───────────────────────────── RxNav (NLM) ─────────────────────────────

export interface RxName { name: string; rxcui: string | null }

/** Ingredient-level names RxNav suggests for a possibly misspelt query (approximate match + spelling). */
export async function rxnavSuggest(q: string): Promise<RxName[]> {
  const base = "https://rxnav.nlm.nih.gov/REST/";
  const [approx, spell] = await Promise.allSettled([
    getJson<{ approximateGroup?: { candidate?: { rxcui?: string; name?: string; source?: string }[] } }>(
      base + "approximateTerm.json?" + new URLSearchParams({ term: q, maxEntries: "25", option: "1" }),
    ),
    getJson<{ suggestionGroup?: { suggestionList?: { suggestion?: string[] } } }>(
      base + "spellingsuggestions.json?" + new URLSearchParams({ name: q }),
    ),
  ]);
  const out = new Map<string, RxName>();
  const ok = (n: string) => n.length <= 40 && !/\d|\//.test(n) && n.split(/\s+/).length <= 3 &&
    !/\b(oral|tablet|pill|injectable|product|capsule|topical|solution)\b/i.test(n);
  if (approx.status === "fulfilled") {
    for (const c of approx.value.approximateGroup?.candidate ?? []) {
      if (!c.name || !ok(c.name)) continue;
      const k = key(c.name);
      const prev = out.get(k);
      const rxcui = c.source === "RXNORM" ? c.rxcui ?? null : prev?.rxcui ?? null;
      out.set(k, { name: k, rxcui: rxcui ?? prev?.rxcui ?? null });
    }
  }
  if (spell.status === "fulfilled") {
    for (const s of spell.value.suggestionGroup?.suggestionList?.suggestion ?? []) {
      if (ok(s) && !out.has(key(s))) out.set(key(s), { name: key(s), rxcui: null });
    }
  }
  if (approx.status === "rejected" && spell.status === "rejected") throw approx.reason;
  return [...out.values()].slice(0, 8);
}

// ───────────────────────────── PubChem ─────────────────────────────

export async function pubchemAutocomplete(q: string): Promise<string[]> {
  const url = `https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound/${encodeURIComponent(q)}/json?limit=6`;
  const data = await getJson<{ dictionary_terms?: { compound?: string[] } }>(url, 6000);
  return data.dictionary_terms?.compound ?? [];
}

/** PubChem answers 404 for a name it has no compound for (a herb such as Ivy leaf): that is no synonyms, not a
 * failure, so the form does not say "PubChem did not answer" (8 November 2026). */
export async function pubchemSynonyms(name: string): Promise<string[]> {
  const url = `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/${encodeURIComponent(name)}/synonyms/JSON`;
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json" },
    signal: AbortSignal.timeout(8000),
  });
  if (res.status === 404) {
    await res.body?.cancel();
    return [];
  }
  if (!res.ok) throw new Error(`${new URL(url).host} answered ${res.status}`);
  const data = (await res.json()) as { InformationList?: { Information?: { Synonym?: string[] }[] } };
  return data.InformationList?.Information?.[0]?.Synonym ?? [];
}
