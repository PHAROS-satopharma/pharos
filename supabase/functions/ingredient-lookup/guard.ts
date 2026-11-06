// Names that belong to another substance never reach the proposal (6 November 2026: Wikidata gave levofloxacin
// the names "Ofloxacin" and "Floxin", and the EMA ofloxacin PSUSA was linked to levofloxacin; guaifenesin got
// ペントキシベリン, paracetamol "Canada og Japan"). Every proposed synonym and brand from Wikidata or PubChem is
// checked against the identity of the ingredient itself:
//   * Wikidata: a name that is the label or alias of ANOTHER item that is a substance (an RxNorm id or a CAS
//     number) of a different RxNorm ingredient, a medicine whose active ingredients are all other substances,
//     or a disambiguation page (the name is ambiguous);
//   * RxNorm: an English name RxNav resolves to ingredients that are all different from the ingredient's own.
// A form of the substance (a salt that is a subclass of it, or one with the same RxNorm ingredient) and a
// medicine that contains it pass. A check that cannot be made is reported, never silently passed.
import { key } from "./text.ts";

const contact = Deno.env.get("CONTACT_EMAIL");
const UA = `PHAROS/1.0 (pharmacovigilance screening aid${contact ? `; ${contact}` : ""})`;
const DISAMBIGUATION = "Q4167410";

export interface Candidate { term: string; lang: string }
export interface Own { qid: string | null; rxcui: string[]; inn: string }

/** A chemical formula (C9H13NO2) names no single substance. */
export function isFormula(s: string): boolean {
  return /^C\d*H\d*(?:[A-Z][a-z]?\d*)*$/.test(s.trim()) && /\d/.test(s);
}

/** A name of several words must contain one of the substance's own names ("Canada og Japan" does not). */
export function namesTheSubstance(alias: string, names: string[]): boolean {
  const a = key(alias);
  if (!/\s/.test(a)) return true;
  const own = names.map(key).filter((n) => n.length >= 4);
  const words = new Set(a.split(/[\s\-/]+/));
  return own.some((n) => words.has(n) || a.includes(n));
}

interface Init { method?: string; headers?: Record<string, string>; body?: URLSearchParams }

async function fetchJson<T>(url: string, init: Init = {}, timeoutMs = 10000): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "User-Agent": UA, Accept: "application/json", ...(init.headers ?? {}) },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`${new URL(url).host} answered ${res.status}`);
  return (await res.json()) as T;
}

type Binding = Record<string, { value: string } | undefined>;
const qidOf = (uri?: string) => uri?.match(/\/(Q\d+)$/)?.[1] ?? null;
const literal = (s: string, lang: string) => `"${s.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"@${lang}`;

function variants(s: string): string[] {
  const t = s.trim();
  return [...new Set([t, t.toLowerCase(), t.charAt(0).toUpperCase() + t.slice(1).toLowerCase()])];
}

interface Other {
  label: string | null;
  rx: Set<string>;
  substance: boolean;
  formOf: boolean;
  disambiguation: boolean;
  ingredients: Map<string, { label: string | null; rx: Set<string>; formOf: boolean }>;
}

