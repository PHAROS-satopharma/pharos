-- A possible case report must name its ingredient (owner, 8 Nov 2026: "stop flagging case reports that don't name
-- the ingredient").
-- Until 7 Nov 2026 the literature was searched in whole papers and by drug class: on 7 Nov 2,516 papers were
-- flagged as possible case reports, each with a 15-day clock, and only 420 of them named their ingredient in the
-- title or abstract. collectors/case_names.py now checks each flagged paper once (structured.names_checked) and
-- clears the flag of one whose title and abstract name none of the ingredients whose name searches found it
-- (structured.case_report becomes JSON null; the old flag is kept as structured.case_report_was). The literature
-- runs do this after their searches, as they need PubMed and Europe PMC.
--   1. Here, at once, the papers only drug-class words found: they name no ingredient, so nothing is asked.
--   2. v_case_report (0031) follows structured.case_report, as the Ingredients screen (paper_state, 0044 and 0070)
--      and the daily message (Store.case_report_papers_since) already do: a cleared flag is not a case report.
--      A paper with no case_report key at all (none is left since 0044) is still judged by its type and title.

update document d
   set structured = d.structured || jsonb_build_object(
         'case_report', 'null'::jsonb,
         'case_report_was', d.structured -> 'case_report',
         'names_checked', to_char((now() at time zone 'Africa/Cairo')::date, 'YYYY-MM-DD'))
  from source s
 where s.id = d.source_id
   and s.kind = 'literature'
   and jsonb_typeof(d.structured -> 'case_report') = 'object'
   and d.structured -> 'names_checked' is null
   and not exists (select 1
                     from jsonb_array_elements(case when jsonb_typeof(d.structured -> 'queries') = 'array'
                                                    then d.structured -> 'queries' else '[]'::jsonb end) q
                    where q ->> 'kind' = 'name');

create or replace view v_case_report with (security_invoker = true) as
select
  i.id                                                     as issue_id,
  i.title,
  i.status,
  d.url,
  d.lang,
  d.structured ->> 'pmid'                                  as pmid,
  d.structured ->> 'journal'                               as journal,
  case when jsonb_typeof(d.structured -> 'case_report') = 'object' then d.structured -> 'case_report' ->> 'reason'
       when coalesce(d.structured -> 'pubtype', '[]'::jsonb) ? 'Case Reports' then 'pubtype' else 'title' end
                                                           as flagged_by,
  z.day_zero,
  z.day_zero + 15                                          as serious_due,
  z.day_zero + 90                                          as nonserious_due,
  (select array_agg(ing.inn_en order by ing.inn_en)
     from issue_ingredient ii join ingredient ing on ing.id = ii.ingredient_id
    where ii.issue_id = i.id)                              as ingredients,
  (select array_agg(ing.inn_en order by ing.inn_en)
     from issue_ingredient ii join ingredient ing on ing.id = ii.ingredient_id
    where ii.issue_id = i.id
      and not exists (select 1 from mlm_entry m where m.ingredient_id = ing.id)) as not_monitored
from issue i
join document d on d.id = i.anchor_document_id
cross join lateral (select (d.first_seen_at at time zone 'Africa/Cairo')::date as day_zero) z
where i.doc_type = 'literature'
  and case when d.structured ? 'case_report' then jsonb_typeof(d.structured -> 'case_report') = 'object'
           else coalesce(d.structured -> 'pubtype', '[]'::jsonb) ? 'Case Reports'
                or d.title_orig ~* '\m(case report|case reports|case series|a case of)\M' end;
