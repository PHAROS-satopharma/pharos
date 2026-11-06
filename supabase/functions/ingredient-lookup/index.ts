// ingredient-lookup — ranked candidates for a typed ingredient, and proposed per-language terms for one.
//
// {q}                                          → {candidates:[...], warnings:[...]}
// {action:'terms', wikidata_qid, atc_code, inn_en} → {terms:[...], gaps:[...], notes:[...], warnings:[...]}
//
// It NEVER saves and NEVER picks: the web app shows the ranked list and nothing is stored until a person
// clicks "Confirm <name> (<ATC>)". Proposed terms are pre-filled into the term editor for a human to check.
//
// Known gaps (also returned as `notes` with every term proposal):
// - National brand names (CIMA, BDPM, FEST, Fimea, Swissmedic, CBG, PMDA, MFDS) are not looked up here; the
//   SPC watch discovers national products, and brands are added in the term editor.
// - Wikidata often lacks Finnish, Norwegian, Icelandic and Korean labels (e.g. fi lornoksikaami,
//   nb lornoksikam, ko 로르녹시캄): such languages are listed in `gaps` and must be typed by hand.
// - Salt forms are not proposed. PubChem synonyms are English-only and unverified.
// - EU-wide (centrally authorised) brands from the EMA medicines list are proposed once per EU/EEA language
//   so that language-filtered matching sees them; nationally authorised brands are not in that list.
// - Wikidata is the only source of the non-English names. When it fails, times out or sends nothing for the
//   item, the proposal still comes back with the English sources and `warnings` says the other languages are
//   missing; the form shows it with a button to load the names again (terms.ts).
import { HttpError, json, readJson, serve } from "../_shared/cors.ts";
import { requirePerson } from "../_shared/auth.ts";
import {
  emaIndex,
  pubchemAutocomplete,
  rxnavSuggest,
  wikidataByAtc,
  wikidataDetails,
  wikidataSearch,
  type EmaSubstance,
  type WikidataItem,
} from "./sources.ts";
import { key, similarity } from "./text.ts";
import { ATC_RE, settled, terms } from "./terms.ts";

interface Candidate {
  inn_en: string;
  atc_code: string | null;
  wikidata_qid: string | null;
  rxcui: string | null;
  labels: Record<string, string>;
  sources: string[];
  score: number;
  description?: string | null;
}

// ───────────────────────────── search ─────────────────────────────

