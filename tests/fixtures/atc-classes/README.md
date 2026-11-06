# atc-classes (PHAROS fixture)

What `collectors/classes.py` reads to make a drug class from an ingredient's ATC code. Every file is the
answer exactly as received on 6 November 2026, with the requests the code itself makes:

* `who-J01MA.html`, `who-M01AC.html` — WHO's ATC index,
  `https://atcddd.fhi.no/atc_ddd_index/?code=<code>&showdescription=no` (ISO-8859-1). The group line reads
  `J01MA <b><a …>Fluoroquinolones</a></b>` and `M01AC <b><a …>Oxicams</a></b>`.
* `wikidata-atc-J01MA.json` — the Wikidata SPARQL query for the item whose ATC code (P267) is J01MA, its
  labels and aliases in the 15 languages: Q28801726 (fluoroquinolone), labels in 12 languages (no Japanese,
  Portuguese or Icelandic).
* `wikidata-atc-M01AC.json` — the same query for M01AC: no item carries that code (empty bindings).
* `wikidata-search-Oxicams.json` — the Wikidata search `Oxicams haswbstatement:P31=Q2585617` (drug classes
  named Oxicams): Q1143640.
* `wikidata-items-Q1143640.json` — the labels and aliases of Q1143640 (oxicam) in the 15 languages.
