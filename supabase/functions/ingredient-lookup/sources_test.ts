// deno test --allow-env supabase/functions/
// The names of a herbal substance from EMA's HMPC list (8 November 2026: "ivy leaves" found nothing).
import { assertEquals } from "jsr:@std/assert@1.0.13";
import { assertRejects } from "jsr:@std/assert@1.0.13";
import { botanicalNames, type EmaSubstance, herbalNames, pubchemSynonyms } from "./sources.ts";
import { similarity } from "./text.ts";

const herbal = (name: string, latin: string, plants: string[]): EmaSubstance => ({
  name,
  atc: new Set(),
  lists: new Set(["ema-herbal"]),
  brands: new Set(),
  herbal: { latin, plants },
});

Deno.test("botanical names lose their authors, also when EMA writes them against the epithet", () => {
  assertEquals(botanicalNames("Hedera helix L."), ["Hedera helix"]);
  assertEquals(
    botanicalNames("Fragaria vescaL.;Fragaria moschataWeston;Fragaria x ananassa (Weston) Duchesne ex Rozier"),
    ["Fragaria vesca", "Fragaria moschata", "Fragaria x ananassa"],
  );
  assertEquals(botanicalNames("Glycine max (L.) Merr."), ["Glycine max"]);
  assertEquals(botanicalNames(""), []);
  assertEquals(botanicalNames(undefined), []);
});

Deno.test("ivy leaf answers to its plural, its Latin name and its plant", () => {
  const ivy = herbal("Ivy leaf", "Hederae helicis folium", ["Hedera helix"]);
  assertEquals(herbalNames(ivy), ["Ivy leaf", "Ivy leaves", "Hederae helicis folium", "Hedera helix"]);
  for (const typed of ["ivy leaves", "ivy leaf", "Hedera helix", "hederae helicis folium"]) {
    const best = Math.max(...herbalNames(ivy).map((n) => similarity(typed, n)));
    assertEquals(best, 1, typed);
  }
  assertEquals(herbalNames(herbal("Wild Strawberry Leaf", "Fragariae folium", []))[1], "Wild Strawberry Leaves");
  assertEquals(herbalNames(herbal("Liquorice Root", "Liquiritiae radix", []))[1], "Liquorice Roots");
});

Deno.test("a substance that is not herbal keeps its one name", () => {
  const s: EmaSubstance = { name: "lornoxicam", atc: new Set(), lists: new Set(["ema-psusa"]), brands: new Set() };
  assertEquals(herbalNames(s), ["lornoxicam"]);
});

async function withPubchem<T>(status: number, fn: () => Promise<T>): Promise<T> {
  const real = globalThis.fetch;
  globalThis.fetch = (() =>
    Promise.resolve(new Response(status === 200 ? JSON.stringify({ InformationList: { Information: [{ Synonym: ["Coreg"] }] } }) : "{}", { status }))) as typeof fetch;
  try {
    return await fn();
  } finally {
    globalThis.fetch = real;
  }
}

Deno.test("PubChem with no compound for a herb is no synonyms, not a failure", async () => {
  assertEquals(await withPubchem(404, () => pubchemSynonyms("Ivy leaf")), []);
  assertEquals(await withPubchem(200, () => pubchemSynonyms("carvedilol")), ["Coreg"]);
  await assertRejects(() => withPubchem(503, () => pubchemSynonyms("carvedilol")));
});
