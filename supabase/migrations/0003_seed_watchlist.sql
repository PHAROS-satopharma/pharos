-- PHAROS — seed watchlist: the NSAID class and lornoxicam.
-- Plain SQL, idempotent (on conflict do nothing); applies on plain Postgres 16 as well as Supabase.
-- Every term carries source 'seed' and verified_by null: an admin verifies each one in the app.
-- Matching modes (collectors/matching.py): stem = word start + up to 6 letters; exact = whole word;
-- substring = anywhere (Japanese, Korean). Short acronyms that are also ordinary words elsewhere
-- (AINS ~ "ainsi", FANS ~ "fans", AINE ~ "aîné") are exact; class terms only apply in their own language.

-- ───────────── the NSAID class ─────────────
insert into drug_class (code, name_en)
values ('NSAID', 'Non-steroidal anti-inflammatory drugs')
on conflict (code) do nothing;

insert into class_term (class_id, lang, term, mode)
select c.id, v.lang, v.term, v.mode::match_mode
  from drug_class c
 cross join (values
    ('en', 'NSAID', 'stem'),
    ('en', 'non-steroidal anti-inflammatory', 'stem'),
    ('en', 'nonsteroidal anti-inflammatory', 'stem'),
    ('de', 'NSAR', 'stem'),
    ('de', 'nichtsteroidale Antirheumatika', 'stem'),
    ('de', 'nichtsteroidale Antiphlogistika', 'stem'),
    ('fr', 'AINS', 'exact'),
    ('fr', 'anti-inflammatoires non stéroïdiens', 'stem'),
    ('it', 'FANS', 'exact'),
    ('it', 'antinfiammatori non steroidei', 'stem'),
    ('es', 'AINE', 'exact'),
    ('es', 'antiinflamatorios no esteroideos', 'stem'),
    ('pt', 'AINE', 'exact'),
    ('pt', 'anti-inflamatórios não esteroides', 'stem'),
    ('nl', 'NSAID', 'stem'),
    ('nl', 'ontstekingsremmende pijnstillers', 'stem'),
    ('da', 'NSAID', 'stem'),
    ('da', 'NSAID-præparater', 'stem'),
    ('nb', 'NSAID', 'stem'),
    ('nb', 'NSAID-preparater', 'stem'),
    ('sv', 'NSAID', 'stem'),
    ('sv', 'NSAID-preparat', 'stem'),
    ('fi', 'tulehduskipulääke', 'stem'),
    ('fi', 'tulehduskipulääkk', 'stem'),          -- gradation: tulehduskipulääkkeet, -lääkkeiden
    ('is', 'bólgueyðandi gigtarlyf', 'stem'),
    ('ja', '非ステロイド性抗炎症薬', 'substring'),
    ('ko', '비스테로이드성 소염진통제', 'substring'),
    ('ar', 'مضادات الالتهاب غير الستيرويدية', 'stem')
 ) as v(lang, term, mode)
 where c.code = 'NSAID'
on conflict (class_id, lang, term) do nothing;

-- ───────────── lornoxicam (ATC M01AC05, Wikidata Q2734874) ─────────────
insert into ingredient (inn_en, atc_code, wikidata_qid, active)
values ('lornoxicam', 'M01AC05', 'Q2734874', true)
on conflict (atc_code) do nothing;

insert into ingredient_term (ingredient_id, lang, term, kind, mode, exclusions, source)
select i.id, v.lang, v.term, v.kind::term_kind, v.mode::match_mode, v.exclusions::text[], 'seed'
  from ingredient i
 cross join (values
    ('en', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('de', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('fr', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('it', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('es', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('pt', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('nl', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('da', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('sv', 'lornoxikam',    'inn', 'stem', '{tenoxikam,meloxikam,piroxikam,tenoxicam,meloxicam,piroxicam}'),
    ('nb', 'lornoksikam',   'inn', 'stem', '{tenoksikam,meloksikam,piroksikam,tenoxicam,meloxicam,piroxicam}'),
    ('fi', 'lornoksikaami', 'inn', 'stem', '{tenoksikaami,meloksikaami,piroksikaami,tenoxicam,meloxicam,piroxicam}'),
    ('is', 'lornoxicam',    'inn', 'stem', '{tenoxicam,meloxicam,piroxicam}'),
    ('ja', 'ロルノキシカム',  'inn', 'substring', '{テノキシカム,メロキシカム,ピロキシカム}'),
    ('ko', '로르녹시캄',      'inn', 'substring', '{테녹시캄,멜록시캄,피록시캄}'),
    ('ar', 'لورنوكسيكام',    'inn', 'stem', '{تينوكسيكام,ميلوكسيكام,بيروكسيكام}'),
    -- Xefo, the originator brand, in every screened EU/EEA language
    ('en', 'Xefo', 'brand', 'exact', '{}'),
    ('de', 'Xefo', 'brand', 'exact', '{}'),
    ('fr', 'Xefo', 'brand', 'exact', '{}'),
    ('it', 'Xefo', 'brand', 'exact', '{}'),
    ('es', 'Xefo', 'brand', 'exact', '{}'),
    ('pt', 'Xefo', 'brand', 'exact', '{}'),
    ('nl', 'Xefo', 'brand', 'exact', '{}'),
    ('da', 'Xefo', 'brand', 'exact', '{}'),
    ('sv', 'Xefo', 'brand', 'exact', '{}'),
    ('nb', 'Xefo', 'brand', 'exact', '{}'),
    ('fi', 'Xefo', 'brand', 'exact', '{}'),
    ('is', 'Xefo', 'brand', 'exact', '{}')
 ) as v(lang, term, kind, mode, exclusions)
 where i.atc_code = 'M01AC05'
on conflict (ingredient_id, lang, term) do nothing;

insert into ingredient_class (ingredient_id, class_id)
select i.id, c.id from ingredient i, drug_class c
 where i.atc_code = 'M01AC05' and c.code = 'NSAID'
on conflict do nothing;
