-- PHAROS — the EURD list and the PSUR builder (2026-11-05).
--
-- EMA's List of Union reference dates (EURD list) sets, for each active substance, how often its PSURs are
-- due, the data lock point (DLP) and the submission date. collectors/eurd.py reads the list each day and
-- keeps here the rows that name a watched ingredient, alone or in a combination; every row is replaced when
-- EMA publishes a new list, so the table always holds one list (its version, date and SHA-256 on each row).
--
-- The PSUR page reads it to choose the reporting interval, then builds the PBRER sections PHAROS can fill
-- from its own records. screening_summary() gives the screening annex: each source, how often it was read
-- in the interval and how often that failed, counted the same way as the screening log (0018).

create table eurd_entry (
  eurd_id                 int  not null,                 -- EMA's row ID, e.g. 1911 for lornoxicam
  ingredient_id           uuid not null references ingredient(id) on delete cascade,
  substance               text not null,                 -- as EMA writes it: "ibuprofen / pseudoephedrine"
  combination             boolean not null default false,
  eurd                    text,                          -- the reference date, often "Not available*"
  frequency               text,                          -- "7 years", "6 months"
  dlp                     date,
  submission_date         date,
  next_dlp                date,                          -- only for frequencies under a year
  next_submission_date    date,
  generics_psur_required  boolean,                       -- null when EMA leaves it blank
  published               date,
  notes                   text,
  procedure               text,                          -- PSUSA/00001911/203112
  next_procedure          text,
  prac_rapporteur         text,
  lead_ms                 text,
  cap                     text,
  nap                     text,
  list_version            text not null,                 -- EMA/630645/2012 Rev.165
  list_date               date,
  sha256                  text not null,
  r2_key                  text not null,
  stored_at               timestamptz not null default now(),
  primary key (eurd_id, ingredient_id)
);
create index on eurd_entry (ingredient_id);

alter table eurd_entry enable row level security;
create policy eurd_entry_read on eurd_entry for select to authenticated using (my_role() is not null);
revoke insert, update, delete, truncate on eurd_entry from anon, authenticated;

create function screening_summary(p_from date, p_to date)
returns table (source_id text, regulator text, country text, kind source_kind, runs bigint, ok_runs bigint,
               failed_runs bigint, days_read bigint, items_seen bigint, items_matched bigint,
               first_run timestamptz, last_run timestamptz)
language plpgsql stable security definer set search_path = public as $$
begin
  if my_role() is null then
    raise exception 'Sign in to read the screening summary.' using errcode = '42501';
  end if;
  if p_from is null or p_to is null or p_to < p_from then
    raise exception 'Choose a period whose end is on or after its start.' using errcode = '22023';
  end if;
  return query
    select s.id, r.name, r.country_name, s.kind,
           count(sr.id),
           count(sr.id) filter (where not source_run_failed(sr.error)),
           count(sr.id) filter (where source_run_failed(sr.error)),
           count(distinct (sr.started_at at time zone 'Africa/Cairo')::date)
             filter (where not source_run_failed(sr.error)),
           coalesce(sum(sr.items_seen), 0)::bigint,
           coalesce(sum(sr.items_matched), 0)::bigint,
           min(sr.started_at), max(sr.started_at)
      from source s
      join regulator r on r.id = s.regulator_id
      left join source_run sr
        on sr.source_id = s.id
       and sr.started_at >= (p_from::timestamp at time zone 'Africa/Cairo')
       and sr.started_at <  ((p_to + 1)::timestamp at time zone 'Africa/Cairo')
     group by s.id, r.name, r.country_name, s.kind
     order by r.country_name, s.id;
end $$;

revoke all on function screening_summary(date, date) from public, anon;
grant execute on function screening_summary(date, date) to authenticated;
