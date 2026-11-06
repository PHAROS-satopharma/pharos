-- PHAROS — FAERS: the drug shown with a flagged reaction must be over-represented in its reports (2026-11-06).
--
-- 0076 named the drug most often reported with each flagged reaction. Some are the explanation (relugolix in 199 of
-- carvedilol's 239 HOT FLUSH reports); others are drugs often taken with the ingredient whatever the reaction (aspirin,
-- furosemide or amlodipine, named in 25-43% of a reaction's reports). collectors/faers.py now shows a
-- drug only when it is named in at least 3 of the reaction's reports and its share of them is at least twice its
-- share of all the ingredient's reports over the period; the most reported such drug is kept.
--
-- co_all_reports: how many of all the ingredient's reports over the period name co_drug, the base its share is
-- weighed against; null whenever co_drug is.

alter table faers_reaction
  add column co_all_reports int check (co_all_reports >= 0);

-- The drugs kept before were not weighed: none is shown until the next FAERS run weighs them.
update faers_reaction set co_drug = null, co_reports = null where co_drug is not null;

-- ingredient_faers() as in 0076, with the new column at the end.
drop function ingredient_faers(uuid);

create function ingredient_faers(p_ingredient uuid)
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
    select exists (select 1 from label_coded lc where lc.ingredient_id = p_ingredient) as any_label),
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
              when coded.any_label then 'not_listed' end,
         r.co_drug, r.co_reports, r.co_all_reports
    from r
    cross join coded
    left join per_q on per_q.reaction = r.reaction
    left join lateral (select mesh_listed(p_ingredient, r.ui) as src) l on true
   order by r.reports desc, r.reaction;
end $$;

revoke all on function ingredient_faers(uuid) from public, anon;
grant execute on function ingredient_faers(uuid) to authenticated;
