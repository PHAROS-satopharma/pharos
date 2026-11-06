-- PHAROS — our label under "Label changes" (2026-11-06, the QPPV's third need after her review).
--
-- The label watch (collectors/spc) finds when an originator's SmPC / PI changes a safety section, and 0027 keeps
-- the text of OUR label section by section. Until now the two met only on the removed notice page. This puts
-- them together under section 03 of the Ingredients screen and in the weekly report:
--
-- 1. spc_product.is_reference: the product whose label she follows first (one per ingredient, the originator as a
--    rule). set_reference_product(product, on) marks it — a reviewer or administrator; marking one clears the
--    other product of the same ingredient; every mark is in the audit log.
-- 2. label_gap: for one label change and one version of our label, what the gap check found (the collector
--    computes it, collectors/labels: for each sentence the originator added, whether our section says it —
--    covered, partly, missing — never across languages). The collector writes it when the change is recorded
--    and catches up on every run; a new version of our label is compared with the changes of the last year on
--    the next run. The team reads it; nobody else writes it.
-- 3. label_changes(ingredient, from, to): the label changes DETECTED in the Cairo days (not the label's own
--    date — the same days the screen and the weekly report use), the reference product first, then newest first,
--    each with its product, authority, link, sections, the stored word diff, the gap against the newest current
--    version of our label (null until the collector computed it), the notice it opened and the latest decision.
--    Read as the Ingredients screen is read: ingredient_screen_check() (a member of the team, or the weekly
--    report on its direct connection; at most 366 days; P0002 for an unknown ingredient).

-- ───────────────────────────── the reference product ─────────────────────────────
alter table spc_product add column is_reference boolean not null default false;
create unique index spc_product_one_reference_idx on spc_product (ingredient_id) where is_reference;
comment on column spc_product.is_reference is
  'The product whose label the QPPV follows first for this ingredient; one per ingredient (set_reference_product).';

-- The mark is audited; the weekly upsert of every product by the label watch is not (it never sets the column).
create trigger audit_spc_product_reference after update of is_reference on spc_product
  for each row when (old.is_reference is distinct from new.is_reference) execute function audit_row();

create function set_reference_product(p_product uuid, p_on boolean) returns void
language plpgsql security definer set search_path = public as $$
declare
  v_ing uuid;
  v_on  boolean := coalesce(p_on, false);
begin
  if my_role() is null or my_role() not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can mark the reference product.' using errcode = '42501';
  end if;
  select ingredient_id into v_ing from spc_product where id = p_product for update;
  if not found then
    raise exception 'That product is not in the label watch.' using errcode = 'P0002';
  end if;
  if v_on then
    update spc_product set is_reference = false
     where ingredient_id = v_ing and is_reference and id <> p_product;
  end if;
  update spc_product set is_reference = v_on where id = p_product and is_reference is distinct from v_on;
end $$;
revoke all on function set_reference_product(uuid, boolean) from public, anon;
grant execute on function set_reference_product(uuid, boolean) to authenticated;

-- ───────────────────────────── the gap the collector computed ─────────────────────────────
create table label_gap (
  id             uuid primary key default gen_random_uuid(),
  spc_change_id  uuid not null references spc_change(id) on delete cascade,
  our_label_id   uuid not null references our_label(id) on delete cascade,
  gap            jsonb not null,            -- {lang_match, our_lang, their_lang, covered, partly, missing, sections: […]}
  computed_at    timestamptz not null default now(),
  unique (spc_change_id, our_label_id)
);
create index on label_gap (our_label_id);
comment on table label_gap is
  'What the gap check found for one label change against one version of our label (collectors/labels/gap.py).';

alter table label_gap enable row level security;
create policy label_gap_read on label_gap for select to authenticated using (my_role() is not null);
revoke all on label_gap from public, anon;
revoke insert, update, delete, truncate on label_gap from authenticated;
grant select on label_gap to authenticated;

-- ───────────────────────────── the label changes of an ingredient ─────────────────────────────
create function label_changes(p_ingredient uuid, p_from date, p_to date) returns jsonb
language plpgsql stable security definer set search_path = public as $$
begin
  perform ingredient_screen_check(p_ingredient, p_from, p_to);
  return coalesce((
    with ours as (
      -- the newest current version of our label for the ingredient: the one the screen compares with
      select ol.id, ol.product_name, ol.version, ol.lang, ol.uploaded_at, p.full_name as uploaded_by
        from our_label ol
        left join person p on p.id = ol.uploaded_by
       where ol.ingredient_id = p_ingredient and ol.superseded_at is null
       order by ol.uploaded_at desc, ol.id
       limit 1
    )
    select jsonb_agg(jsonb_build_object(
             'change_id', sc.id,
             'detected_at', sc.created_at,
             'detected_day', (sc.created_at at time zone 'Africa/Cairo')::date,
             'label_date', t.doc_date,
             'previous_label_date', f.doc_date,
             'product', jsonb_build_object(
               'id', sp.id,
               'name', sp.product_name,
               'mah', sp.mah,
               'country_code', sp.country_code,
               'country_name', r.country_name,
               'source_id', s.id,
               'regulator_id', r.id,
               'regulator_name', r.name,
               'url', sp.url,
               'is_reference', sp.is_reference),
             'lang', coalesce(d.lang, s.languages[1]),
             'link', case when d.id is not null then document_link(d, s, r)
                          else coalesce(sp.url, s.page_url, r.homepage) end,
             'document_id', d.id,
             'title', coalesce(d.title_orig, sp.product_name || ' — ' || array_to_string(sc.sections, ', ')),
             'sections', to_jsonb(sc.sections),
             'diff', sc.diff,
             'gap', lg.gap,
             'gap_at', lg.computed_at,
             'our_label', case when o.id is not null then
               jsonb_build_object('id', o.id, 'product_name', o.product_name, 'version', o.version,
                                  'lang', o.lang, 'uploaded_at', o.uploaded_at, 'uploaded_by', o.uploaded_by) end,
             'issue_id', i.id,
             'issue_status', i.status,
             'is_backfill', coalesce(d.is_backfill, false) or coalesce(i.is_backfill, false),
             'decision', dec.j
           ) order by sp.is_reference desc, sc.created_at desc, sc.id)
      from spc_change sc
      join spc_product sp on sp.id = sc.spc_product_id
      join source s on s.id = sp.source_id
      join regulator r on r.id = s.regulator_id
      join spc_snapshot t on t.id = sc.to_snapshot
      left join spc_snapshot f on f.id = sc.from_snapshot
      left join issue i on i.id = sc.issue_id
      left join document d on d.id = i.anchor_document_id
      left join ours o on true
      left join lateral (
        select lg.gap, lg.computed_at
          from label_gap lg
         where lg.spc_change_id = sc.id and lg.our_label_id = o.id
         limit 1
      ) lg on true
      left join lateral (
        select jsonb_build_object('to_status', re.to_status, 'person', p.full_name,
                                  'at', re.created_at, 'comment', re.comment) as j
          from review_event re
          join person p on p.id = re.person_id
         where re.issue_id = i.id
         order by re.created_at desc, re.id desc
         limit 1
      ) dec on true
     where sp.ingredient_id = p_ingredient
       and (sc.created_at at time zone 'Africa/Cairo')::date between p_from and p_to
  ), '[]'::jsonb);
end $$;
revoke all on function label_changes(uuid, date, date) from public, anon;
grant execute on function label_changes(uuid, date, date) to authenticated;

create index if not exists spc_change_product_created_idx on spc_change (spc_product_id, created_at desc);
