-- PHAROS — free medical terminologies beside MedDRA (2026-11-08).
--
-- Why: Sato Pharma has no MedDRA subscription yet, so a reaction cannot carry an official MedDRA Lowest Level Term
-- and a case goes on the CIOMS I form (0102, PR 226). Until the subscription arrives, reactions can still be
-- searched, named and grouped with dictionaries whose licences let a company use them at no cost:
--
--   ncit    NCI Thesaurus (US National Cancer Institute): its adverse-event and disease/finding branches, CTCAE
--   oae     Ontology of Adverse Events (CC BY), loaded without any of its MedDRA cross-references
--   icd11   WHO ICD-11 for Mortality and Morbidity Statistics, English and Arabic, stored exactly as WHO publishes it
--   mesh    MeSH (NLM), already loaded by 0061; copied here so one search covers every source
--
-- None of them is MedDRA and none is claimed to be equivalent: a free code never reaches the E2B file, and a
-- reaction without an LLT says "Needs official MedDRA coding" (docs/terminology.md).
--
--   release   each download is a term_release, kept with its SHA-256 and the counts. The first release of a source
--             is applied at once; a later one is staged with its differences (term_change) until an administrator
--             activates or rejects it on the Terminology screen;
--   concept   term_concept, one row a code; its names (term_name) and parents (term_parent);
--   search    term_search() by code, exact name, start of a name, then likeness; the ones chosen before first.

create extension if not exists pg_trgm;

