-- The literature is searched for the ingredients' names only (owner, 7 Nov 2026).
-- PubMed, PubMed Central and Europe PMC are now searched in titles and abstracts only, for each ingredient's
-- English names (collectors/parsers/pubmed.py, europepmc.py). The drug-class words made the 12-month look-back
-- about 140,000 papers, most about other drugs of the class, so every class is kept out of the literature:
--   ingredient_class.literature is false for every link, and a new link (a class made from the ATC code by the
--   daily run, or added by hand) starts out of the literature too. The class's words are still searched in the
--   authorities' notices. An administrator can still switch a class back on (set_class_literature, 0051).
-- Readiness (ingredient_readiness, 0082) then waits only for the name's look-back, as it reads ic.literature.

alter table ingredient_class alter column literature set default false;
update ingredient_class set literature = false where literature;
comment on column ingredient_class.literature is
  'Whether the class''s English words are also searched in the literature (PubMed, PMC, Europe PMC). Off by '
  'default since 0093: the literature is searched for the ingredients'' names; the words stay in notices.';
