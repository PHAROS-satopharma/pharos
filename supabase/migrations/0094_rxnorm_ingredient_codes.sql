-- PHAROS — the RxNorm code of an ingredient is the RxNorm ingredient (IN), never a precise form of it (2026-11-07).
--
-- Levofloxacin was stored with 1546009, "levofloxacin anhydrous" (a PIN): the ingredient lookup took the code
-- Wikidata gives its levofloxacin item. RxNav resolves levofloxacin's names to the ingredient 82122, so the
-- matching audit of 7 November 2026 flagged six of its own names (L-ofloxacin, Levaquin, Levofloxacin
-- anhydrous, Levofloxacine, Levofloxacino, Levofloxacinum) as "RxNorm: levofloxacin". Lornoxicam had no code
-- (RxNorm 20890), so its names were never checked. DailyMed finds the same 143 levofloxacin labels by either code.
-- The lookup now stores the ingredient's code (supabase/functions/ingredient-lookup/index.ts), and the name
-- check and the audit compare against it (guard.ts, collectors/match_audit.py).
-- ingredient is logged by its audit trigger (0001). A code someone has since changed by hand is left as it is.

update ingredient set rxcui = '82122'
 where lower(inn_en) = 'levofloxacin' and rxcui = '1546009';

update ingredient set rxcui = '20890'
 where lower(inn_en) = 'lornoxicam' and rxcui is null;
