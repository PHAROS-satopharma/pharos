# Free terminologies (migration 0103)

Sato Pharma has no MedDRA subscription yet. Until it does, every case goes on the CIOMS I form, and each reaction
carries the tag **Needs official MedDRA coding**. Meanwhile, PHAROS can still name, search and group reactions with
four medical terminologies whose licences allow a company to use them at no cost. This page says what each one is,
what its licence asks of us, and what none of them can do.

**None of them is MedDRA, and PHAROS makes no claim that any is equivalent to MedDRA.** A code chosen from one of
them is kept on the reaction as `reaction.term` and is never written into the E2B(R3) file. Two tests check this:
`tests/test_terminology.py` (the E2B file) and `web/src/features/terminology/terms.test.ts` (the screen's E2B
checks).

## The four sources

| Source | What PHAROS keeps | Licence and credit | Updated |
|---|---|---|---|
| **NCI Thesaurus** (US National Cancer Institute, EVS) | The descendants of C41331 *Adverse Event* and C7057 *Disease, Disorder or Finding*, plus every concept in a CTCAE subset, including its grades with their criteria. Retired and obsolete concepts are left out. About 51,000 concepts. | [NCI Thesaurus terms of use](https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/ThesaurusTermsofUse.htm): free to use with credit to NCI; NCI does not endorse PHAROS. | Each month |
| **OAE**, the Ontology of Adverse Events | Each OAE class that isn't deprecated: its label, definition, synonyms and alternative terms, and its parents. About 9,300 classes. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), with credit. PHAROS checks the licence on every release and refuses a file that no longer says CC BY. | A few times a year |
| **ICD-11 MMS** (World Health Organization), in English and Arabic | Every chapter, block and category, with its code, its title and its URI, stored exactly as WHO publishes them. About 31,700 entries. | [CC BY-ND 3.0 IGO](https://icd.who.int/en/docs/icd11-license.pdf): PHAROS changes nothing, translates nothing and merges nothing, and never compares ICD-11 with another source. | Each January |
| **MeSH** (US National Library of Medicine) | The disease and mental-disorder trees PHAROS already loads (migration 0061), also copied into the shared search. | NLM terms: credit NLM, which does not endorse PHAROS. | Each year |

### What is never stored

MedDRA is licensed by ICH through MSSO, and this repository is public, so no MedDRA term or code is ever stored or
tested here. OAE carries MedDRA cross-references, and PHAROS never reads them:

- `OAE_0004334` (has_MedDRA_id), the editor notes (`IAO_0000116`), comments and database cross-references are
  skipped;
- any remaining name or definition that mentions MedDRA, or contains an eight-digit code of the 100xxxxx form, is
  dropped.

A test loads a fixture full of such values and checks that none of them reaches the database.

## How a release arrives

The *PHAROS dictionaries* workflow runs on the 3rd of each month at 03:50 Cairo, or by hand with *Terminology*
set to one source or *all*. It runs `python -m collectors.coding --terminology all`, which, for each source:

1. downloads the release and skips it if PHAROS has seen the same file before (same SHA-256);
2. checks it: well-formed codes, a name on every concept, enough concepts, and no more than 20% of concepts
   retired at once;
3. refuses it if the database would pass **400 MB** (the Supabase free plan stops at 500 MB). The four sources
   together take about 180 MB; the database held 190 MB before them (9 November 2026). The watchdog warns at 420 MB;
4. keeps the original, write-once, in the R2 archive;
5. applies the **first** release of a source at once. A **later** release is *staged*: its differences (added,
   changed and retired concepts) wait on the Terminology screen until an administrator presses **Activate** or
   **Reject**. Nothing in the search changes before then. A retired concept is kept and marked, never deleted, so an
   old case still names it;
6. tells the administrators on Telegram what arrived, or why it was refused.

MeSH goes into the same tables after its own load on the 2nd (migration 0061).

## On the screens

- **Terminology** (`/terminology`, linked from the Cases screen): one search across all four sources. It finds a
  code, an exact name, the start of a name, or a close spelling, in English or Arabic (Arabic vowel marks are
  ignored). The source chips narrow the search; "found as" shows the synonym that matched.
- **A concept's page** shows its path from the top of its source, its definition, its other names, its CTCAE grades
  if it has any, its narrower concepts, its source, release and licence, and concepts of other sources with the same
  words. Those are labelled *Same words, not an official mapping*, and ICD-11 never appears among them.
- **Releases**: what is in use, and each staged release with its changes. An administrator activates or rejects it.
- **On a case**, each reaction has a *Free terminology* box. The three closest concepts for its words are
  proposals; nothing is written until a reviewer presses **Use**. The choice records the source, code, name and
  release, and who chose it and when. Choosing a MeSH concept also fills the reaction's MeSH code. The credit of
  each source used appears under the reactions.

## What MedDRA does that these cannot

- **It is the regulatory standard.** ICH E2B(R3), EMA, FDA and the Egyptian Drug Authority require MedDRA
  Lowest Level Terms on individual case reports. None of these four sources is accepted in its place.
- **It has a fixed five-level hierarchy** (LLT, PT, HLT, HLGT, SOC) with one primary SOC for each term. Signal
  detection, PSURs and the authorities' line listings count cases on that hierarchy. These sources are organised
  differently, so their counts don't match MedDRA's.
- **It has the Standardised MedDRA Queries (SMQs)** that authorities expect for safety topics.
- **It has twice-yearly versions** that the E2B file names, and the authorities and partners code to them.
- **It has exchange.** A partner's or an authority's MedDRA code can be checked against the loaded MedDRA. A free
  code can't be checked against anyone else's coding.

PHAROS makes no mapping from these sources to MedDRA, and no MedDRA code is derived from them. Once the subscription
arrives, an administrator uploads MedDRA on the Cases screen (migration 0102), each reaction is coded with its LLT,
and the E2B file can be made. The free code stays on the reaction only as a record.
