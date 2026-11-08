// Proposed per-language terms for one confirmed ingredient (action 'terms' of ingredient-lookup).
// Kept apart from index.ts, which starts the server on import, so that it can be tested on its own.
import { HttpError } from "../_shared/cors.ts";
import {
  EEA_LANGS,
  emaIndex,
  herbalNames,
  LANGS,
  pubchemSynonyms,
  wikidataByAtc,
  wikidataDetails,
  type EmaSubstance,
  type WikidataItem,
} from "./sources.ts";
import { type Candidate, namesTheSubstance, otherSubstances } from "./guard.ts";
import { key, looksLikeCode, modeFor, usableSynonym } from "./text.ts";

export interface Term {
  lang: string;
  country_code: string | null;
  term: string;
  kind: "inn" | "salt" | "brand" | "code" | "synonym";
  mode: "stem" | "exact" | "substring";
  source: string;
}

export const ATC_RE = /^[A-Z]\d{2}[A-Z]{2}\d{2}$/;

export function settled<T>(r: PromiseSettledResult<T>, label: string, warnings: string[], fallback: T): T {
  if (r.status === "fulfilled") return r.value;
  warnings.push(`${label} did not answer; its suggestions are missing.`);
  console.warn(label, r.reason);
  return fallback;
}

// ───────────────────────────── terms ─────────────────────────────

// Wikidata is the only source of the names in languages other than English, so when it fails the proposal
// still comes back (English INN, PubChem, EMA brands) and the form must say what is missing.
const OTHERS_MISSING =
  "so the names in other languages are missing: only the English sources are shown. Load the names again, or type them by hand.";

function wikidataFailed(reason: unknown): string {
  const timedOut = reason instanceof DOMException && (reason.name === "TimeoutError" || reason.name === "AbortError");
  console.warn("Wikidata", reason);
  if (timedOut) return `Wikidata did not answer in time, ${OTHERS_MISSING}`;
  const why = reason instanceof Error && reason.message ? ` (${reason.message})` : "";
  return `Wikidata did not answer${why}, ${OTHERS_MISSING}`;
}

