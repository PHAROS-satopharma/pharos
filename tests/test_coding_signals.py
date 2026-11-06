"""What the coded terms say (migration 0062): the MeSH headings of papers, and the MeSH names in labels."""

from __future__ import annotations

import json
from contextlib import contextmanager

from collectors.coding import labels, papers

EFETCH_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle><MedlineCitation><PMID Version="1">111</PMID>
  <MeshHeadingList>
   <MeshHeading><DescriptorName UI="D056486" MajorTopicYN="N">Chemical and Drug Induced Liver Injury</DescriptorName>
    <QualifierName UI="Q000209" MajorTopicYN="Y">etiology</QualifierName></MeshHeading>
   <MeshHeading><DescriptorName UI="D005076" MajorTopicYN="N">Exanthema</DescriptorName>
    <QualifierName UI="Q000139" MajorTopicYN="N">chemically induced</QualifierName></MeshHeading>
   <MeshHeading><DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName></MeshHeading>
  </MeshHeadingList></MedlineCitation></PubmedArticle>
 <PubmedArticle><MedlineCitation><PMID Version="1">222</PMID></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


class FakeDb:
    def __init__(self, rows=None, one=None):
        self.rows, self.one, self.done = rows or {}, one, []

    def fetchall(self, sql, params=None):
        for key, rows in self.rows.items():
            if key in sql:
                return rows
        return []

    def fetchone(self, sql, params=None):
        return self.one

    def execute(self, sql, params=None):
        self.done.append((" ".join(sql.split())[:40], params))

    @contextmanager
    def transaction(self):
        yield self


# ───────────────────────────── papers ─────────────────────────────
def test_headings_keep_the_qualifiers_and_the_major_flag():
    got = papers.parse(EFETCH_XML)
    assert set(got) == {"111", "222"} and got["222"] == []
    liver, rash, humans = got["111"]
    assert liver == {"ui": "D056486", "name": "Chemical and Drug Induced Liver Injury", "major": True,
                     "q": ["Q000209"]}
    assert rash["q"] == ["Q000139"] and not rash["major"]
    assert humans["q"] == []


def test_every_paper_waiting_is_stored_and_a_failed_batch_is_counted():
    rows = [{"id": "doc-a", "pmid": "111"}, {"id": "doc-b", "pmid": "111"}, {"id": "doc-c", "pmid": "222"}]
    db = FakeDb({"from document d": rows})
    asked = []

    def fetch(pmids):
        asked.append(pmids)
        return EFETCH_XML

    words = papers.code_papers(db, fetch=fetch)
    assert asked == [["111", "222"]]                       # one request; the same paper twice is asked once
    stored = {p["id"]: json.loads(p["mesh"]) for _, p in db.done}
    assert set(stored) == {"doc-a", "doc-b", "doc-c"} and stored["doc-c"] == []
    assert words == "1 papers indexed, 1 not indexed by NLM yet"

    db = FakeDb({"from document d": rows})

    def broken(pmids):
        raise TimeoutError

    assert "2 to try again" in papers.code_papers(db, fetch=broken) and db.done == []


def test_nothing_waiting_asks_nothing():
    assert papers.code_papers(FakeDb(), fetch=lambda p: 1 / 0) == "no paper waits for its MeSH headings"


# ───────────────────────────── labels ─────────────────────────────
TERMS = [
    {"ui": "D056486", "term": "Chemical and Drug Induced Liver Injury"},
    {"ui": "D056486", "term": "Hepatitis, Toxic"},
    {"ui": "D006505", "term": "Hepatitis"},
    {"ui": "D005076", "term": "Rash"},
    {"ui": "D009325", "term": "Nausea"},
    {"ui": "D012640", "term": "Seizures"},
    {"ui": "D001523", "term": "Disorder"},           # a generic word, never taken alone
    {"ui": "D013577", "term": "Syndrome"},
]


def test_the_longest_name_wins_and_generic_words_are_skipped():
    names = labels.index(TERMS)
    assert "disorder" not in names and "syndrome" not in names
    text = ("Common: nausea, rash. Uncommon: toxic hepatitis; hepatitis, toxic. Rare: chemical and drug "
            "induced liver injury, a seizure disorder, a syndrome.")
    found = labels.find_terms(text, names)
    assert found == {"D009325": "Nausea", "D005076": "Rash", "D006505": "Hepatitis",
                     "D056486": "Hepatitis, Toxic", "D012640": "Seizures"}


def test_a_label_is_coded_once_until_it_or_the_dictionary_changes():
    mesh = {"version": "MeSH 2026", "sha256": "abcdef0123456789"}
    our = [{"ingredient_id": "ing-1", "ref": "lab-1", "product_name": "Carvid", "version": "March 2024",
            "text": "Very common: nausea. Common: rash."}]
    ref = [{"ingredient_id": "ing-1", "ref": "snap-9", "product_name": "Dilatrend", "doc_date": None,
            "r2_key": "sha256/x"}]
    archive = {"sha256/x": {"sections": {"4.8": "Seizures have been reported."}}}
    db = FakeDb({"from our_label": our, "from spc_product sp": ref, "from mesh_term t": TERMS,
                 "from label_coded": []}, one=mesh)
    words = labels.code_labels(db, load=archive.get)
    assert words == "2 labels coded, 0 unchanged"
    inserted = [json.loads(p["f"]) for sql, p in db.done if sql.startswith("insert into label_mesh")]
    assert inserted == [[{"ui": "D005076", "term": "Rash"}, {"ui": "D009325", "term": "Nausea"}],
                        [{"ui": "D012640", "term": "Seizures"}]]

    coded = [{"ingredient_id": "ing-1", "source": "our_label", "label_ref": "lab-1",
              "mesh_version": "MeSH 2026 (abcdef012345)"},
             {"ingredient_id": "ing-1", "source": "reference", "label_ref": "snap-9",
              "mesh_version": "MeSH 2026 (abcdef012345)"},
             {"ingredient_id": "ing-2", "source": "reference", "label_ref": "snap-1", "mesh_version": "x"}]
    db = FakeDb({"from our_label": our, "from spc_product sp": ref, "from mesh_term t": TERMS,
                 "from label_coded": coded}, one=mesh)
    assert labels.code_labels(db, load=archive.get) == "0 labels coded, 2 unchanged, 1 removed"
    assert [p for sql, p in db.done] == [{"i": "ing-2", "s": "reference"}]

    db = FakeDb({"from our_label": our, "from spc_product sp": ref, "from mesh_term t": TERMS,
                 "from label_coded": coded[:2]}, one={**mesh, "sha256": "ffff"})
    assert labels.code_labels(db, load=archive.get) == "2 labels coded, 0 unchanged"


def test_no_dictionary_codes_nothing():
    assert labels.code_labels(FakeDb(), load={}.get) == "MeSH is not loaded: no label coded"
