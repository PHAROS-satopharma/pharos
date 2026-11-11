// deno test --allow-env supabase/functions/
// The term proposal with every outside source faked: no network is used.
import { assert, assertEquals } from "jsr:@std/assert@1.0.13";
import { isFormula, namesTheSubstance, toIngredientCodes } from "./guard.ts";
import { herbalStore } from "./sources.ts";
import { terms } from "./terms.ts";
import { usableSynonym } from "./text.ts";

// No database in a test: the stored herbal list is read as empty.
herbalStore.read = () => Promise.resolve([]);

const CARVEDILOL = { wikidata_qid: "Q412534", atc_code: "C07AG02", inn_en: "carvedilol" };

type Wikidata = "timeout" | "error" | "empty" | "names";

function reply(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Replaces fetch for one call of terms(): EMA lists empty, PubChem English synonyms, Wikidata as asked. */
async function withSources<T>(wikidata: Wikidata, fn: () => Promise<T>): Promise<T> {
  const real = globalThis.fetch;
  globalThis.fetch = ((input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    if (url.host === "query.wikidata.org") {
      if (wikidata === "timeout") return Promise.reject(new DOMException("Signal timed out.", "TimeoutError"));
      if (wikidata === "error") return Promise.resolve(reply({ error: "busy" }, 503));
      // the check for names of other substances (guard.ts): none
      if (wikidata === "empty" || init?.method === "POST") return Promise.resolve(reply({ results: { bindings: [] } }));
      const item = { type: "uri", value: "http://www.wikidata.org/entity/Q412534" };
      const row = (kind: string, val: string, lang?: string) => ({
        item,
        kind: { type: "literal", value: kind },
        val: { type: "literal", value: val, ...(lang ? { "xml:lang": lang } : {}) },
      });
      return Promise.resolve(reply({
        results: {
          bindings: [
            row("atc", "C07AG02"),
            row("label", "carvedilol", "en"),
            row("label", "Carvedilol", "de"),
            row("label", "carvédilol", "fr"),
            row("label", "カルベジロール", "ja"),
          ],
        },
      }));
    }
    if (url.host === "pubchem.ncbi.nlm.nih.gov") {
      return Promise.resolve(reply({
        InformationList: { Information: [{ Synonym: ["carvedilol", "Coreg", "Dilatrend", "BM-14190"] }] },
      }));
    }
    if (url.host === "www.ema.europa.eu") return Promise.resolve(reply({ data: [] }));
    return Promise.reject(new Error(`unexpected fetch ${url.href}`));
  }) as typeof fetch;
  try {
    return await fn();
  } finally {
    globalThis.fetch = real;
  }
}

const othersMissing = (warnings: string[]) => warnings.some((w) => /names in other languages are missing/.test(w));

Deno.test("Wikidata names in every language arrive with no warning", async () => {
  const r = await withSources("names", () => terms(CARVEDILOL));
  assertEquals(r.warnings, []);
  assert(r.terms.some((t) => t.lang === "de" && t.term === "Carvedilol"));
  assert(r.terms.some((t) => t.lang === "ja"));
});

Deno.test("a Wikidata timeout is reported, and the English terms still come", async () => {
  const r = await withSources("timeout", () => terms(CARVEDILOL));
  assert(othersMissing(r.warnings), `no warning about the other languages: ${JSON.stringify(r.warnings)}`);
  assert(r.warnings.some((w) => /in time/.test(w)), "the warning does not say it timed out");
  assert(r.terms.length > 0 && r.terms.every((t) => t.lang === "en"));
  assert(r.gaps.includes("de"));
});

Deno.test("a Wikidata error status is reported", async () => {
  const r = await withSources("error", () => terms(CARVEDILOL));
  assert(othersMissing(r.warnings), `no warning about the other languages: ${JSON.stringify(r.warnings)}`);
});

Deno.test("Wikidata answering with no names for the item is reported", async () => {
  const r = await withSources("empty", () => terms(CARVEDILOL));
  assert(othersMissing(r.warnings), `no warning about the other languages: ${JSON.stringify(r.warnings)}`);
  assert(r.terms.every((t) => t.lang === "en"));
});

Deno.test("with no Wikidata id, a failed lookup by ATC code is reported", async () => {
  const r = await withSources("timeout", () => terms({ atc_code: "C07AG02", inn_en: "carvedilol" }));
  assert(othersMissing(r.warnings), `no warning about the other languages: ${JSON.stringify(r.warnings)}`);
});

// ───────────── names that belong to another substance (guard.ts, 6 November 2026) ─────────────

const LEVOFLOXACIN = { wikidata_qid: "Q424193", atc_code: "J01MA12", inn_en: "levofloxacin" };
const uri = (q: string) => ({ type: "uri", value: `http://www.wikidata.org/entity/${q}` });
const lit = (value: string, lang?: string) => ({ type: "literal", value, ...(lang ? { "xml:lang": lang } : {}) });

/** Wikidata as it stood on 6 November 2026 for levofloxacin, RxNav as it answers. Wikidata's own RxNorm id for
 *  levofloxacin is 1546009, "levofloxacin anhydrous" (a precise form); its ingredient is 82122. */
async function withLevofloxacin<T>(fn: () => Promise<T>, wikidataRxcui = "82122"): Promise<T> {
  const real = globalThis.fetch;
  globalThis.fetch = ((input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    if (url.host === "query.wikidata.org" && init?.method === "POST") {
      const row = (val: string, other: string, extra: Record<string, unknown>) => ({ val: lit(val), other: uri(other), ...extra });
      return Promise.resolve(reply({ results: { bindings: [
        row("ofloxacin", "Q411447", { otherLabel: lit("ofloxacin"), rx: lit("7623"), cas: lit("82419-36-1") }),
        row("Floxin", "Q411447", { otherLabel: lit("ofloxacin"), rx: lit("7623"), cas: lit("82419-36-1") }),
        row("Floxin", "Q47521929", { otherLabel: lit("Floxin"), ing: uri("Q411447"), ingLabel: lit("ofloxacin"), irx: lit("7623") }),
        row("Levaquin", "Q47521762", { otherLabel: lit("Levaquin"), ing: uri("Q47495791"),
                                       ingLabel: lit("levofloxacin hemihydrate"), irx: lit("82122") }),
        row("Floxacin", "Q5462352", { otherLabel: lit("Floxacin"), p31: uri("Q4167410") }),
      ] } }));
    }
    if (url.host === "query.wikidata.org") {
      const item = uri("Q424193");
      const row = (kind: string, val: string, lang?: string) => ({ item, kind: lit(kind), val: lit(val, lang) });
      return Promise.resolve(reply({ results: { bindings: [
        row("atc", "J01MA12"), row("rxcui", wikidataRxcui),
        row("label", "levofloxacin", "en"), row("label", "Levofloxacin", "de"), row("label", "levofloxacine", "nb"),
        row("alt", "Ofloxacin", "en"), row("alt", "Floxin", "en"), row("alt", "Floxacin", "en"),
        row("alt", "Levaquin", "en"), row("alt", "C18H20FN3O4", "fr"), row("alt", "Canada og Japan", "nb"),
      ] } }));
    }
    if (url.host === "rxnav.nlm.nih.gov") {
      const ids: Record<string, string[]> = { Ofloxacin: ["7623"], Levaquin: ["217992"] };
      const ins: Record<string, [string, string]> = {
        "7623": ["7623", "ofloxacin"], "217992": ["82122", "levofloxacin"],
        "82122": ["82122", "levofloxacin"], "1546009": ["82122", "levofloxacin"],
      };
      const m = url.pathname.match(/rxcui\/(\d+)\/related/);
      if (m) {
        const [rxcui, name] = ins[m[1]];
        return Promise.resolve(reply({ relatedGroup: { conceptGroup: [{ tty: "IN", conceptProperties: [{ rxcui, name }] }] } }));
      }
      return Promise.resolve(reply({ idGroup: { rxnormId: ids[url.searchParams.get("name") ?? ""] } }));
    }
    if (url.host === "pubchem.ncbi.nlm.nih.gov") return Promise.resolve(reply({ InformationList: { Information: [] } }));
    if (url.host === "www.ema.europa.eu") return Promise.resolve(reply({ data: [] }));
    return Promise.reject(new Error(`unexpected fetch ${url.href}`));
  }) as typeof fetch;
  try {
    return await fn();
  } finally {
    globalThis.fetch = real;
  }
}

Deno.test("names of another substance are left out and named in a warning; its own brand stays", async () => {
  const r = await withLevofloxacin(() => terms(LEVOFLOXACIN));
  const names = r.terms.map((t) => t.term);
  for (const wrong of ["Ofloxacin", "Floxin", "Floxacin", "C18H20FN3O4", "Canada og Japan"]) {
    assert(!names.includes(wrong), `${wrong} was proposed`);
  }
  assert(names.includes("Levaquin"), "levofloxacin's own brand was left out");
  assert(names.includes("levofloxacin") && names.includes("Levofloxacin"));
  const warning = r.warnings.find((w) => /another substance/.test(w)) ?? "";
  assert(/Ofloxacin \(a name of ofloxacin\)/.test(warning) && /Floxin/.test(warning), warning);
});

Deno.test("with Wikidata's code of a form (levofloxacin anhydrous), levofloxacin's own names still pass", async () => {
  const r = await withLevofloxacin(() => terms(LEVOFLOXACIN), "1546009");
  const names = r.terms.map((t) => t.term);
  assert(names.includes("Levaquin"), `levofloxacin's own brand was left out: ${JSON.stringify(r.warnings)}`);
  assert(!names.includes("Ofloxacin") && !names.includes("Floxin"));
});

Deno.test("the lookup offers the ingredient's RxNorm code, never the code of a form of it", async () => {
  const items = [{ rxcui: "1546009" }, { rxcui: "82122" }, { rxcui: null }];
  const ok = await withLevofloxacin(() => toIngredientCodes(items));
  assertEquals(items.map((c) => c.rxcui), ["82122", "82122", null]);
  assert(ok);
});

Deno.test("a name check that cannot be made is reported, never silently passed", async () => {
  const real = globalThis.fetch;
  const r = await withLevofloxacin(() => {
    const inner = globalThis.fetch;
    globalThis.fetch = ((input: string | URL | Request, init?: RequestInit) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
      if (url.host === "rxnav.nlm.nih.gov") return Promise.reject(new DOMException("Signal timed out.", "TimeoutError"));
      return inner(input, init);
    }) as typeof fetch;
    return terms(LEVOFLOXACIN);
  });
  globalThis.fetch = real;
  assert(r.warnings.some((w) => /could not be checked/.test(w)), JSON.stringify(r.warnings));
});

Deno.test("formulas and several-word aliases that do not name the substance are refused", () => {
  assert(isFormula("C9H13NO2") && isFormula("C10H14O4") && !isFormula("Coreg") && !isFormula("CHF"));
  assert(!usableSynonym("C9H13NO2"));
  assert(!namesTheSubstance("Canada og Japan", ["paracetamol", "acetaminophen"]));
  assert(namesTheSubstance("acetaminophen i USA", ["paracetamol", "acetaminophen"]));
  assert(namesTheSubstance("Tylenol", ["paracetamol"]));
});
