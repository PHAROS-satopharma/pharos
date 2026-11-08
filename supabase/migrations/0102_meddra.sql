-- PHAROS — the MedDRA dictionary, from the company's own MSSO subscription (2026-11-08).
--
-- Why: the E2B(R3) file codes every reaction with a MedDRA Lowest Level Term (LLT) and its version, and the PSMF
-- inspection noted that Sato Pharma had no MedDRA subscription. Until the subscription is in place, a case is sent
-- on the CIOMS I form (PR 226). Once MSSO sends the files, an administrator uploads them on the Cases screen and
-- PHAROS loads them: then each reaction's LLT is searched and chosen here, never typed from another browser.
--
-- The licence: MedDRA belongs to ICH and is licensed to the subscribing organisation. Its files and terms are never
-- put in this repository (it is public) or in a run log; they travel only from the private storage bucket
-- 'meddra' (administrators only) to these tables, which only the company's own people read.
--
--   upload    the administrator chooses the release zip as MSSO sends it, or the .asc files of its MedAscii folder;
--             the web stores them under meddra/uploads/<UTC time>/ and asks for the load (ask_meddra_load);
--   load      collectors/coding/meddra.py (the "PHAROS dictionaries" workflow, every two hours) loads the newest
--             upload asked for, in one transaction, and writes its answer on the upload;
--   coding    meddra_search() finds the LLTs closest to the reporter's words, the ones chosen before first;
--             meddra_lookup() names a typed code, so a wrong or retired code is seen before the E2B file is made.

alter table coding_dictionary drop constraint coding_dictionary_name_check;
alter table coding_dictionary add constraint coding_dictionary_name_check check (name in ('mesh','meddra'));
alter table coding_dictionary add column release text;    -- MedDRA: the bare version the E2B file names, '28.1'

-- The Preferred Terms, each on its primary path (the hierarchy MSSO marks primary): HLT, HLGT and SOC.
create table meddra_pt (
  code       text primary key check (code ~ '^[0-9]{8}$'),
  name       text not null,
  hlt_code   text,
  hlt_name   text,
  hlgt_code  text,
  hlgt_name  text,
  soc_code   text,
  soc_name   text,
  soc_abbrev text
);

-- The Lowest Level Terms: the level a reaction is coded at. A non-current LLT stays, so an old case still names its
-- code, but it is never suggested first.
create table meddra_llt (
  code     text primary key check (code ~ '^[0-9]{8}$'),
  name     text not null,
  pt_code  text not null references meddra_pt (code) on delete cascade,
  current  boolean not null,
  norm     text generated always as (coding_norm(name)) stored
);
create index meddra_llt_trgm on meddra_llt using gin (norm gin_trgm_ops);
create index meddra_llt_norm on meddra_llt (norm);
create index meddra_llt_pt   on meddra_llt (pt_code);

-- Each upload and what the load answered.
create table meddra_upload (
  folder      text primary key check (folder ~ '^uploads/[0-9]{8}T[0-9]{6}Z$'),
  asked_by    uuid references person (id),
  asked_at    timestamptz not null default now(),
  status      text not null default 'waiting' check (status in ('waiting','loading','loaded','failed','replaced')),
  message     text,
  done_at     timestamptz
);

alter table meddra_pt     enable row level security;
alter table meddra_llt    enable row level security;
alter table meddra_upload enable row level security;
create policy meddra_pt_read     on meddra_pt     for select to authenticated using (my_role() is not null);
create policy meddra_llt_read    on meddra_llt    for select to authenticated using (my_role() is not null);
create policy meddra_upload_read on meddra_upload for select to authenticated using (my_role() is not null);

-- The private bucket. Supabase provides the storage schema; the CI database has none, so it is made only where the
-- schema exists. Should the platform refuse it, the deploy goes on and says so, and the screen's upload answers
-- that it was refused (no file is ever stored anywhere else).
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public, file_size_limit)
    values ('meddra', 'meddra', false, 52428800)
    on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit;
    execute $p$create policy meddra_files_insert on storage.objects for insert to authenticated
               with check (bucket_id = 'meddra' and public.my_role() = 'admin')$p$;
    execute $p$create policy meddra_files_read on storage.objects for select to authenticated
               using (bucket_id = 'meddra' and public.my_role() = 'admin')$p$;
  end if;
