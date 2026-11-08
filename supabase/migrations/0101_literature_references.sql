-- Literature references, Global and Local (Dr Sama, 8 Nov 2026, for the inspection on Wednesday 18 Nov).
--
-- She screens the literature against two kinds of reference: Global (the international databases: PubMed, PubMed
-- Central, Europe PMC, Cochrane, Medscape) and Local (the Egyptian medical journals the Egyptian Drug Authority
-- asks for: the Al-Azhar Medical Journal, the Ain Shams Medical Journal, …). For every reference she needs the
-- negative result in writing, week by week, as the app already gives it for the 25 authorities.
--
-- 1. literature_ref: her list. Admins add, change and remove; the team reads; every change is in the audit log.
--      searched_in   the databases the app searches for it ('pubmed', 'pmc', 'europepmc'); empty = checked by hand
--      journal_like  only papers whose journal holds these words count for it (Cochrane: its reviews are in
--                    PubMed and Europe PMC, so the app's searches already cover them)
-- 2. literature_search_log: every search the collector sent, with what the database returned, one row each. Until
--    now literature_search (0035) kept only the last time a search ran, and the report's zero was worked out from
--    the papers stored. Written by the collector only; nobody changes or removes a row.
-- 3. literature_check: a hand check of a reference the app cannot search (Medscape refuses automatic access, and
--    the Egyptian journals until the app reads them): who checked, when, and whether anything was found. Written
--    through record_literature_check() by a reviewer or an admin; nobody changes or removes a row.
-- 4. literature_refs_week(ingredient, from, to): for each reference, the searches the app ran in those days, the
--    papers found, and the latest hand check. With no ingredient: every search (the Sources page).

-- ───────────────────────────── 1. the references ─────────────────────────────
create table literature_ref (
  id            uuid primary key default gen_random_uuid(),
  scope         text not null check (scope in ('global', 'local')),
  name          text not null check (btrim(name) <> '' and length(name) <= 200),
  url           text check (url ~ '^https?://[^\s]+$' and length(url) <= 500),
  searched_in   text[] not null default '{}'
                check (searched_in <@ array['pubmed', 'pmc', 'europepmc']::text[]),
  journal_like  text check (journal_like is null or (btrim(journal_like) <> '' and length(journal_like) <= 200)),
  note          text check (note is null or length(note) <= 1000),
  sort          int not null default 100,
  active        boolean not null default true,
  created_by    uuid references person(id) on delete set null default my_person_id(),
  created_at    timestamptz not null default now()
);
create unique index literature_ref_url_key on literature_ref (scope, lower(url)) where url is not null and active;
create unique index literature_ref_name_key on literature_ref (scope, lower(btrim(name))) where active;
comment on table literature_ref is
  'Her literature references, Global and Local: the databases and journals she screens, and how each is screened.';

alter table literature_ref enable row level security;
create policy literature_ref_read on literature_ref for select to authenticated using (my_role() is not null);
create policy literature_ref_admin on literature_ref for all to authenticated
  using (my_role() = 'admin') with check (my_role() = 'admin');
revoke all on literature_ref from anon;
revoke truncate on literature_ref from authenticated;
create trigger audit_literature_ref after insert or update or delete on literature_ref
  for each row execute function audit_row();

insert into literature_ref (scope, name, url, searched_in, journal_like, note, sort, created_by) values
  ('global', 'PubMed (NCBI)', 'https://pubmed.ncbi.nlm.nih.gov/', '{pubmed}', null,
   'Searched by the app every day: the ingredient''s name and its class words, in titles and abstracts.', 10, null),
  ('global', 'PubMed Central (NCBI)', 'https://pmc.ncbi.nlm.nih.gov/', '{pmc}', null,
   'Searched by the app every day: the full text of the open papers.', 20, null),
  ('global', 'Europe PMC', 'https://europepmc.org/', '{europepmc}', null,
   'Searched by the app every day, with the preprints.', 30, null),
  ('global', 'Cochrane Database of Systematic Reviews', 'https://www.cochranelibrary.com/', '{pubmed,europepmc}',
   'cochrane database',
   'Every Cochrane review is indexed in PubMed and Europe PMC, so the app''s searches cover it; the Cochrane site '
   'itself refuses automatic access.', 40, null),
  ('global', 'Medscape', 'https://www.medscape.com/', '{}', null,
   'Medscape refuses automatic access: checked by hand.', 50, null),
  ('local', 'Al-Azhar Medical Journal', 'https://amj.journals.ekb.eg/', '{}', null,
   'Egyptian Knowledge Bank. Checked by hand.', 10, null),
  ('local', 'Ain Shams Medical Journal', 'https://asmj.journals.ekb.eg/', '{}', null,
   'Egyptian Knowledge Bank. Checked by hand.', 20, null);

-- ───────────────────────────── 2. every search, with its count ─────────────────────────────
create table literature_search_log (
  id           bigint generated always as identity primary key,
  run_id       uuid references run(id) on delete set null,
  source_id    text not null references source(id),
  db           text not null check (db in ('pubmed', 'pmc', 'europepmc')),
  query        text not null check (query <> '' and query = lower(query)),
  kind         text not null check (kind in ('name', 'class')),
  window_from  date not null,
  window_to    date not null,
  hits         int not null check (hits >= 0),
  searched_at  timestamptz not null default now(),
  check (window_from <= window_to)
);
create index literature_search_log_at on literature_search_log (searched_at);
create index literature_search_log_query on literature_search_log (query, searched_at);
comment on table literature_search_log is
  'Every literature search the collector sent, with the number of papers the database returned (0 included).';

alter table literature_search_log enable row level security;
create policy literature_search_log_read on literature_search_log for select to authenticated
  using (my_role() is not null);
revoke all on literature_search_log from anon;
revoke insert, update, delete, truncate on literature_search_log from authenticated;
grant select on literature_search_log to authenticated;

-- ───────────────────────────── 3. hand checks ─────────────────────────────
create table literature_check (
  id          uuid primary key default gen_random_uuid(),
  ref_id      uuid not null references literature_ref(id) on delete restrict,
  result      text not null check (result in ('nothing', 'found')),
  note        text check (note is null or length(note) <= 1000),
  checked_by  uuid not null references person(id),
  checked_at  timestamptz not null default now()
);
create index literature_check_ref on literature_check (ref_id, checked_at desc);
comment on table literature_check is
  'A hand check of a literature reference: who checked it, when, and whether anything was found.';

alter table literature_check enable row level security;
create policy literature_check_read on literature_check for select to authenticated using (my_role() is not null);
revoke all on literature_check from anon;
revoke insert, update, delete, truncate on literature_check from authenticated;
grant select on literature_check to authenticated;
create trigger audit_literature_check after insert or update or delete on literature_check
  for each row execute function audit_row();

create function record_literature_check(p_ref uuid, p_result text, p_note text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := my_person_id();
  v_id     uuid;
begin
  if v_person is null or my_role() not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can record a check.' using errcode = '42501';
  end if;
  if p_result is null or p_result not in ('nothing', 'found') then
    raise exception 'Say whether anything was found.' using errcode = '22023';
  end if;
  if not exists (select 1 from literature_ref where id = p_ref and active) then
    raise exception 'That reference is not on the list.' using errcode = 'P0002';
  end if;
  if p_result = 'found' and nullif(btrim(p_note), '') is null then
    raise exception 'Say what was found.' using errcode = '22023';
  end if;
  insert into literature_check (ref_id, result, note, checked_by)
    values (p_ref, p_result, nullif(btrim(left(p_note, 1000)), ''), v_person)
    returning id into v_id;
  return v_id;
end $$;
revoke all on function record_literature_check(uuid, text, text) from public, anon;
grant execute on function record_literature_check(uuid, text, text) to authenticated;

-- ───────────────────────────── 4. each reference, for some days ─────────────────────────────
-- One object per active reference, in her order:
--   id, scope, name, url, note, by_hand (true when the app does not search it), searched_in, journal_like,
--   searches (searches sent in those days for the ingredient's words, or for any word with no ingredient),
--   last_searched, hits (what the databases returned, summed), found (the ingredient's papers of those days that
--   these databases found; null with no ingredient), check (the latest hand check in those days: result, note,
--   checked_at, checked_by (a name)).
create function literature_refs_week(p_ingredient uuid, p_from date, p_to date) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_from    timestamptz := p_from::timestamp at time zone 'Africa/Cairo';
  v_to      timestamptz := (p_to + 1)::timestamp at time zone 'Africa/Cairo';
  v_classes uuid[];
  v_lit     uuid[];
  v_words   text[];
begin
  if p_ingredient is not null then
    perform ingredient_screen_check(p_ingredient, p_from, p_to);
    select coalesce(array_agg(ic.class_id), '{}'),
           coalesce(array_agg(ic.class_id) filter (where ic.enabled and ic.literature), '{}')
      into v_classes, v_lit
      from ingredient_class ic where ic.ingredient_id = p_ingredient;
    select array_agg(w) into v_words from (
      select lower(regexp_replace(btrim(i.inn_en), '\s+', ' ', 'g')) as w from ingredient i where i.id = p_ingredient
      union
      select lower(regexp_replace(btrim(ct.term), '\s+', ' ', 'g'))
        from class_term ct where ct.class_id = any (v_lit) and ct.lang = 'en') x;
  else
    if not screen_reader() then
      raise exception 'Only a member of the team can read the literature references.' using errcode = '42501';
    end if;
    if p_from is null or p_to is null or p_to < p_from then
      raise exception 'Choose days whose end is on or after their start.' using errcode = '22023';
    end if;
    if p_to - p_from > 365 then
      raise exception 'Choose at most 366 days.' using errcode = '22023';
    end if;
  end if;

  return coalesce((
    with log as (
      select l.db, l.hits, l.searched_at
        from literature_search_log l
       where l.searched_at >= v_from and l.searched_at < v_to
         and (p_ingredient is null or l.query = any (v_words))
    ),
    papers as (
      select d.structured
        from (select m.document_id as doc_id
                from match m
               where p_ingredient is not null
                 and (m.ingredient_id = p_ingredient or m.class_id = any (v_classes))
               group by m.document_id) h
        join document d on d.id = h.doc_id
        join source s on s.id = d.source_id
       where s.kind = 'literature'
         and coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date) between p_from and p_to
    )
    select jsonb_agg(jsonb_build_object(
             'id', r.id, 'scope', r.scope, 'name', r.name, 'url', r.url, 'note', r.note,
             'by_hand', cardinality(r.searched_in) = 0,
             'searched_in', to_jsonb(r.searched_in), 'journal_like', r.journal_like,
             'searches', (select count(*) from log where log.db = any (r.searched_in)),
             'last_searched', (select max(log.searched_at) from log where log.db = any (r.searched_in)),
             'hits', (select coalesce(sum(log.hits), 0) from log where log.db = any (r.searched_in)),
             'found', case when p_ingredient is null or cardinality(r.searched_in) = 0 then null else
                        (select count(*) from papers pp
                          where jsonb_typeof(pp.structured -> 'found_in') = 'array'
                            and (pp.structured -> 'found_in') ?| r.searched_in
                            and (r.journal_like is null
                                 or coalesce(pp.structured ->> 'journal', '')
                                    ilike '%' || replace(replace(replace(r.journal_like, '\', '\\'), '%', '\%'),
                                                         '_', '\_') || '%')) end,
             'check', (select jsonb_build_object('result', c.result, 'note', c.note, 'checked_at', c.checked_at,
                                                 'checked_by', coalesce(p.full_name, 'a former member'))
                         from literature_check c left join person p on p.id = c.checked_by
                        where c.ref_id = r.id and c.checked_at >= v_from and c.checked_at < v_to
                        order by c.checked_at desc limit 1))
           order by r.scope, r.sort, lower(r.name))
      from literature_ref r
     where r.active), '[]'::jsonb);
end $$;
revoke all on function literature_refs_week(uuid, date, date) from public, anon;
grant execute on function literature_refs_week(uuid, date, date) to authenticated;