create table term_source (
  id          text primary key check (id in ('ncit','oae','icd11','mesh')),
  name        text not null,
  publisher   text not null,
  licence     text not null,
  licence_url text not null,
  attribution text not null,
  maps        boolean not null default true    -- false: never compared with another source (WHO's ICD-11 terms)
);

insert into term_source (id, name, publisher, licence, licence_url, attribution, maps) values
  ('ncit', 'NCI Thesaurus', 'National Cancer Institute (NCI EVS)', 'NCI Thesaurus terms of use (free, with credit)',
   'https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/ThesaurusTermsofUse.htm',
   'NCI Thesaurus, the National Cancer Institute''s Enterprise Vocabulary Services. NCI does not endorse PHAROS.', true),
  ('oae', 'Ontology of Adverse Events', 'OAE project (He group, University of Michigan)', 'CC BY 4.0',
   'https://creativecommons.org/licenses/by/4.0/',
   'Ontology of Adverse Events (OAE), CC BY 4.0. Its MedDRA cross-references are not loaded.', true),
  ('icd11', 'ICD-11 MMS', 'World Health Organization', 'CC BY-ND 3.0 IGO',
   'https://icd.who.int/en/docs/icd11-license.pdf',
   'ICD-11 for Mortality and Morbidity Statistics, World Health Organization, CC BY-ND 3.0 IGO. Stored unchanged.',
   false),
  ('mesh', 'MeSH', 'US National Library of Medicine', 'NLM terms and conditions',
   'https://www.nlm.nih.gov/databases/download/terms_and_conditions.html',
   'Medical Subject Headings, courtesy of the US National Library of Medicine. NLM does not endorse PHAROS.', true);

create table term_release (
  id            bigint generated always as identity primary key,
  source        text not null references term_source (id),
  version       text not null,
  url           text,
  sha256        text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  archive_key   text,                              -- the original, kept write-once in the R2 archive
  status        text not null default 'staged' check (status in ('staged','active','superseded','rejected')),
  concepts      int not null default 0,
  names         int not null default 0,
  added         int not null default 0,
  changed       int not null default 0,
  retired       int not null default 0,
  fetched_at    timestamptz not null default now(),
  activated_at  timestamptz,
  activated_by  uuid references person (id),
  rejected_at   timestamptz,
  rejected_by   uuid references person (id),
  note          text,
  unique (source, version)
);
create unique index term_release_one_active on term_release (source) where status = 'active';
create unique index term_release_one_staged on term_release (source) where status = 'staged';

create table term_concept (
  source        text not null references term_source (id),
  code          text not null check (code ~ '^[A-Za-z0-9_.:-]{1,40}$'),
  name          text not null,
  definition    text,
  lang          text not null default 'en',
  status        text not null default 'current' check (status in ('current','retired')),
  first_release bigint references term_release (id),
  retired_in    bigint references term_release (id),
  subsets       text[] not null default '{}',
  uri           text,
  primary key (source, code)
);
create index term_concept_subsets on term_concept using gin (subsets);
create index term_concept_code    on term_concept (code);

create table term_name (
  source    text not null,
  code      text not null,
  name      text not null,
  norm      text generated always as (coding_norm(name)) stored,
  lang      text not null default 'en',
  preferred boolean not null default false,
  primary key (source, code, norm, lang),
  foreign key (source, code) references term_concept (source, code) on delete cascade
);
create index term_name_trgm   on term_name using gin (norm gin_trgm_ops);
create index term_name_prefix on term_name (norm text_pattern_ops);

create table term_parent (
  source text not null,
  code   text not null,
  parent text not null,
  primary key (source, code, parent),
  foreign key (source, code) references term_concept (source, code) on delete cascade
);
create index term_parent_up on term_parent (source, parent);

-- What a staged release would change; kept after activation (or rejection) as the history of each code.
-- after: {"name", "definition", "lang", "subsets", "uri", "names": [[name, lang, preferred]], "parents": [code]}
create table term_change (
  release bigint not null references term_release (id) on delete cascade,
  source  text not null,
  code    text not null,
  kind    text not null check (kind in ('added','changed','retired')),
  before  jsonb,
  after   jsonb,
  primary key (release, code)
);
create index term_change_code on term_change (source, code);

alter table term_source  enable row level security;
alter table term_release enable row level security;
alter table term_concept enable row level security;
alter table term_name    enable row level security;
alter table term_parent  enable row level security;
alter table term_change  enable row level security;
create policy term_source_read  on term_source  for select to authenticated using (my_role() is not null);
create policy term_release_read on term_release for select to authenticated using (my_role() is not null);
create policy term_concept_read on term_concept for select to authenticated using (my_role() is not null);
create policy term_name_read    on term_name    for select to authenticated using (my_role() is not null);
create policy term_parent_read  on term_parent  for select to authenticated using (my_role() is not null);
create policy term_change_read  on term_change  for select to authenticated using (my_role() is not null);

-- The concepts closest to some words, or the concept of a code. Ranking: the concept chosen before for the same
-- words (a confirmed or sent case's reaction.term), then a current concept before a retired one, then the code,
-- the exact name, the start of a name, and likeness. found_as is the name that matched (a synonym, or Arabic).
create function term_search(p_text text, p_sources text[] default null, p_limit int default 12)
returns table (source text, code text, name text, found_as text, status text, match text, subsets text[],
               chosen_before int, score real)
language sql stable security invoker set search_path = public as $$
  with q as (select coding_norm(left(p_text, 300)) as n, btrim(coalesce(left(p_text, 300), '')) as raw),
  chosen as (
    select r -> 'term' ->> 'source' as source, r -> 'term' ->> 'code' as code, count(distinct c.id)::int as cases
      from safety_case c, q,
           jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                     then c.data -> 'reactions' else '[]'::jsonb end) r
     where c.status in ('confirmed','sent')
       and jsonb_typeof(r -> 'term') = 'object'
       and q.n <> '' and q.n in (coding_norm(r ->> 'verbatim'), coding_norm(r ->> 'english'))
     group by 1, 2),
  hit as (
    select c.source, c.code, c.name as found, 'code'::text as match, 4::real as score
      from term_concept c, q
     where q.raw <> '' and c.code in (q.raw, upper(q.raw))
    union all
    select t.source, t.code, t.name, 'exact', 3::real
      from term_name t, q where length(q.n) >= 2 and t.norm = q.n
    union all
    select t.source, t.code, t.name, 'prefix', (2 + similarity(t.norm, q.n))::real
      from term_name t, q
     where length(q.n) >= 3 and t.norm like replace(replace(replace(q.n, '\', '\\'), '%', '\%'), '_', '\_') || '%'
       and t.norm <> q.n
    union all
    select t.source, t.code, t.name, 'trigram',
           ((similarity(t.norm, q.n) + word_similarity(q.n, t.norm)) / 2)::real
      from term_name t, q
     where length(q.n) >= 3 and (t.norm % q.n or q.n <% t.norm)
    union all
    select ch.source, ch.code, null, 'chosen', 1::real from chosen ch),
  best as (
    select distinct on (h.source, h.code) h.source, h.code, h.found, h.match, h.score
      from hit h
     where p_sources is null or h.source = any (p_sources)
     order by h.source, h.code, h.score desc, h.found)
  select c.source, c.code, c.name, coalesce(b.found, c.name), c.status, b.match, c.subsets,
         coalesce(ch.cases, 0), b.score
    from best b
    join term_concept c on c.source = b.source and c.code = b.code
    left join chosen ch on ch.source = b.source and ch.code = b.code
   order by coalesce(ch.cases, 0) desc, (c.status = 'current') desc, b.score desc, c.name, c.source
   limit least(greatest(coalesce(p_limit, 12), 1), 50)
$$;

-- One code named, with its source, the version it comes from and the licence (no row: not in that source).
create function term_lookup(p_source text, p_code text)
returns table (source text, code text, name text, definition text, lang text, status text, subsets text[],
               uri text, names jsonb, version text, retired_in text, source_name text, licence text,
               licence_url text, attribution text)
language sql stable security invoker set search_path = public as $$
  select c.source, c.code, c.name, c.definition, c.lang, c.status, c.subsets, c.uri,
         coalesce((select jsonb_agg(jsonb_build_object('name', n.name, 'lang', n.lang, 'preferred', n.preferred)
                                    order by n.preferred desc, n.lang, n.name)
                     from term_name n where n.source = c.source and n.code = c.code), '[]'::jsonb),
         (select r.version from term_release r where r.source = c.source and r.status = 'active'),
         (select r.version from term_release r where r.id = c.retired_in),
         s.name, s.licence, s.licence_url, s.attribution
    from term_concept c join term_source s on s.id = c.source
   where c.source = p_source and c.code = btrim(coalesce(p_code, ''))
$$;

create function term_children(p_source text, p_code text)
returns table (code text, name text, status text, children int)
language sql stable security invoker set search_path = public as $$
  select c.code, c.name, c.status,
         (select count(*)::int from term_parent g where g.source = c.source and g.parent = c.code)
    from term_parent p join term_concept c on c.source = p.source and c.code = p.code
   where p.source = p_source and p.parent = p_code
   order by (c.status = 'current') desc, c.name
   limit 500
$$;

-- One path from the top of the source down to the code (the first parent by code at each step).
create function term_path(p_source text, p_code text)
returns table (depth int, code text, name text)
language sql stable security invoker set search_path = public as $$
  with recursive up (depth, code, seen) as (
    select 0, p_code, array[p_code]
    union all
    select u.depth + 1, nx.parent, u.seen || nx.parent
      from up u
      cross join lateral (select p.parent from term_parent p
                           where p.source = p_source and p.code = u.code
                             and exists (select 1 from term_concept x where x.source = p_source and x.code = p.parent)
                           order by p.parent limit 1) nx
     where u.depth < 40 and not nx.parent = any (u.seen))
  select (max(u.depth) over () - u.depth)::int, u.code, c.name
    from up u join term_concept c on c.source = p_source and c.code = u.code
   order by 1
$$;

-- Concepts of the other sources that carry the same words. Never an official mapping, and never ICD-11 (WHO's
-- terms are stored as published and compared with nothing).
create function term_related(p_source text, p_code text)
returns table (source text, code text, name text, same_words text, note text)
language sql stable security invoker set search_path = public as $$
  select distinct on (o.source, o.code) o.source, o.code, c.name, o.name,
         'Same words, not an official mapping'::text
    from term_name n
    join term_source sn on sn.id = n.source and sn.maps
    join term_name o on o.norm = n.norm and o.source <> n.source
    join term_source so on so.id = o.source and so.maps
    join term_concept c on c.source = o.source and c.code = o.code and c.status = 'current'
   where n.source = p_source and n.code = p_code and length(n.norm) >= 3
   order by o.source, o.code, o.preferred desc
   limit 30
$$;

-- An administrator applies a staged release: each change is written, the release becomes the active one and the
-- one before it superseded. Everything in one transaction (the function's own).
create function activate_term_release(p_release bigint) returns jsonb language plpgsql security definer
set search_path = public as $$
declare
  r term_release;
  ch term_change;
  n int := 0;
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator activates a terminology release.' using errcode = '42501';
  end if;
  select * into r from term_release where id = p_release for update;
  if not found or r.status <> 'staged' then
    raise exception 'That release is not waiting for review.' using errcode = '22023';
  end if;
  for ch in select * from term_change where release = r.id loop
    if ch.kind = 'retired' then
      update term_concept set status = 'retired', retired_in = r.id where source = r.source and code = ch.code;
    else
      insert into term_concept (source, code, name, definition, lang, status, first_release, retired_in, subsets, uri)
      values (r.source, ch.code, ch.after ->> 'name', ch.after ->> 'definition',
              coalesce(ch.after ->> 'lang', 'en'), 'current', r.id, null,
              coalesce(array(select jsonb_array_elements_text(ch.after -> 'subsets')), '{}'), ch.after ->> 'uri')
      on conflict on constraint term_concept_pkey do update
         set name = excluded.name, definition = excluded.definition, lang = excluded.lang, status = 'current',
             retired_in = null, subsets = excluded.subsets, uri = excluded.uri;
      delete from term_name where source = r.source and code = ch.code;
      insert into term_name (source, code, name, lang, preferred)
      select r.source, ch.code, x ->> 0, coalesce(x ->> 1, 'en'), coalesce((x ->> 2)::boolean, false)
        from jsonb_array_elements(coalesce(ch.after -> 'names', '[]'::jsonb)) x
       where coding_norm(x ->> 0) <> ''
      on conflict do nothing;
      delete from term_parent where source = r.source and code = ch.code;
    end if;
    n := n + 1;
  end loop;
  -- Parents last: a new concept may name a parent added later in the same release.
  insert into term_parent (source, code, parent)
  select r.source, tc.code, p
    from term_change tc, jsonb_array_elements_text(coalesce(tc.after -> 'parents', '[]'::jsonb)) p
   where tc.release = r.id and tc.kind <> 'retired'
  on conflict do nothing;
  update term_release set status = 'superseded' where source = r.source and status = 'active';
  update term_release set status = 'active', activated_at = now(), activated_by = my_person_id()
   where id = r.id;
  analyze term_concept, term_name, term_parent;   -- the search plans for the rows it now has
  return jsonb_build_object('release', r.id, 'changes', n);
end $$;

create function reject_term_release(p_release bigint, p_note text default null) returns void language plpgsql
security definer set search_path = public as $$
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator rejects a terminology release.' using errcode = '42501';
  end if;
  update term_release set status = 'rejected', rejected_at = now(), rejected_by = my_person_id(),
         note = nullif(btrim(left(coalesce(p_note, ''), 500)), '')
   where id = p_release and status = 'staged';
  if not found then
    raise exception 'That release is not waiting for review.' using errcode = '22023';
  end if;
end $$;

revoke all on function term_search(text, text[], int), term_lookup(text, text), term_children(text, text),
                       term_path(text, text), term_related(text, text), activate_term_release(bigint),
                       reject_term_release(bigint, text) from public, anon;
grant execute on function term_search(text, text[], int), term_lookup(text, text), term_children(text, text),
                          term_path(text, text), term_related(text, text), activate_term_release(bigint),
                          reject_term_release(bigint, text) to authenticated;
revoke insert, update, delete, truncate on term_source, term_release, term_concept, term_name, term_parent,
                                           term_change from anon, authenticated;
