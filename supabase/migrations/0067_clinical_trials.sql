-- PHAROS — clinical trials of each watched ingredient, from ClinicalTrials.gov (2026-11-06).
--
-- collectors/trials.py (the weekly "PHAROS clinical trials" workflow) asks ClinicalTrials.gov API v2 for the
-- studies whose interventions name each active ingredient (its English names), keeps each study once however many
-- ingredients it names, links it to them, and keeps the adverse-event tables of its posted results. Only the
-- collector writes; a member of the team reads.
--
--   trial            one study: what the registry says of it, as published. status_changed_on is the Cairo day
--                    PHAROS first saw a status different from the one it kept (never set the first time a study
--                    is kept), with the status before it.
--   trial_ingredient which ingredient's search found which study.
--   trial_event      the serious and other adverse events of a study's results: one row per term and organ
--                    system, summed over the groups (every arm, the comparators and placebo too), with each
--                    group's numbers in groups ([{group, affected, at_risk}]). The terms are the sponsor's words
--                    as published (usually MedDRA terms): shown as they are, never made into a dictionary.
--   trial_search     when each ingredient was last searched, with which names, and how many studies it found.
--
-- ingredient_trials(p_ingredient) answers section 07 of the Ingredients screen: the trials, newest update first,
-- each flagged when its status changed or its results were first posted in the last 90 days, and the serious
-- adverse events reported by most participants across the trials with results.

create table trial (
  nct_id            text primary key check (nct_id ~ '^NCT[0-9]{8}$'),
  title             text not null,
  phase             text[],                  -- as published: {PHASE2,PHASE3}, {NA}, {EARLY_PHASE1}
  status            text not null,           -- overall status as published: RECRUITING, COMPLETED …
  previous_status   text,
  status_changed_on date,
  start_date        text check (start_date ~ '^\d{4}-\d{2}(-\d{2})?$'),       -- a day or a month, as published
  completion_date   text check (completion_date ~ '^\d{4}-\d{2}(-\d{2})?$'),
  sponsor           text,                    -- the lead sponsor
  enrolment         int check (enrolment >= 0),
  enrolment_type    text,                    -- ACTUAL or ESTIMATED
  has_results       boolean not null default false,
  results_posted_on date,                    -- results first posted
  last_update_on    date,                    -- last update posted: a study is fetched again when it changes
  fetched_at        timestamptz not null default now()
);

create table trial_ingredient (
  ingredient_id uuid not null references ingredient (id) on delete cascade,
  nct_id        text not null references trial (nct_id) on delete cascade,
  linked_at     timestamptz not null default now(),
  primary key (ingredient_id, nct_id)
);
create index trial_ingredient_nct_idx on trial_ingredient (nct_id);

create table trial_event (
  nct_id       text not null references trial (nct_id) on delete cascade,
  serious      boolean not null,
  term         text not null,
  organ_system text not null default '',
  affected     int not null check (affected >= 0),
  at_risk      int check (at_risk >= 0),
  groups       jsonb not null default '[]',
  primary key (nct_id, serious, term, organ_system)
);

create table trial_search (
  ingredient_id uuid primary key references ingredient (id) on delete cascade,
  names         text[] not null,
  trials        int not null,
  searched_at   timestamptz not null default now()
);

alter table trial            enable row level security;
alter table trial_ingredient enable row level security;
alter table trial_event      enable row level security;
alter table trial_search     enable row level security;
create policy trial_read            on trial            for select to authenticated using (my_role() is not null);
create policy trial_ingredient_read on trial_ingredient for select to authenticated using (my_role() is not null);
create policy trial_event_read      on trial_event      for select to authenticated using (my_role() is not null);
create policy trial_search_read     on trial_search     for select to authenticated using (my_role() is not null);

-- Section 07 of the Ingredients screen. Checks the role once and reads as its owner, as ingredient_screen() (0039)
-- and the coded-term counts (0064) do.
create function ingredient_trials(p_ingredient uuid) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_since date := (now() at time zone 'Africa/Cairo')::date - 90;
  v_out   jsonb;
begin
  if my_role() is null then
    raise exception 'Only a member of the team can read the clinical trials.' using errcode = '42501';
  end if;

  with t as (
    select tr.*,
           coalesce(tr.results_posted_on >= v_since, false)  as new_results,
           coalesce(tr.status_changed_on >= v_since, false) as status_changed
      from trial_ingredient ti
      join trial tr on tr.nct_id = ti.nct_id
     where ti.ingredient_id = p_ingredient
  ),
  ev as (
    select lower(e.term) as k,
           mode() within group (order by e.term)                          as term,
           array_agg(distinct e.organ_system) filter (where e.organ_system <> '') as organ_systems,
           count(distinct e.nct_id)::int                                  as trials,
           sum(e.affected)::int                                           as affected,
           sum(e.at_risk)::int                                            as at_risk
      from t join trial_event e on e.nct_id = t.nct_id and e.serious
     where t.has_results
     group by lower(e.term)
    having sum(e.affected) > 0
     order by sum(e.affected) desc, count(distinct e.nct_id) desc, lower(e.term)
     limit 15
  )
  select jsonb_build_object(
           'searched', (select jsonb_build_object('at', s.searched_at, 'names', s.names, 'trials', s.trials)
                          from trial_search s where s.ingredient_id = p_ingredient),
           'with_results', (select count(*) from t where t.has_results),
           'recent', (select count(*) from t where t.new_results or t.status_changed),
           'trials', coalesce((select jsonb_agg(jsonb_build_object(
                         'nct_id', t.nct_id, 'title', t.title, 'phase', t.phase, 'status', t.status,
                         'previous_status', t.previous_status, 'status_changed_on', t.status_changed_on,
                         'start_date', t.start_date, 'completion_date', t.completion_date, 'sponsor', t.sponsor,
                         'enrolment', t.enrolment, 'enrolment_type', t.enrolment_type,
                         'has_results', t.has_results, 'results_posted_on', t.results_posted_on,
                         'last_update_on', t.last_update_on, 'new_results', t.new_results,
                         'status_changed', t.status_changed)
                         order by t.last_update_on desc nulls last, t.nct_id desc) from t), '[]'::jsonb),
           'events', coalesce((select jsonb_agg(jsonb_build_object(
                         'term', ev.term, 'organ_systems', coalesce(ev.organ_systems, '{}'), 'trials', ev.trials,
                         'affected', ev.affected, 'at_risk', ev.at_risk)
                         order by ev.affected desc, ev.trials desc, ev.k) from ev), '[]'::jsonb))
    into v_out;
  return v_out;
end $$;

revoke all on function ingredient_trials(uuid) from public, anon;
grant execute on function ingredient_trials(uuid) to authenticated;
