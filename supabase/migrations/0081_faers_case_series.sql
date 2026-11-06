-- PHAROS — FAERS: a flag that stands only on one repeated case series (2026-11-06).
--
-- One patient can be reported to FDA hundreds of times: every follow-up is a report, and a case published in a
-- journal is filed by each company that sells a drug named in it. Such a series lists the same long run of
-- reactions each time, so each of them can look disproportionate for every drug the patient took. Paracetamol
-- carried 14 unrelated flags (lupus, pemphigus, hand deformity...) in reports also naming leflunomide.
--
-- For each flagged reaction collectors/faers.py finds the largest group of its reports that could be one patient:
-- one sex and an age in years within a year of one age (ages under 2 left out), when that group is at least a
-- quarter of the reaction's reports. When the reaction would no longer stand out without the group, the flag is
-- kept and marked: series_reports is the group's size, series_age its middle age and series_sex its sex (E2B:
-- 1 male, 2 female). All three are null otherwise.

alter table faers_reaction
  add column series_reports int check (series_reports >= 0),
  add column series_age     int check (series_age >= 0),
  add column series_sex     text check (series_sex in ('1', '2'));

-- ingredient_faers() as in 0080, with the three columns at the end (a new return type: dropped and made again).
drop function ingredient_faers(uuid);

create function ingredient_faers(p_ingredient uuid)
returns table (reaction text, reports int, last_quarter int, quarters int[], all_reports int,
               prr double precision, prr_low double precision, prr_high double precision,
               ror double precision, ror_low double precision, ror_high double precision,
               chi2 double precision, flagged boolean, mesh_ui text, listed text,
               co_drug text, co_reports int, co_all_reports int,
               series_reports int, series_age int, series_sex text)
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
         r.co_drug, r.co_reports, r.co_all_reports, r.series_reports, r.series_age, r.series_sex
    from r
    cross join coded
    left join per_q on per_q.reaction = r.reaction
    left join lateral (select mesh_listed(p_ingredient, r.ui) as src) l on true
   order by r.reports desc, r.reaction;
end $$;

revoke all on function ingredient_faers(uuid) from public, anon;
grant execute on function ingredient_faers(uuid) to authenticated;
