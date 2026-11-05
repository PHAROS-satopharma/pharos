-- PHAROS — the notice list knows the language of each title (2026-11-05).
--
-- v_issue_table gave the title (the first notice's original title) without its language, so the list
-- could not mark a Japanese, Arabic or Finnish title with lang=…: screen readers read it with English
-- rules and the browser could not pick the right font. The view now also returns the first notice's
-- language as `lang`. Same columns as before plus one at the end; still security_invoker.

create or replace view v_issue_table with (security_invoker = true) as
select
  i.id,
  i.first_date,
  i.doc_type,
  i.title,
  i.status,
  i.class_only,
  i.is_backfill,
  ad.url                                             as link,
  ar.country_name                                    as anchor_country,
  ar.name                                            as anchor_regulator,
  (select array_agg(distinct r.country_name order by r.country_name)
     from issue_document idd
     join document d on d.id = idd.document_id
     join source s on s.id = d.source_id
     join regulator r on r.id = s.regulator_id
    where idd.issue_id = i.id)                       as countries,
  (select array_agg(distinct ing.inn_en order by ing.inn_en)
     from issue_ingredient ii join ingredient ing on ing.id = ii.ingredient_id
    where ii.issue_id = i.id)                        as ingredients,
  (select count(*) from issue_document idd where idd.issue_id = i.id) as copies,
  ad.lang                                            as lang
from issue i
left join document ad on ad.id = i.anchor_document_id
left join source asrc on asrc.id = ad.source_id
left join regulator ar on ar.id = asrc.regulator_id;
