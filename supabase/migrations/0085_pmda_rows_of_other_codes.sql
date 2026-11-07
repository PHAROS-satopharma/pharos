-- PHAROS — Japan's package inserts filed under an ingredient whose code they do not carry are switched off.
--
-- Before 0079 the first ingredient to list a label kept it. Live, 6 Nov 2026 (read 23:30 Cairo): ivabradine held
-- 100 active PMDA "products" under 23 different 一般名 codes (paracetamol's 1141007, 1141400 and 1141700 among
-- them), and only one under its own code 2190039. 0079 expected the wrong owner's next run to switch them off,
-- but that happens only when the run lists them as gone, and the label watch now keeps products a list does
-- not reach (a partial list switches nothing off). So they are switched off here, once.
--
-- The rule: a PMDA product whose national id ("<company>_<YJ code>") does not start, after the company, with one
-- of the ingredient's Japanese codes (ingredient_term kind code, country JP: the 7-character 一般名 code, or a
-- 12-character YJ code whose first 7 characters are it). Nothing is deleted: the snapshots stay, and a product a
-- later run lists again for that ingredient is switched back on by its upsert. Ingredients with no Japanese
-- code keep their rows (their codes come from revision notices, which the run checks itself).

update public.spc_product p
   set active = false
 where p.source_id = 'spc-pmda'
   and p.active
   and exists (select 1 from public.ingredient_term t
                where t.ingredient_id = p.ingredient_id and t.kind = 'code' and t.country_code = 'JP')
   and not exists (select 1 from public.ingredient_term t
                    where t.ingredient_id = p.ingredient_id and t.kind = 'code' and t.country_code = 'JP'
                      and left(upper(t.term), 7) = left(upper(split_part(p.national_id, '_', 2)), 7));
