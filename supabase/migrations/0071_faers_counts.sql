-- PHAROS — FDA adverse-event report counts per watched ingredient (2026-11-06).
--
-- collectors/faers.py (the weekly "PHAROS FAERS counts" workflow) asks openFDA to count the reports of the FDA
-- Adverse Event Reporting System (FAERS) for each active ingredient, over the last 8 complete calendar quarters
-- openFDA holds: the reports naming the ingredient, the reactions in them (the 100 most frequent of the whole
-- period), and the same for every drug together. It works out PRR, ROR, chi-squared and Evans' flag in Python
-- (faers.disproportion) and keeps them here. Only the collector writes; the team reads.
--
-- A reaction is kept by its name exactly as FDA publishes it (a MedDRA preferred term, in capitals). PHAROS holds
-- no MedDRA licence: no MedDRA code is stored, and no dictionary is built from these names. For the label tag the
-- name is matched to MeSH by its exact normalised name (coding_norm(), 0061) and mesh_listed() (0062) says which
-- label lists it; a name MeSH does not have is left unknown.

-- One row per ingredient: what was searched, the quarters counted, and when.
create table faers_ingredient (
  ingredient_id uuid primary key references ingredient (id) on delete cascade,
  searched      text not null,           -- the INN in capitals, searched exactly
  first_quarter date not null,           -- the first day of the oldest quarter counted
  last_quarter  date not null,           -- the first day of the newest
  reports       int  not null,           -- reports naming the ingredient, whole period
  all_reports   int  not null,           -- reports of every drug, whole period
  fetched_at    timestamptz not null default now(),
  check (first_quarter <= last_quarter)
);

-- The reports per quarter. complete: openFDA listed every reaction of that quarter's reports, so a reaction with no
-- count that quarter had none; otherwise it was below the most frequent and is not known.
create table faers_quarter (
  ingredient_id uuid not null references faers_ingredient (ingredient_id) on delete cascade,
  quarter       date not null check (extract(day from quarter) = 1 and extract(month from quarter) in (1, 4, 7, 10)),
  reports       int  not null,
  all_reports   int  not null,
  complete      boolean not null,
  primary key (ingredient_id, quarter)
);

-- The most frequent reactions of the whole period, with the 2×2 table's results.
create table faers_reaction (
  ingredient_id uuid not null references faers_ingredient (ingredient_id) on delete cascade,
  reaction      text not null,           -- exactly as FAERS gives it
  reports       int  not null,           -- a: reports of the ingredient with the reaction
  all_reports   int  not null,           -- a + c: reports of every drug with the reaction
  prr           double precision,        -- null where it would divide by zero
  prr_low       double precision,
  prr_high      double precision,
  ror           double precision,
  ror_low       double precision,
  ror_high      double precision,
  chi2          double precision,        -- with Yates' correction
  flagged       boolean not null,        -- Evans: a >= 3, PRR >= 2, chi-squared >= 4
  primary key (ingredient_id, reaction)
);

-- Each kept reaction's reports in each quarter it was listed.
create table faers_count (
  ingredient_id uuid not null,
  quarter       date not null,
  reaction      text not null,
  reports       int  not null,
  all_reports   int,                     -- every drug's; null when below every drug's most frequent that quarter
  primary key (ingredient_id, quarter, reaction),
  foreign key (ingredient_id, quarter) references faers_quarter (ingredient_id, quarter) on delete cascade,
  foreign key (ingredient_id, reaction) references faers_reaction (ingredient_id, reaction) on delete cascade
);

alter table faers_ingredient enable row level security;
alter table faers_quarter    enable row level security;
alter table faers_reaction   enable row level security;
alter table faers_count      enable row level security;
create policy faers_ingredient_read on faers_ingredient for select to authenticated using (my_role() is not null);
create policy faers_quarter_read    on faers_quarter    for select to authenticated using (my_role() is not null);
create policy faers_reaction_read   on faers_reaction   for select to authenticated using (my_role() is not null);
create policy faers_count_read      on faers_count      for select to authenticated using (my_role() is not null);

-- Section 06 of the Ingredients screen: the reactions, most reported first, with their reports per quarter (oldest
-- first; null when not known that quarter), the newest quarter's, the disproportion, and the label.
-- listed: 'our_label' or 'reference' (mesh_listed), 'not_listed' (MeSH has the name and a label is coded, but
-- neither lists it), or null (MeSH does not have the name, or no label is coded). Checks the role once and reads as
-- its owner, as ingredient_screen() does (0039): row by row it would run past the 8 seconds a request may take.
create function ingredient_faers(p_ingredient uuid)
returns table (reaction text, reports int, last_quarter int, quarters int[], all_reports int,
               prr double precision, prr_low double precision, prr_high double precision,
               ror double precision, ror_low double precision, ror_high double precision,
               chi2 double precision, flagged boolean, mesh_ui text, listed text)
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
              when coded.any_label then 'not_listed' end
    from r
    cross join coded
    left join per_q on per_q.reaction = r.reaction
    left join lateral (select mesh_listed(p_ingredient, r.ui) as src) l on true
   order by r.reports desc, r.reaction;
end $$;

revoke all on function ingredient_faers(uuid) from public, anon;
grant execute on function ingredient_faers(uuid) to authenticated;
