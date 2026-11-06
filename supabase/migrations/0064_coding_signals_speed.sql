-- PHAROS — the coded-term counts of 0062, fast (2026-11-06).
--
-- 0062's functions ran as the person asking (security invoker), so every paper, link and MeSH heading they read was
-- checked against its row-level policy one row at a time: carvedilol's counts took more than the 8 seconds a
-- signed-in request may run, and section 05 of the Ingredients screen showed an error. They now check the person's
-- role once, as ingredient_screen() does (0039), and read as their owner. issue_ingredient gets the index by
-- ingredient that every per-ingredient count needs.

create index if not exists issue_ingredient_ingredient_idx on issue_ingredient (ingredient_id);

create or replace function coding_check() returns void language plpgsql stable security definer
set search_path = public as $$
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the coded reactions.' using errcode = '42501';
  end if;
end $$;

alter function ingredient_coded_terms(uuid) security definer;

create or replace function ingredient_mesh_counts(p_ingredient uuid, p_from date, p_to date)
returns table (ui text, name text, categories text[], cases_now int, cases_before int, papers_now int,
               papers_before int, listed text)
language plpgsql stable security definer set search_path = public as $$
begin
  perform coding_check();
  return query
  with s as (select p_from - (p_to - p_from + 1) as b_from, p_from - 1 as b_to),
  t as (select * from ingredient_coded_terms(p_ingredient)),
  n as (
    select t.ui,
           count(distinct t.item) filter (where t.kind = 'case'  and t.day between p_from and p_to)       as cn,
           count(distinct t.item) filter (where t.kind = 'case'  and t.day between s.b_from and s.b_to)   as cb,
           count(distinct t.item) filter (where t.kind = 'paper' and t.day between p_from and p_to)       as pn,
           count(distinct t.item) filter (where t.kind = 'paper' and t.day between s.b_from and s.b_to)   as pb
      from t, s
     group by t.ui)
  select d.ui, d.name, mesh_category(d.trees), n.cn::int, n.cb::int, n.pn::int, n.pb::int,
         mesh_listed(p_ingredient, d.ui)
    from n join mesh_descriptor d on d.ui = n.ui
   where n.cn + n.cb + n.pn + n.pb > 0
   order by n.cn + n.pn desc, n.cb + n.pb desc, d.name;
end $$;

create or replace function ingredient_topic_counts(p_ingredient uuid, p_from date, p_to date)
returns table (topic text, name text, cases_now int, cases_before int, papers_now int, papers_before int,
               terms text[])
language plpgsql stable security definer set search_path = public as $$
begin
  perform coding_check();
  return query
  with s as (select p_from - (p_to - p_from + 1) as b_from, p_from - 1 as b_to),
  t as (select ct.*, td.topic_id from ingredient_coded_terms(p_ingredient) ct
          join topic_descriptor td on td.ui = ct.ui)
  select st.id, st.name,
         (count(distinct t.item) filter (where t.kind = 'case'  and t.day between p_from and p_to))::int,
         (count(distinct t.item) filter (where t.kind = 'case'  and t.day between s.b_from and s.b_to))::int,
         (count(distinct t.item) filter (where t.kind = 'paper' and t.day between p_from and p_to))::int,
         (count(distinct t.item) filter (where t.kind = 'paper' and t.day between s.b_from and s.b_to))::int,
         array_agg(distinct d.name order by d.name)
    from t cross join s
    join safety_topic st on st.id = t.topic_id
    join mesh_descriptor d on d.ui = t.ui
   where t.day between s.b_from and p_to
   group by st.id, st.name, st.sort
   order by st.sort;
end $$;

-- mesh_listed and ingredient_coded_terms now read as their owner: only a member of the team may call them.
create or replace function mesh_listed(p_ingredient uuid, p_ui text) returns text language sql stable
security definer set search_path = public as $$
  select lm.source
    from label_mesh lm
    join mesh_descriptor l on l.ui = lm.ui
    join mesh_descriptor r on r.ui = p_ui
   where my_role() is not null
     and lm.ingredient_id = p_ingredient
     and exists (select 1 from unnest(r.trees) rt, unnest(l.trees) lt where rt = lt or rt like lt || '.%')
   order by lm.source = 'our_label' desc
   limit 1
$$;

revoke all on function coding_check() from public, anon;
grant execute on function coding_check() to authenticated;
revoke all on function ingredient_coded_terms(uuid) from authenticated;   -- only through the counts now
