-- PHAROS — the terminology search answers in milliseconds for the people who use it (2026-11-09).
--
-- Why: on 9 Nov 2026, the first search on the Terminology screen stopped with "canceling statement due to
-- statement timeout". The functions of 0103 ran with the caller's rights, so row-level security applied to every
-- row of term_name (250,000 names). Its policy calls my_role(), which is not leakproof, so Postgres keeps it ahead
-- of the trigram and prefix conditions, reads the whole table instead of its indexes, and calls my_role() on each
-- row: about 4 s a search on a laptop, past the 8 s limit on the database. The checks in CI ran as the owner, who
-- skips row-level security, and so never saw it.
--
-- Now each function runs with its owner's rights (security definer) and asks my_role() once: someone who is not
-- a PHAROS person gets no row, as before; everyone else gets the indexes. The policies of 0103 also ask my_role()
-- once a query, not once a row, for the screen's direct reads.

create or replace function term_search(p_text text, p_sources text[] default null, p_limit int default 12)
returns table (source text, code text, name text, found_as text, status text, match text, subsets text[],
               chosen_before int, score real)
language sql stable security definer set search_path = public as $$
  with q as (select term_norm(left(p_text, 300)) as n, btrim(coalesce(left(p_text, 300), '')) as raw
             where my_role() is not null),
  chosen as (
    select r -> 'term' ->> 'source' as source, r -> 'term' ->> 'code' as code, count(distinct c.id)::int as cases
      from safety_case c, q,
           jsonb_array_elements(case when jsonb_typeof(c.data -> 'reactions') = 'array'
                                     then c.data -> 'reactions' else '[]'::jsonb end) r
     where c.status in ('confirmed','sent')
       and jsonb_typeof(r -> 'term') = 'object'
       and q.n <> '' and q.n in (term_norm(r ->> 'verbatim'), term_norm(r ->> 'english'))
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

create or replace function term_lookup(p_source text, p_code text)
returns table (source text, code text, name text, definition text, lang text, status text, subsets text[],
               uri text, names jsonb, version text, retired_in text, source_name text, licence text,
               licence_url text, attribution text)
language sql stable security definer set search_path = public as $$
  select c.source, c.code, c.name, c.definition, c.lang, c.status, c.subsets, c.uri,
         coalesce((select jsonb_agg(jsonb_build_object('name', n.name, 'lang', n.lang, 'preferred', n.preferred)
                                    order by n.preferred desc, n.lang, n.name)
                     from term_name n where n.source = c.source and n.code = c.code), '[]'::jsonb),
         (select r.version from term_release r where r.source = c.source and r.status = 'active'),
         (select r.version from term_release r where r.id = c.retired_in),
         s.name, s.licence, s.licence_url, s.attribution
    from term_concept c join term_source s on s.id = c.source
   where c.source = p_source and c.code = btrim(coalesce(p_code, '')) and my_role() is not null
$$;

create or replace function term_children(p_source text, p_code text)
returns table (code text, name text, status text, children int)
language sql stable security definer set search_path = public as $$
  select c.code, c.name, c.status,
         (select count(*)::int from term_parent g where g.source = c.source and g.parent = c.code)
    from term_parent p join term_concept c on c.source = p.source and c.code = p.code
   where p.source = p_source and p.parent = p_code and my_role() is not null
   order by (c.status = 'current') desc, c.name
   limit 500
$$;

create or replace function term_path(p_source text, p_code text)
returns table (depth int, code text, name text)
language sql stable security definer set search_path = public as $$
  with recursive up (depth, code, seen) as (
    select 0, p_code, array[p_code] where my_role() is not null
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

create or replace function term_related(p_source text, p_code text)
returns table (source text, code text, name text, same_words text, note text)
language sql stable security definer set search_path = public as $$
  select distinct on (o.source, o.code) o.source, o.code, c.name, o.name,
         'Same words, not an official mapping'::text
    from term_name n
    join term_source sn on sn.id = n.source and sn.maps
    join term_name o on o.norm = n.norm and o.source <> n.source
    join term_source so on so.id = o.source and so.maps
    join term_concept c on c.source = o.source and c.code = o.code and c.status = 'current'
   where n.source = p_source and n.code = p_code and length(n.norm) >= 3 and my_role() is not null
   order by o.source, o.code, o.preferred desc
   limit 30
$$;

alter policy term_source_read  on term_source  using ((select my_role()) is not null);
alter policy term_release_read on term_release using ((select my_role()) is not null);
alter policy term_concept_read on term_concept using ((select my_role()) is not null);
alter policy term_name_read    on term_name    using ((select my_role()) is not null);
alter policy term_parent_read  on term_parent  using ((select my_role()) is not null);
alter policy term_change_read  on term_change  using ((select my_role()) is not null);
