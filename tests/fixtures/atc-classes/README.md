# atc-classes (PHAROS fixture)

What `collectors/classes.py` reads to make a drug class from an ingredient's ATC code. Every file is the
answer exactly as received on 6 November 2026, with the requests the code itself makes:

* `who-J01MA.html`, `who-M01AC.html`, `who-J01M.html`, `who-M01A.html` — WHO's ATC index,
  `https://atcddd.fhi.no/atc_ddd_index/?code=<code>&showdescription=no` (ISO-8859-1). The group line reads
  `J01MA <b><a …>Fluoroquinolones</a></b>` and `M01AC <b><a …>Oxicams</a></b>`; the level-3 classes above them
  are in capitals, `J01M <b><a …>QUINOLONE ANTIBACTERIALS</a></b>` and `M01A <b><a …>ANTIINFLAMMATORY AND
  ANTIRHEUMATIC PRODUCTS, NON-STEROIDS</a></b>`.
* `wikidata-atc-J01M.json` — the SPARQL query for the item whose ATC code is J01M: Q13669486 (quinolone
  antibiotic), labels in 15 languages including Japanese (ニューキノロン, フルオロキノロン) and the alias
  "girase inhibitors" — the noise that keeps a parent class switched off until it is read.
* `wikidata-atc-M01A.json` — the same query for M01A: no item carries that code (empty bindings).
* `wikidata-search-M01A.json` — the Wikidata search for WHO's name of M01A among drug classes: nothing.
* `wikidata-atc-J01MA.json` — the Wikidata SPARQL query for the item whose ATC code (P267) is J01MA, its
  labels and aliases in the 15 languages: Q28801726 (fluoroquinolone), labels in 12 languages (no Japanese,
  Portuguese or Icelandic).
* `wikidata-atc-M01AC.json` — the same query for M01AC: no item carries that code (empty bindings).
* `wikidata-search-Oxicams.json` — the Wikidata search `Oxicams haswbstatement:P31=Q2585617` (drug classes
  named Oxicams): Q1143640.
* `wikidata-items-Q1143640.json` — the labels and aliases of Q1143640 (oxicam) in the 15 languages.