export async function terms(body: { wikidata_qid?: string; atc_code?: string; inn_en?: string }) {
  const warnings: string[] = [];
  const inn = (body.inn_en ?? "").trim();
  const atc = (body.atc_code ?? "").trim().toUpperCase();
  let qid = (body.wikidata_qid ?? "").trim();
  if (qid && !/^Q\d+$/.test(qid)) throw new HttpError(400, "wikidata_qid must look like Q123.");
  if (atc && !ATC_RE.test(atc)) throw new HttpError(400, "atc_code must look like M01AC05.");
  if (!qid && !atc && !inn) throw new HttpError(400, "Give wikidata_qid, atc_code or inn_en.");

  if (!qid && atc) {
    try {
      qid = (await wikidataByAtc(atc))[0] ?? "";
      if (!qid) warnings.push(`Wikidata has no item with the ATC code ${atc}, ${OTHERS_MISSING}`);
    } catch (e) {
      warnings.push(wikidataFailed(e));
    }
  }

  const [det, ema, syn] = await Promise.allSettled([
    qid ? wikidataDetails([qid]) : Promise.resolve(new Map<string, WikidataItem>()),
    emaIndex(),
    inn ? pubchemSynonyms(inn) : Promise.resolve([] as string[]),
  ]);
  // A fulfilled answer can still hold nothing for the item (an empty or partial reply): that is reported too.
  let item: WikidataItem | undefined;
  if (det.status === "rejected") warnings.push(wikidataFailed(det.reason));
  else if (qid) {
    item = det.value.get(qid);
    if (!item || !Object.keys(item.labels).length) {
      warnings.push(`Wikidata sent no names for ${qid}, ${OTHERS_MISSING}`);
    }
  }
  const emaRes = settled(ema, "EMA lists", warnings, { index: new Map<string, EmaSubstance>(), failed: [] });
  if (emaRes.failed.length) warnings.push(`EMA list(s) not loaded: ${emaRes.failed.join(", ")}; EU-wide brand names may be missing.`);
  const synonyms = settled(syn, "PubChem", warnings, []);
  const innEn = inn || item?.labels.en || "";

  const out: Term[] = [];
  const seen = new Set<string>();
  const push = (t: Omit<Term, "mode">) => {
    const term = t.term.trim();
    if (!term) return;
    const k = `${t.lang}|${key(term)}`;
    if (seen.has(k)) return;
    seen.add(k);
    out.push({ ...t, term, mode: modeFor(term, t.lang, t.kind) });
  };

  if (innEn) push({ lang: "en", country_code: null, term: innEn, kind: "inn", source: inn ? "manual" : "wikidata" });

  // the substance's own one-word names: an alias of several words must contain one ("Canada og Japan" does not)
  const ownNames = item
    ? [innEn, ...Object.values(item.labels), ...Object.values(item.alt).flat()].filter((n) => n && !/\s/.test(n.trim()))
    : [innEn];
  if (item) {
    for (const lang of LANGS) {
      const label = item.labels[lang];
      if (label) push({ lang, country_code: null, term: label, kind: "inn", source: "wikidata" });
      for (const alt of item.alt[lang] ?? []) {
        if (!usableSynonym(alt) && !looksLikeCode(alt)) continue;
        if (!looksLikeCode(alt) && !namesTheSubstance(alt, ownNames)) continue;
        push({ lang, country_code: null, term: alt, kind: looksLikeCode(alt) ? "code" : "synonym", source: "wikidata" });
      }
    }
  }

  // A herbal substance (EMA's HMPC list) is written in the papers by its plural, its Latin name and its plant:
  // "ivy leaves", "Hederae helicis folium", "Hedera helix" for Ivy leaf (8 November 2026).
  const herbal = innEn ? emaRes.index.get(key(innEn)) : undefined;
  if (herbal?.herbal) {
    for (const n of herbalNames(herbal)) push({ lang: "en", country_code: null, term: n, kind: "synonym", source: "ema-herbal" });
  }

  // EU-wide brand names from the EMA medicines and DHPC lists (matched by INN or by ATC code).
  const brands = new Map<string, string>();
  for (const s of emaRes.index.values()) {
    const sameName = innEn && key(s.name) === key(innEn);
    const sameAtc = atc && s.atc.has(atc);
    if (!sameName && !sameAtc) continue;
    for (const b of s.brands) {
      if (key(b) !== key(innEn)) brands.set(key(b), b);
    }
  }
  for (const b of brands.values()) {
    for (const lang of EEA_LANGS) push({ lang, country_code: null, term: b, kind: "brand", source: "ema-medicines" });
  }

  // PubChem synonyms: development codes and short alternative names (English, unverified).
  let pcCount = 0;
  for (const s of synonyms) {
    if (pcCount >= 12) break;
    if (key(s) === key(innEn)) continue;
    if (looksLikeCode(s)) {
      push({ lang: "en", country_code: null, term: s, kind: "code", source: "pubchem" });
      pcCount++;
    } else if (usableSynonym(s) && /^[\p{L}][\p{L}\- ]+$/u.test(s) && s.split(" ").length <= 2) {
      push({ lang: "en", country_code: null, term: s, kind: "synonym", source: "pubchem" });
      pcCount++;
    }
  }

  // Names that belong to another substance are left out (guard.ts), and the form says which and why.
  const checked = out.filter((t) => (t.kind === "synonym" || t.kind === "brand") &&
    (t.source === "wikidata" || t.source === "pubchem"));
  if (checked.length) {
    try {
      const other = await otherSubstances(
        checked.map((t): Candidate => ({ term: t.term, lang: t.lang })),
        { qid: qid || null, rxcui: item?.rxcui ?? [], inn: innEn },
      );
      if (other.size) {
        const left: string[] = [];
        for (let i = out.length - 1; i >= 0; i--) {
          const why = checked.includes(out[i]) ? other.get(key(out[i].term)) : undefined;
          if (!why) continue;
          left.unshift(`${out[i].term} (${why})`);
          out.splice(i, 1);
        }
        warnings.push(`Left out because they name another substance: ${[...new Set(left)].join("; ")}.`);
      }
    } catch (e) {
      console.warn("name check", e);
      warnings.push(
        "The proposed names could not be checked against Wikidata and RxNorm for other substances; check each one yourself.",
      );
    }
  }

  const gaps = LANGS.filter((l) => !out.some((t) => t.lang === l && t.kind === "inn"));
  const notes = [
    "Nothing is saved until you confirm. Check every proposed term against the regulator's own wording.",
    "National brand names (Spain CIMA, France BDPM, Norway FEST, Finland Fimea, Switzerland, Netherlands CBG, Japan PMDA, Korea MFDS) are not looked up here; add them in the term editor.",
    "Languages listed under gaps have no name from Wikidata; type the local name by hand (e.g. fi lornoksikaami, nb lornoksikam, ko 로르녹시캄).",
    "Salt forms are not proposed. PubChem names are English-only and unverified.",
  ];
  return { terms: out, gaps, notes, warnings, wikidata_qid: qid || null };
}