async function search(q: string): Promise<{ candidates: Candidate[]; warnings: string[] }> {
  const warnings: string[] = [];
  const atcQuery = ATC_RE.test(q.toUpperCase()) ? q.toUpperCase() : null;
  const despaced = q.replace(/\s+/g, "");

  const [wdA, wdB, wdAtc, rx, ema, pc] = await Promise.allSettled([
    wikidataSearch(q),
    despaced !== q ? wikidataSearch(despaced) : Promise.resolve([] as string[]),
    atcQuery ? wikidataByAtc(atcQuery) : Promise.resolve([] as string[]),
    rxnavSuggest(q),
    emaIndex(),
    pubchemAutocomplete(q),
  ]);
  const qids = new Set<string>([
    ...settled(wdA, "Wikidata", warnings, []),
    ...settled(wdB, "Wikidata", warnings, []),
    ...settled(wdAtc, "Wikidata", warnings, []),
  ]);
  const rxNames = settled(rx, "RxNav", warnings, []);
  const emaRes = settled(ema, "EMA lists", warnings, { index: new Map<string, EmaSubstance>(), failed: [] });
  if (emaRes.failed.length) warnings.push(`EMA list(s) not loaded: ${emaRes.failed.join(", ")}.`);
  const pcNames = settled(pc, "PubChem", warnings, []).map(key);

  // Fuzzy match against every EMA substance name (this is what turns "laura noxicam" into lornoxicam and
  // tenoxicam), or exact ATC match when an ATC code was typed.
  const emaHits = [...emaRes.index.values()]
    .map((s) => ({ s, sim: atcQuery ? (s.atc.has(atcQuery) ? 1 : 0) : similarity(q, s.name) }))
    .filter((h) => h.sim >= 0.55)
    .sort((a, b) => b.sim - a.sim)
    .slice(0, 6);

  // Names the reference sources propose; look each up in Wikidata to get its identity (QID, ATC).
  const names = new Set<string>();
  for (const r of rxNames) names.add(r.name);
  for (const h of emaHits) names.add(key(h.s.name));
  for (const n of pcNames.slice(0, 3)) names.add(n);
  const lookups = await Promise.allSettled([...names].slice(0, 10).map((n) => wikidataSearch(n, 3)));
  for (const r of lookups) if (r.status === "fulfilled") r.value.forEach((x) => qids.add(x));

  let details = new Map<string, WikidataItem>();
  try {
    details = await wikidataDetails([...qids]);
  } catch (e) {
    warnings.push("Wikidata details did not answer; labels and ATC codes may be missing.");
    console.warn(e);
  }

  const byKey = new Map<string, Candidate>();
  const nameKeys = (c: Candidate) => [key(c.inn_en), ...Object.values(c.labels).map(key)];

  // Wikidata items that are medicines (have an ATC code, an RxNorm id or a PubChem id).
  for (const it of details.values()) {
    if (!it.atc.length && !it.rxcui.length && !it.cid.length) continue;
    const en = it.labels.en ?? Object.values(it.labels)[0];
    if (!en) continue;
    const c: Candidate = {
      inn_en: en,
      atc_code: it.atc[0] ?? null,
      wikidata_qid: it.qid,
      rxcui: it.rxcui[0] ?? null,
      labels: { ...it.labels },
      sources: ["wikidata"],
      score: 0,
      description: it.description,
    };
    byKey.set(it.qid, c);
  }

  // EMA names with no Wikidata item still appear (with the ATC code EMA gives, if any).
  for (const { s } of emaHits) {
    const k = key(s.name);
    const existing = [...byKey.values()].find((c) => nameKeys(c).includes(k) || (c.atc_code && s.atc.has(c.atc_code)));
    if (existing) {
      for (const l of s.lists) if (!existing.sources.includes(l)) existing.sources.push(l);
      if (!existing.atc_code && s.atc.size) existing.atc_code = [...s.atc][0];
    } else {
      byKey.set(`ema:${k}`, {
        inn_en: s.name,
        atc_code: s.atc.size ? [...s.atc][0] : null,
        wikidata_qid: null,
        rxcui: null,
        labels: { en: s.name },
        sources: [...s.lists],
        score: 0,
      });
    }
  }

  // Attach RxNav, PubChem and EMA presence by name.
  for (const c of byKey.values()) {
    const keys = nameKeys(c);
    const rxHit = rxNames.find((r) => keys.includes(r.name));
    if (rxHit) {
      if (!c.sources.includes("rxnav")) c.sources.push("rxnav");
      c.rxcui ??= rxHit.rxcui;
    }
    if (pcNames.some((n) => keys.includes(n)) && !c.sources.includes("pubchem")) c.sources.push("pubchem");
    const emaHit = emaRes.index.get(key(c.inn_en));
    if (emaHit) for (const l of emaHit.lists) if (!c.sources.includes(l)) c.sources.push(l);
  }

  // Rank: closeness to what was typed first, then how many independent sources agree, then an ATC code.
  for (const c of byKey.values()) {
    const sim = atcQuery && c.atc_code === atcQuery
      ? 1
      : Math.max(...[c.inn_en, ...Object.values(c.labels)].map((n) => similarity(q, n)));
    let score = 55 * sim;
    if (sim === 1) score += 15;
    if (c.atc_code) score += 12;
    if (c.sources.some((s) => s.startsWith("ema-"))) score += 8;
    if (c.sources.includes("rxnav")) score += 6;
    if (c.sources.includes("pubchem")) score += 2;
    if (c.sources.includes("wikidata")) score += 2;
    c.score = Math.min(100, Math.round(score));
  }

  const candidates = [...byKey.values()]
    .filter((c) => c.score >= 35)
    .sort((a, b) => b.score - a.score || a.inn_en.localeCompare(b.inn_en))
    .slice(0, 10);
  return { candidates, warnings };
}

serve(async (req) => {
  await requirePerson(req);
  const body = await readJson<{ q?: string; action?: string; wikidata_qid?: string; atc_code?: string; inn_en?: string }>(req);

  if (body.action === "terms") return json(req, await terms(body));
  if (body.action && body.action !== "search") throw new HttpError(400, "Unknown action.");

  const q = (body.q ?? "").trim();
  if (q.length < 2 || q.length > 100) throw new HttpError(400, "Type 2 to 100 characters.");
  return json(req, await search(q));
});
