-- PHAROS — medical coding of cases with free public dictionaries (2026-11-06).
--
-- The company holds no MedDRA or WHODrug licence, so PHAROS codes against two free dictionaries of the U.S.
-- National Library of Medicine (NLM), which ask only that NLM is named as the source and never as endorsing:
--   reactions, indications, medical history  MeSH, the disease tree (C) and mental disorders (F03), loaded into
--                                             mesh_descriptor / mesh_term by collectors/coding/mesh.py, one
--                                             release a year;
--   products                                 the watched ingredients first (their brands and names), then
--                                             RxNorm (RxNav, public domain) with the ingredient's UNII, looked up
--                                             when a case is coded.
-- MedDRA stays where the E2B file needs it: the reviewer's own LLT code and version on each reaction.
--
-- Coding is suggested, never decided: collectors/coding/coder.py writes its suggestions to safety_case.coding
-- (beside the form, so a reviewer's open page never goes stale because of it), and a reviewer chooses each code
-- into the form (data), which is saved and confirmed as before. Every confirmed code teaches the next suggestion
-- (coding_memory: the same words coded the same way before, with how many times).

create table coding_dictionary (
  name        text primary key check (name in ('mesh')),
  version     text not null,                 -- 'MeSH 2026'
  source_url  text not null,
  sha256      text not null,
  descriptors int  not null,
  terms       int  not null,
  loaded_at   timestamptz not null default now()
);

-- Words compared the way the coder compares them (collectors/coding/norm.py norm()): ASCII lower case, every run
-- of characters other than ASCII letters and digits and non-ASCII letters made one space.
create function coding_norm(p text) returns text language sql immutable parallel safe as $$
  select btrim(regexp_replace(lower(coalesce(p, '') collate "C"), '[^0-9a-z\u0080-\uffff]+', ' ', 'g'))
$$;

create table mesh_descriptor (
  ui         text primary key check (ui ~ '^D[0-9]{6,9}$'),
  name       text not null,
  trees      text[] not null,                -- C06.552.380, …
  scope_note text
);
create index mesh_descriptor_trees on mesh_descriptor using gin (trees);

create table mesh_term (
  ui        text not null references mesh_descriptor (ui) on delete cascade,
  term      text not null,
  norm      text generated always as (coding_norm(term)) stored,
  preferred boolean not null default false,
  primary key (ui, norm)
);
create index mesh_term_trgm on mesh_term using gin (norm gin_trgm_ops);
create index mesh_term_norm on mesh_term (norm);

alter table coding_dictionary enable row level security;
alter table mesh_descriptor   enable row level security;
alter table mesh_term         enable row level security;
create policy coding_dictionary_read on coding_dictionary for select to authenticated using (my_role() is not null);
create policy mesh_descriptor_read   on mesh_descriptor   for select to authenticated using (my_role() is not null);
create policy mesh_term_read         on mesh_term         for select to authenticated using (my_role() is not null);

-- The body-system heading of a tree number: C06.552.380 → the descriptor at C06 (Digestive System Diseases).
create function mesh_category(p_trees text[]) returns text[] language sql stable security invoker
set search_path = public as $$
  select coalesce(array_agg(distinct d.name order by d.name), '{}')
    from unnest(p_trees) t
    join mesh_descriptor d on left(t, 3) = any (d.trees)
$$;

-- The descriptors whose names come closest to some words: the exact name first, then by trigram likeness.
create function mesh_search(p_text text, p_limit int default 12)
returns table (ui text, name text, term text, trees text[], categories text[], score real)
language sql stable security invoker set search_path = public as $$
  with q as (select coding_norm(left(p_text, 300)) as n),
  hit as (
    select distinct on (t.ui) t.ui, t.term,
           (greatest(similarity(t.norm, q.n), word_similarity(q.n, t.norm))
            + case when t.norm = q.n then 1 else 0 end
            + case when t.preferred then 0.01 else 0 end)::real as score
      from mesh_term t, q
     where length(q.n) >= 3 and (t.norm % q.n or q.n <% t.norm)
     order by t.ui, score desc)
  select d.ui, d.name, hit.term, d.trees, mesh_category(d.trees), hit.score
    from hit join mesh_descriptor d using (ui)
   order by hit.score desc, d.name
   limit least(greatest(coalesce(p_limit, 12), 1), 50)
$$;

-- What the coder has been taught: in confirmed and sent cases, which code a person chose for the same words.
create view coding_memory with (security_invoker = true) as
with reactions as (
  select c.id, r
    from safety_case c,
         jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                   then c.data -> 'reactions' else '[]'::jsonb end) r
   where c.status in ('confirmed','sent')),
products as (
  select c.id, p
    from safety_case c,
         jsonb_array_elements(case when jsonb_typeof(c.data -> 'products') = 'array'
                                   then c.data -> 'products' else '[]'::jsonb end) p
   where c.status in ('confirmed','sent')),
said as (
  select 'reaction'::text as kind, coding_norm(w) as norm, r ->> 'mesh_ui' as code, r ->> 'mesh_term' as label, id
    from reactions, unnest(array[r ->> 'verbatim', r ->> 'english']) w
   where coalesce(r ->> 'mesh_ui', '') <> '' and coalesce(w, '') <> ''
  union all
  select 'indication', coding_norm(p ->> 'indication'), p ->> 'indication_mesh_ui', p ->> 'indication_mesh_term', id
    from products
   where coalesce(p ->> 'indication_mesh_ui', '') <> '' and coalesce(p ->> 'indication', '') <> ''
  union all
  select 'product', coding_norm(w), p ->> 'rxcui', p ->> 'rxnorm_name', id
    from products, unnest(array[p ->> 'name', p ->> 'active_ingredient']) w
   where coalesce(p ->> 'rxcui', '') <> '' and coalesce(w, '') <> '')
select kind, norm, code, max(label) as label, count(distinct id)::int as cases
  from said
 where norm <> ''
 group by kind, norm, code;

-- The coder's suggestions, beside the form. A reviewer asks for them again (after changing the words) with
-- ask_case_coding(); the collector codes every case asked for, and every case read since it last coded.
alter table safety_case
  add column coding        jsonb,
  add column coding_status text check (coding_status in ('queued','done','failed')),
  add column coding_error  text,
  add column coded_at      timestamptz;

create function ask_case_coding(p_case uuid) returns void language plpgsql security definer
set search_path = public as $$
declare v_status case_status;
begin
  perform case_require_reviewer();
  select status into v_status from safety_case where id = p_case;
  if v_status is null then raise exception 'That case does not exist.' using errcode = '22023'; end if;
  if v_status in ('queued','reading','not_valid') then
    raise exception 'The case is not read yet: its codes are suggested once it is.' using errcode = '22023';
  end if;
  update safety_case set coding_status = 'queued', coding_error = null where id = p_case;
end $$;

revoke all on function ask_case_coding(uuid) from public, anon;
grant execute on function ask_case_coding(uuid) to authenticated;
revoke all on function mesh_search(text, int), mesh_category(text[]) from public, anon;
grant execute on function mesh_search(text, int), mesh_category(text[]), coding_norm(text) to authenticated;
grant select on coding_memory to authenticated;
