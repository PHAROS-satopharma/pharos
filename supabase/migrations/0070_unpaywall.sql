-- PHAROS — legal open-access full text of the literature papers, found by Unpaywall (2026-11-06; validation row 22).
--
-- The daily step `python -m collectors.fulltext` (collect.yml, after Coding) asks Unpaywall for each literature
-- paper of the last year with a DOI and keeps its answer in document.structured.oa: is_oa, the best open
-- location's url, pdf_url, license, version (published, accepted or submitted) and host_type (publisher or
-- repository), the PDFs to try for a case, and when it was checked. Nothing here changes how it is stored.
--
-- 1. paper_state(p_documents uuid[]) (0044) also returns open_access for each paper: {url, license, version,
--    host_type} when Unpaywall found a free full text whose address is http(s), else null. Everything else it
--    returns is as 0044 wrote it, and so are its signature, its grants and its check (screen_reader(); at most
--    1,000 papers a call). The Ingredients screen shows "Free full text" with the licence and version beside the
--    paper. ingredient_papers() is left as it is: ingredient_screen() reads it by column position.

create or replace function paper_state(p_documents uuid[]) returns jsonb
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
           'due_nonserious', z.day_zero + 90,
           'open_access', case when jsonb_typeof(d.structured -> 'oa') = 'object'
                                    and d.structured -> 'oa' ->> 'is_oa' = 'true'
                                    and d.structured -> 'oa' ->> 'url' ~* '^https?://[^[:space:]]+$'
                                 then jsonb_build_object(
                                        'url', d.structured -> 'oa' ->> 'url',
                                        'license', nullif(btrim(d.structured -> 'oa' ->> 'license'), ''),
                                        'version', case when d.structured -> 'oa' ->> 'version'
                                                             in ('published', 'accepted', 'submitted')
                                                        then d.structured -> 'oa' ->> 'version' end,
                                        'host_type', case when d.structured -> 'oa' ->> 'host_type'
                                                               in ('publisher', 'repository')
                                                          then d.structured -> 'oa' ->> 'host_type' end)
                                 else 'null'::jsonb end)), '{}'::jsonb)
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
