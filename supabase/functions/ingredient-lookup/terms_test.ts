// deno test --allow-env supabase/functions/
// The term proposal with every outside source faked: no network is used.
import { assert, assertEquals } from "jsr:@std/assert@1.0.13";
import { terms } from "./terms.ts";

const CARVEDILOL = { wikidata_qid: "Q412534", atc_code: "C07AG02", inn_en: "carvedilol" };

type Wikidata = "timeout" | "error" | "empty" | "names";

function reply(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Replaces fetch for one call of terms(): EMA lists empty, PubChem English synonyms, Wikidata as asked. */
async function withSources<T>(wikidata: Wikidata, fn: () => Promise<T>): Promise<T> {
  const real = globalThis.fetch;
  globalThis.fetch = ((input: string | URL | Request) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    if (url.host === "query.wikidata.org") {
      if (wikidata === "timeout") return Promise.reject(new DOMException("Signal timed out.", "TimeoutError"));
      if (wikidata === "error") return Promise.resolve(reply({ error: "busy" }, 503));
      if (wikidata === "empty") return Promise.resolve(reply({ results: { bindings: [] } }));
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
