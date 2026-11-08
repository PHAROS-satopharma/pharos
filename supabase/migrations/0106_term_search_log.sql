-- PHAROS — every terminology search is logged: who, when, the words, where and how many concepts (2026-11-10).
--
-- Why: on 10 Nov 2026 the owner asked how many terminology searches were made that day. Nothing recorded them:
-- term_search() (0103, 0105) is a read-only function, and Postgres's own statistics only said "2 calls since
-- 4 November", with no person and no day.
--
-- Now the screens call term_find(), which runs term_search() and adds one row to term_search_log:
--   person_id  the PHAROS person who searched (someone who is not a PHAROS person finds nothing and is not logged)
--   at         when, stored in UTC; term_search_counts() groups the days in Cairo time
--   text       the words, as typed (at most 300 characters, like the search itself)
--   sources    the source chips chosen (null = all four)
--   place      'typed'    = a person typed it (the Terminology screen, or the search box on a case);
--              'proposal' = the three automatic proposals under a reaction on a case, from its words
--   results    how many concepts came back (0 = nothing found, worth knowing)
-- The screen searches 300 ms after the typing stops, so a word typed slowly can count more than once.
--
-- Only administrators read the log, through term_search_counts() or the table itself; nobody can change it.
-- A row is about 100 bytes: 10,000 searches are about 1 MB.

create table term_search_log (
  id         bigint generated always as identity primary key,
  at         timestamptz not null default now(),
  person_id  uuid references person(id) on delete set null,
  text       text not null,
  sources    text[],
  place      text not null default 'typed' check (place in ('typed', 'proposal')),
  results    int not null
);

create index term_search_log_at on term_search_log (at);

alter table term_search_log enable row level security;
create policy term_search_log_admin_read on term_search_log for select to authenticated
  using ((select my_role()) = 'admin');
revoke insert, update, delete, truncate on term_search_log from anon, authenticated;

-- term_search() with a log row. Same columns, same answers, same limits.
create function term_find(p_text text, p_sources text[] default null, p_limit int default 12,
                          p_place text default 'typed')
returns table (source text, code text, name text, found_as text, status text, match text, subsets text[],
               chosen_before int, score real)
language plpgsql volatile security definer set search_path = public as $$
#variable_conflict use_column
declare
  v_person uuid := my_person_id();
  v_found  int;
begin
  if v_person is null then
    return;
  end if;
  return query select * from term_search(p_text, p_sources, p_limit);
  get diagnostics v_found = row_count;
  insert into term_search_log (person_id, text, sources, place, results)
  values (v_person, left(btrim(coalesce(p_text, '')), 300), p_sources,
          case when p_place = 'proposal' then 'proposal' else 'typed' end, v_found);
end $$;

-- Searches a day (Cairo) and person, for an administrator. Anyone else gets no row.
create function term_search_counts(p_from date default null, p_to date default null)
returns table (day date, person text, place text, searches bigint, words bigint, found_nothing bigint)
language sql stable security definer set search_path = public as $$
  select (l.at at time zone 'Africa/Cairo')::date, coalesce(p.full_name, 'someone removed'), l.place,
         count(*), count(distinct lower(l.text)), count(*) filter (where l.results = 0)
    from term_search_log l
    left join person p on p.id = l.person_id
   where my_role() = 'admin'
     and (l.at at time zone 'Africa/Cairo')::date
         between coalesce(p_from, (now() at time zone 'Africa/Cairo')::date)
             and coalesce(p_to, p_from, (now() at time zone 'Africa/Cairo')::date)
   group by 1, 2, 3
   order by 1 desc, 4 desc, 2
$$;

revoke all on function term_find(text, text[], int, text), term_search_counts(date, date) from public, anon;
grant execute on function term_find(text, text[], int, text), term_search_counts(date, date) to authenticated;