exception when insufficient_privilege then
  raise warning 'MedDRA bucket: % (create it and its two policies in the dashboard)', sqlerrm;
end $$;

-- The administrator asks for the files just uploaded to be loaded.
create function ask_meddra_load(p_folder text) returns void language plpgsql security definer
set search_path = public as $$
begin
  if my_role() is distinct from 'admin' then
    raise exception 'Only an administrator loads MedDRA.' using errcode = '42501';
  end if;
  if coalesce(p_folder, '') !~ '^uploads/[0-9]{8}T[0-9]{6}Z$' then
    raise exception 'That upload is not valid.' using errcode = '22023';
  end if;
  insert into meddra_upload (folder, asked_by) values (p_folder, my_person_id())
  on conflict (folder) do update set status = 'waiting', message = null, done_at = null,
         asked_by = excluded.asked_by, asked_at = now();
end $$;

-- The LLTs closest to some words (or the LLT of an 8-digit code): those chosen before for the same words first,
-- then the exact name, then trigram likeness; a current LLT before a non-current one.
create function meddra_search(p_text text, p_limit int default 12)
returns table (llt_code text, llt_name text, current boolean, pt_code text, pt_name text, hlt_name text,
               soc_name text, chosen_before int, score real)
language sql stable security invoker set search_path = public as $$
  with q as (select coding_norm(left(p_text, 300)) as n, btrim(coalesce(p_text, '')) as raw),
  chosen as (
    select r ->> 'meddra_llt_code' as code, count(distinct c.id)::int as cases
      from safety_case c, q,
           jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                     then c.data -> 'reactions' else '[]'::jsonb end) r
     where c.status in ('confirmed','sent')
       and coalesce(r ->> 'meddra_llt_code', '') <> ''
       and q.n in (coding_norm(r ->> 'verbatim'), coding_norm(r ->> 'english'))
     group by 1),
  hit as (
    select l.code, (greatest(similarity(l.norm, q.n), word_similarity(q.n, l.norm))
                    + case when l.norm = q.n then 1 else 0 end)::real as score
      from meddra_llt l, q
     where q.raw !~ '^[0-9]{8}$' and length(q.n) >= 3 and (l.norm % q.n or q.n <% l.norm)
    union
    select l.code, 2::real from meddra_llt l, q where q.raw ~ '^[0-9]{8}$' and l.code = q.raw
    union
    select l.code, 1.5::real from meddra_llt l join chosen using (code))
  select l.code, l.name, l.current, p.code, p.name, p.hlt_name, p.soc_name,
         coalesce(ch.cases, 0), max(h.score)
    from hit h
    join meddra_llt l using (code)
    join meddra_pt p on p.code = l.pt_code
    left join chosen ch on ch.code = l.code
   group by l.code, l.name, l.current, p.code, p.name, p.hlt_name, p.soc_name, ch.cases
   order by coalesce(ch.cases, 0) desc, l.current desc, max(h.score) desc, l.name
   limit least(greatest(coalesce(p_limit, 12), 1), 50)
$$;

-- One code named, with its path and the version loaded (no row: not in the loaded MedDRA).
create function meddra_lookup(p_code text)
returns table (llt_code text, llt_name text, current boolean, pt_code text, pt_name text, hlt_name text,
               hlgt_name text, soc_name text, release text)
language sql stable security invoker set search_path = public as $$
  select l.code, l.name, l.current, p.code, p.name, p.hlt_name, p.hlgt_name, p.soc_name,
         (select release from coding_dictionary where name = 'meddra')
    from meddra_llt l join meddra_pt p on p.code = l.pt_code
   where l.code = btrim(coalesce(p_code, ''))
$$;

revoke all on function ask_meddra_load(text), meddra_search(text, int), meddra_lookup(text) from public, anon;
grant execute on function ask_meddra_load(text), meddra_search(text, int), meddra_lookup(text) to authenticated;
revoke insert, update, delete, truncate on meddra_pt, meddra_llt, meddra_upload from anon, authenticated;
