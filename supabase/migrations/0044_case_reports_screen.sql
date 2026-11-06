-- PHAROS — case reports in the literature, on the Ingredients screen and in the weekly report (2026-11-06,
-- Dr Sama's review, point 7).
--
-- A paper that reports a case with one of our products starts a clock the day PHAROS finds it: a valid serious
-- case reaches the Egyptian Drug Authority within 15 days, a non-serious one within 90. The notice page that
-- showed this (v_case_report, 0031) was removed in November 2026; the Ingredients screen now shows it beside
-- each paper, and the weekly report lists it. The collector flags each paper as it is stored
-- (document.structured.case_report, collectors/parsers/pubmed.py: {"reason": "pubtype"} when PubMed types it
-- Case Reports, {"reason": "title"} when its title says "case report", "case series" or "a case of", else
-- null); this migration flags the papers stored before it, with the same words as v_case_report.
--
-- 1. The backfill: every document of a literature source without the flag gets it. document has no audit
--    trigger, and nothing else in structured changes.
-- 2. paper_state(p_documents uuid[]) returns jsonb: keyed by document id, {issue_id, issue_status, decision,
--    case_report, day_zero, due_serious, due_nonserious} for each paper asked for. The notice is the one the
--    paper is filed under (a link not 'suggested', its anchor first), the decision its latest review_event
--    (to_status, person, at, comment), exactly as ingredient_screen() (0039) gives them for a notice. Day zero
--    is the Cairo day PHAROS found the paper; the two dates are day zero + 15 and + 90. A paper stored without
--    the flag is judged on the fly. At most 1,000 papers a call (22023); an unknown document has no entry.
--    ingredient_screen() reads ingredient_papers() by column position, so that function is left exactly as it
--    is and the screen asks this one for the papers it shows, 50 at a time.
-- 3. mlm_monitored(p_ingredient uuid) returns boolean: true while EMA's medical literature monitoring list
--    (mlm_entry, read weekly by collectors/mlm.py) has a row for the ingredient. With no row, the cases in the
--    literature are the company's own to report, and the screen and the report say so.
-- Both answer a member of the team signed in to the app and the weekly report on its direct connection
-- (screen_reader(), 0040); anyone else is refused (42501). Signed-out visitors cannot call them.

-- ───────────────────────────── 1. the papers stored before the flag ─────────────────────────────
update document d
   set structured = coalesce(d.structured, '{}'::jsonb)
                    || jsonb_build_object('case_report',
                         case when coalesce(d.structured -> 'pubtype', '[]'::jsonb) ? 'Case Reports'
                                then '{"reason": "pubtype"}'::jsonb
                              when d.title_orig ~* '\m(case report|case reports|case series|a case of)\M'
                                then '{"reason": "title"}'::jsonb
                              else 'null'::jsonb end)
  from source s
 where s.id = d.source_id
   and s.kind = 'literature'
   and d.structured -> 'case_report' is null;

-- ───────────────────────────── 2. the state of each paper ─────────────────────────────
create function paper_state(p_documents uuid[]) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_out jsonb;
begin
  if not screen_reader() then
    raise exception 'Only a member of the team can screen an ingredient.' using errcode = '42501';
  end if;
  if coalesce(cardinality(p_documents), 0) > 1000 then
    raise exception 'Ask for at most 1,000 papers at a time.' using errcode = '22023';
  end if;
  select coalesce(jsonb_object_agg(d.id::text, jsonb_build_object(
           'issue_id', iss.id,
           'issue_status', iss.status,
           'decision', dec.j,
           'case_report', case when d.structured -> 'case_report' is not null then d.structured -> 'case_report'
                               when coalesce(d.structured -> 'pubtype', '[]'::jsonb) ? 'Case Reports'
                                 then '{"reason": "pubtype"}'::jsonb
                               when d.title_orig ~* '\m(case report|case reports|case series|a case of)\M'
                                 then '{"reason": "title"}'::jsonb
                               else 'null'::jsonb end,
           'day_zero', z.day_zero,
           'due_serious', z.day_zero + 15,
           'due_nonserious', z.day_zero + 90)), '{}'::jsonb)
    into v_out
    from document d
    cross join lateral (select (d.first_seen_at at time zone 'Africa/Cairo')::date as day_zero) z
    left join lateral (
      select i.id, i.status
        from issue_document idd
        join issue i on i.id = idd.issue_id
       where idd.document_id = d.id
         and idd.method <> 'suggested'
       order by coalesce(i.anchor_document_id = d.id, false) desc, i.created_at
       limit 1
    ) iss on true
    left join lateral (
      select jsonb_build_object('to_status', re.to_status, 'person', p.full_name,
                                'at', re.created_at, 'comment', re.comment) as j
        from review_event re
        join person p on p.id = re.person_id
       where re.issue_id = iss.id
       order by re.created_at desc, re.id desc
       limit 1
    ) dec on true
   where d.id = any (p_documents);
  return v_out;
end $$;
revoke all on function paper_state(uuid[]) from public, anon;
grant execute on function paper_state(uuid[]) to authenticated;

-- ───────────────────────────── 3. does EMA read the literature for this ingredient ─────────────────────────────
create function mlm_monitored(p_ingredient uuid) returns boolean
language plpgsql stable security definer set search_path = public as $$
begin
  if not screen_reader() then
    raise exception 'Only a member of the team can screen an ingredient.' using errcode = '42501';
  end if;
  return exists (select 1 from mlm_entry e where e.ingredient_id = p_ingredient);
end $$;
revoke all on function mlm_monitored(uuid) from public, anon;
grant execute on function mlm_monitored(uuid) to authenticated;
