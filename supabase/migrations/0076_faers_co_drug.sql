-- PHAROS — FAERS: the drug most often named with each flagged reaction (2026-11-06).
--
-- A FAERS report names every drug the patient took, and openFDA counts a report for the ingredient whatever role
-- the ingredient had in it. A reaction caused by a drug often taken with the ingredient can therefore look
-- disproportionate for the ingredient: carvedilol's HOT FLUSH (PRR 4.1) came from 199 of 239 reports that named
-- the prostate-cancer drug relugolix (Orgovyx) as the suspect. For each flagged reaction collectors/faers.py now
-- asks openFDA which other drug those reports name most, and keeps it here; section 06 shows it under the flag.
--
-- co_drug: the generic name as openFDA gives it (patient.drug.openfda.generic_name), never the ingredient itself
-- or one of its salts; co_reports: how many of the reaction's reports naming the ingredient also name it. Both are
-- null for a reaction that is not flagged, or when no other drug is named.

alter table faers_reaction
  add column co_drug    text,
  add column co_reports int check (co_reports >= 0);

-- ingredient_faers() as in 0071, with the two columns at the end.
drop function ingredient_faers(uuid);

create function ingredient_faers(p_ingredient uuid)
returns table (reaction text, reports int, last_quarter int, quarters int[], all_reports int,
               prr double precision, prr_low double precision, prr_high double precision,
               ror double precision, ror_low double precision, ror_high double precision,
               chi2 double precision, flagged boolean, mesh_ui text, listed text,
               co_drug text, co_reports int)
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
         r.co_drug, r.co_reports
    from r
    cross join coded
    left join per_q on per_q.reaction = r.reaction
    left join lateral (select mesh_listed(p_ingredient, r.ui) as src) l on true
   order by r.reports desc, r.reaction;
end $$;

revoke all on function ingredient_faers(uuid) from public, anon;
grant execute on function ingredient_faers(uuid) to authenticated;