/** Wikidata: the candidates that are names of another item, with why. */
async function wikidataOthers(cands: Candidate[], own: Own): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  if (!own.qid || !cands.length) return out;
  const values = new Set<string>();
  for (const c of cands) {
    for (const v of variants(c.term)) {
      values.add(literal(v, c.lang));
      values.add(literal(v, "mul"));
    }
  }
  const query = `
SELECT ?val ?other ?otherLabel ?rx ?cas ?sup ?p31 ?ing ?ingLabel ?irx ?isup WHERE {
  VALUES ?val { ${[...values].join(" ")} }
  { ?other rdfs:label ?val } UNION { ?other skos:altLabel ?val }
  FILTER(?other != wd:${own.qid})
  OPTIONAL { ?other wdt:P3345 ?rx }
  OPTIONAL { ?other wdt:P231 ?cas }
  OPTIONAL { ?other wdt:P279 ?sup }
  OPTIONAL { ?other wdt:P31 ?p31 }
  OPTIONAL { ?other wdt:P3781 ?ing .
             OPTIONAL { ?ing wdt:P3345 ?irx } OPTIONAL { ?ing wdt:P279 ?isup }
             OPTIONAL { ?ing rdfs:label ?ingLabel FILTER(LANG(?ingLabel) = "en") } }
  OPTIONAL { ?other rdfs:label ?otherLabel FILTER(LANG(?otherLabel) = "en") }
} LIMIT 5000`;
  const data = await fetchJson<{ results: { bindings: Binding[] } }>("https://query.wikidata.org/sparql", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/sparql-results+json" },
    body: new URLSearchParams({ query, format: "json" }),
  }, 15000);
  const byName = new Map<string, Map<string, Other>>();
  for (const b of data.results?.bindings ?? []) {
    const name = b.val?.value;
    const qid = qidOf(b.other?.value);
    if (!name || !qid) continue;
    const others = byName.get(key(name)) ?? new Map<string, Other>();
    byName.set(key(name), others);
    let o = others.get(qid);
    if (!o) {
      o = { label: null, rx: new Set(), substance: false, formOf: false, disambiguation: false, ingredients: new Map() };
      others.set(qid, o);
    }
    if (b.otherLabel?.value) o.label = b.otherLabel.value;
    if (b.rx?.value) o.rx.add(b.rx.value);
    if (b.rx?.value || b.cas?.value) o.substance = true;
    if (qidOf(b.sup?.value) === own.qid) o.formOf = true;
    if (qidOf(b.p31?.value) === DISAMBIGUATION) o.disambiguation = true;
    const ing = qidOf(b.ing?.value);
    if (ing) {
      const i = o.ingredients.get(ing) ?? { label: null, rx: new Set<string>(), formOf: false };
      if (b.ingLabel?.value) i.label = b.ingLabel.value;
      if (b.irx?.value) i.rx.add(b.irx.value);
      if (ing === own.qid || qidOf(b.isup?.value) === own.qid) i.formOf = true;
      o.ingredients.set(ing, i);
    }
  }
  const sameRx = (rx: Set<string>) => own.rxcui.some((r) => rx.has(r));
  // a salt or other form whose English name contains the INN ("ivabradine hydrochloride") is the substance
  const inn = key(own.inn);
  const named = (label: string | null) => !!inn && inn.length >= 4 && !!label && key(label).includes(inn);
  for (const [name, others] of byName) {
    for (const [qid, o] of others) {
      let why: string | null = null;
      if (o.ingredients.size) {
        const ours = [...o.ingredients.entries()]
          .some(([q, i]) => q === own.qid || i.formOf || sameRx(i.rx) || named(i.label));
        if (!ours) {
          const names = [...o.ingredients.values()].map((i) => i.label).filter(Boolean).join(", ");
          why = `a medicine of ${names || "another substance"}`;
        }
      } else if (o.substance && !o.formOf && !sameRx(o.rx) && !named(o.label)) {
        why = `a name of ${o.label ?? qid}`;
      } else if (o.disambiguation) {
        why = "a name Wikidata lists for several things";
      }
      if (why && !out.has(name)) out.set(name, why);
    }
  }
  return out;
}

/** RxNorm: English names RxNav resolves only to ingredients other than the ingredient's own. */
async function rxnormOthers(cands: Candidate[], own: Own): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  if (!own.rxcui.length) return out;
  const base = "https://rxnav.nlm.nih.gov/REST/";
  const names = [...new Set(cands.filter((c) => c.lang === "en").map((c) => c.term))].slice(0, 30);
  const one = async (name: string) => {
    const ids = await fetchJson<{ idGroup?: { rxnormId?: string[] } }>(
      base + "rxcui.json?" + new URLSearchParams({ name, search: "2" }),
    );
    const ins = new Map<string, string>();
    for (const id of (ids.idGroup?.rxnormId ?? []).slice(0, 3)) {
      const rel = await fetchJson<{ relatedGroup?: { conceptGroup?: { conceptProperties?: { rxcui: string; name: string }[] }[] } }>(
        `${base}rxcui/${encodeURIComponent(id)}/related.json?tty=IN`,
      );
      for (const g of rel.relatedGroup?.conceptGroup ?? []) {
        for (const p of g.conceptProperties ?? []) ins.set(p.rxcui, p.name);
      }
    }
    if (ins.size && !own.rxcui.some((r) => ins.has(r))) out.set(key(name), `RxNorm: ${[...ins.values()].join(", ")}`);
  };
  for (let i = 0; i < names.length; i += 5) await Promise.all(names.slice(i, i + 5).map(one));
  return out;
}

/** The candidates that name another substance, each with why (keyed by key(term)). Throws when a source fails. */
export async function otherSubstances(cands: Candidate[], own: Own): Promise<Map<string, string>> {
  const [wd, rx] = await Promise.all([wikidataOthers(cands, own), rxnormOthers(cands, own)]);
  for (const [k, v] of rx) if (!wd.has(k)) wd.set(k, v);
  return wd;
}
