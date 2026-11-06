-- PHAROS — FAERS: "Not in our label" only when our label was read (2026-11-06).
--
-- ingredient_faers() (0071, 0078) tagged a reaction neither label names "not_listed", shown as "Not in our label",
-- whenever ANY label of the ingredient was coded. For an ingredient with no label of ours in English, only the
-- reference product's label is read, so the tag claimed something about a label nobody read (ivabradine, 6 Nov 2026:
-- 45 of its 100 reactions, headache and dizziness among them, said "Not in our label" while only a US generic label
-- was coded). Now:
--   our_label         our label names it, or a broader heading above it;
--   reference         the reference label does, and ours does not;
--   not_listed        our label is coded and neither label names it ("Not in our label");
--   not_in_reference  only the reference label is coded and it does not name it ("Not in the reference label");
--   null              MeSH does not have the name, or no label is coded.
-- The signature and the columns are unchanged.

create or replace function ingredient_faers(p_ingredient uuid)
returns table (reaction text, reports int, last_quarter int, quarters int[], all_reports int,
               prr double precision, prr_low double precision, prr_high double precision,
               ror double precision, ror_low double precision, ror_high double precision,
               chi2 double precision, flagged boolean, mesh_ui text, listed text,
               co_drug text, co_reports int, co_all_reports int)
language plpgsql stable security definer set search_path = public as $$
#variable_conflict use_column
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the FDA report counts.' using errcode = '42501';
  end if;
  return query
  with qs as (
    select q.quarter, q.complete from faers_quarter q where q.ingredient_id = p_ingredient),
  coded as (
    select exists (select 1 from label_coded lc where lc.ingredient_id = p_ingredient) as any_label,
           exists (select 1 from label_coded lc where lc.ingredient_id = p_ingredient
                                               and lc.source = 'our_label') as ours),
  r as (
    select fr.*,
           (select t.ui from mesh_term t where t.norm = coding_norm(fr.reaction) and t.norm <> ''
             order by t.preferred desc, t.ui limit 1) as ui
      from faers_reaction fr
     where fr.ingredient_id = p_ingredient),
  per_q as (
    select r.reaction,
           array_agg(coalesce(c.reports, case when qs.complete then 0 end) order by qs.quarter) as counts
      from r cross join qs
      left join faers_count c on c.ingredient_id = p_ingredient and c.quarter = qs.quarter
                             and c.reaction = r.reaction
     group by r.reaction)
  select r.reaction, r.reports, per_q.counts[cardinality(per_q.counts)], per_q.counts, r.all_reports,
         r.prr, r.prr_low, r.prr_high, r.ror, r.ror_low, r.ror_high, r.chi2, r.flagged, r.ui,
         case when r.ui is null then null
              when l.src is not null then l.src
              when coded.ours then 'not_listed'
              when coded.any_label then 'not_in_reference' end,
         r.co_drug, r.co_reports, r.co_all_reports
    from r
    cross join coded
    left join per_q on per_q.reaction = r.reaction
    left join lateral (select mesh_listed(p_ingredient, r.ui) as src) l on true
   order by r.reports desc, r.reaction;
end $$;

revoke all on function ingredient_faers(uuid) from public, anon;
grant execute on function ingredient_faers(uuid) to authenticated;
