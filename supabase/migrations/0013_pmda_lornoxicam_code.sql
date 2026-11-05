-- Japan's label watch finds an ingredient's package inserts from its PMDA 一般名 code (a code term,
-- country JP). Lornoxicam (M01AC05) had none, so Japan watched nothing for it. Its code is 1149036
-- (https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/1149036, checked 5 Nov 2026):
-- ロルカム錠 (Taisho) and ロルノキシカム錠「KO」 (Kotobuki). New ingredients get theirs on the
-- Ingredients page. Exact match, so the number alone is never read as a mention in a notice.
insert into ingredient_term (ingredient_id, lang, country_code, term, kind, mode, source)
select i.id, 'ja', 'JP', '1149036', 'code', 'exact', 'pmda'
  from ingredient i
 where i.atc_code = 'M01AC05'
on conflict (ingredient_id, lang, term) do nothing;
