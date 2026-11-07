// literature-search — live PubMed and PubMed Central counts for one ingredient and a range of publication
// dates, with a link that opens the very same search on each website, so a person can see the app and NCBI
// agree.
//
// {ingredient_id, from, to}  (days as YYYY-MM-DD, both included)
//   → {ingredient: {id, inn_en}, from, to, checked_at,
//      queries: [{label, kind: 'name'|'class', pubmed: {count, url, error?}, pmc: {count, url, error?}}]}
//
// The searches are the ones the daily literature watch runs (collectors/parsers/pubmed.py): the English INN with
// its other English names matched as words (Store.literature_names: inn, salt or synonym, mode stem), then each
// English word of the drug classes switched into the literature (none by default since 0093), each a quoted
// phrase in titles and abstracts (ncbiTerm). The watch reads by entry date; this answers by publication date, as
// the websites' date filters do.
// A database that does not answer gives count null and an error; its link still opens the search.
// Any signed-in team member may ask. Nothing is stored.
import { HttpError, json, readJson, serve } from "../_shared/cors.ts";
import { requirePerson } from "../_shared/auth.ts";
import { count, type Db, ncbiTerm, parseDay, pause, websiteUrl } from "./ncbi.ts";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_QUERIES = 20;
const DBS: Db[] = ["pubmed", "pmc"];
const NAMES: Record<Db, string> = { pubmed: "PubMed", pmc: "PubMed Central" };

interface Hit {
  count: number | null;
  url: string;
  error?: string;
}

serve(async (req) => {
  const caller = await requirePerson(req);
  const body = await readJson<{ ingredient_id?: string; from?: string; to?: string }>(req);
  const id = String(body.ingredient_id ?? "").trim();
  if (!UUID_RE.test(id)) throw new HttpError(400, "Choose an ingredient.");
  const from = parseDay(body.from);
  const to = parseDay(body.to);
  if (!from || !to) throw new HttpError(400, "Give both dates as year-month-day.");
  if (from > to) throw new HttpError(400, "The first date is after the last one.");
  if (from < "1800-01-01") throw new HttpError(400, "The first date is too early.");

  const svc = caller.svc;
  const { data: ing, error } = await svc.from("ingredient").select("id, inn_en").eq("id", id).maybeSingle();
  if (error) throw new Error(`ingredient lookup failed: ${error.message}`);
  if (!ing) throw new HttpError(404, "That ingredient is not on the watch list.");

  // The classes whose words this ingredient searches in the literature (ingredient_class.enabled, migration
  // 0049, and ingredient_class.literature, 0051), as the daily watch reads them (Store.class_words).
  const { data: links, error: lErr } = await svc
    .from("ingredient_class")
    .select("class_id")
    .eq("ingredient_id", id)
    .eq("enabled", true)
    .eq("literature", true);
  if (lErr) throw new Error(`class lookup failed: ${lErr.message}`);
  let classWords: string[] = [];
  const classIds = (links ?? []).map((r) => r.class_id as string).filter(Boolean);
  if (classIds.length) {
    const { data: words, error: wErr } = await svc
      .from("class_term")
      .select("term")
      .in("class_id", classIds)
      .eq("lang", "en")
      .order("term");
    if (wErr) throw new Error(`class words lookup failed: ${wErr.message}`);
    classWords = (words ?? []).map((r) => String(r.term));
  }

  // The name's other English names, searched with it (never a brand, a code or an exact-only word).
  const { data: names, error: nErr } = await svc
    .from("ingredient_term")
    .select("term")
    .eq("ingredient_id", id)
    .eq("lang", "en")
    .eq("mode", "stem")
    .in("kind", ["inn", "salt", "synonym"]);
  if (nErr) throw new Error(`name lookup failed: ${nErr.message}`);
  const tidy = (w: string) => w.replaceAll('"', "").split(/\s+/).filter(Boolean).join(" ");
  const inn = tidy(String(ing.inn_en ?? ""));
  const also: string[] = [];
  const alsoSeen = new Set([inn.toLowerCase()]);
  for (const w of (names ?? []).map((r) => tidy(String(r.term))).sort((a, b) => a.localeCompare(b))) {
    if (w && !alsoSeen.has(w.toLowerCase())) {
      alsoSeen.add(w.toLowerCase());
      also.push(w);
    }
  }

  // The name first, then each class word once (NCBI ignores case), as the daily watch searches them.
  const candidates: { word: string; kind: "name" | "class" }[] = [
    { word: inn, kind: "name" },
    ...classWords.map((w) => ({ word: w, kind: "class" as const })),
  ];
  const seen = new Set<string>();
  const searches: { label: string; kind: "name" | "class"; term: string }[] = [];
  for (const { word, kind } of candidates) {
    const label = tidy(word);
    if (!label || seen.has(label.toLowerCase())) continue;
    seen.add(label.toLowerCase());
    searches.push({ label, kind, term: ncbiTerm(kind === "name" ? [label, ...also] : [label]) });
  }

  const queries: Record<string, unknown>[] = [];
  let first = true;
  for (const s of searches.slice(0, MAX_QUERIES)) {
    const row: Record<string, unknown> = { label: s.label, kind: s.kind };
    for (const db of DBS) {
      if (!first) await pause();
      first = false;
      const hit: Hit = { count: null, url: websiteUrl(db, s.term, from, to) };
      try {
        hit.count = await count(db, s.term, from, to);
      } catch (e) {
        console.warn("literature-search", db, s.label, e);
        hit.error = `${NAMES[db]} did not answer. Open the link, or try again in a minute.`;
      }
      row[db] = hit;
    }
    queries.push(row);
  }

  return json(req, {
    ingredient: { id: ing.id, inn_en: ing.inn_en },
    from,
    to,
    checked_at: new Date().toISOString(),
    queries,
    ...(searches.length > MAX_QUERIES ? { note: `Only the first ${MAX_QUERIES} searches were counted.` } : {}),
  });
});
