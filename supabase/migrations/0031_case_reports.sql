-- PHAROS — literature case reports and EMA's literature monitoring (2026-11-05).
--
-- A PubMed hit that looks like an individual case report starts a reporting clock: day zero is the day
-- PHAROS found it (the day the company knew of it, GVP VI); a valid serious case is reported within 15 days
-- and a non-serious one within 90. v_case_report lists the literature notices that look like case reports
-- (PubMed publication type "Case Reports", or "case report", "case series", "a case of" in the title) with
-- day zero and both dates.
--
-- mlm_entry keeps, from EMA's medical literature monitoring list (collectors/mlm.py, weekly), the group of
-- each watched ingredient EMA monitors itself. A watched ingredient with no row is not monitored by EMA, so
-- its literature cases are the company's to report.

create table mlm_entry (
  ingredient_id  uuid primary key references ingredient(id) on delete cascade,
  group_id       int  not null,
  group_name     text not null,
  named_group    boolean not null,                 -- the group bears the ingredient's name
  list_name      text not null,
  sha256         text not null,
  r2_key         text not null,
  stored_at      timestamptz not null default now()
);
alter table mlm_entry enable row level security;
create policy mlm_entry_read on mlm_entry for select to authenticated using (my_role() is not null);
revoke insert, update, delete, truncate on mlm_entry from anon, authenticated;

create view v_case_report with (security_invoker = true) as
select
  i.id                                                     as issue_id,
  i.title,
  i.status,
  d.url,
  d.lang,
  d.structured ->> 'pmid'                                  as pmid,
  d.structured ->> 'journal'                               as journal,
  case when coalesce(d.structured -> 'pubtype', '[]'::jsonb) ? 'Case Reports' then 'pubtype' else 'title' end
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
  and (coalesce(d.structured -> 'pubtype', '[]'::jsonb) ? 'Case Reports'
       or d.title_orig ~* '\m(case report|case reports|case series|a case of)\M');
