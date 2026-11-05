-- PHAROS — our own product labels, to check an originator's label change against (2026-11-05).
--
-- The label watch (collectors/spc) finds when an originator's SmPC / PI changes a safety section. This keeps
-- the text of OUR label (the leaflet / SmPC approved for our product) section by section, so the notice can
-- show, for each sentence the originator added, whether our label already says it.
--
-- A label is saved as a new version: the one before it for the same product stays, marked superseded, so
-- the comparison shown on an old notice can be traced to the label that was current then. Reviewers and
-- administrators save labels through save_our_label(); nobody writes the table directly.

create table our_label (
  id             uuid primary key default gen_random_uuid(),
  ingredient_id  uuid not null references ingredient(id) on delete cascade,
  product_name   text not null check (length(trim(product_name)) > 0),
  version        text not null check (length(trim(version)) > 0),   -- "Leaflet approved by EDA, March 2024"
  lang           text not null,                                      -- BCP-47 of the text, e.g. en
  sections       jsonb not null,                                     -- {"4.4": "…", "4.8": "…"}
  file_name      text,
  uploaded_by    uuid not null references person(id),
  uploaded_at    timestamptz not null default now(),
  superseded_at  timestamptz
);
create index on our_label (ingredient_id) where superseded_at is null;

create trigger audit_our_label after insert or update or delete on our_label
  for each row execute function audit_row();

alter table our_label enable row level security;
create policy our_label_read on our_label for select to authenticated using (my_role() is not null);
revoke insert, update, delete, truncate on our_label from anon, authenticated;

create function save_our_label(p_ingredient uuid, p_product text, p_version text, p_lang text,
                               p_sections jsonb, p_file text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := my_person_id();
  v_id     uuid;
  v_key    text;
  v_val    jsonb;
begin
  if v_person is null or my_role() not in ('admin','reviewer') then
    raise exception 'Only a reviewer or an administrator can save our label.' using errcode = '42501';
  end if;
  if not exists (select 1 from ingredient where id = p_ingredient) then
    raise exception 'That ingredient is not on the watchlist.' using errcode = '22023';
  end if;
  if length(coalesce(trim(p_product), '')) = 0 or length(coalesce(trim(p_version), '')) = 0 then
    raise exception 'Give the product name and which version of the label this is.' using errcode = '22023';
  end if;
  if coalesce(trim(p_lang), '') !~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$' then
    raise exception 'Give the language of the label as a code, for example en.' using errcode = '22023';
  end if;
  if jsonb_typeof(p_sections) is distinct from 'object' then
    raise exception 'The label sections must be a map of section number to text.' using errcode = '22023';
  end if;
  for v_key, v_val in select * from jsonb_each(p_sections) loop
    if v_key !~ '^\d{1,2}(\.\d{1,2}){0,2}$' or jsonb_typeof(v_val) <> 'string' then
      raise exception 'Section % is not a numbered section with its text.', v_key using errcode = '22023';
    end if;
  end loop;
  if not exists (select 1 from jsonb_each_text(p_sections) e where e.key like '4.%' and length(trim(e.value)) > 0) then
    raise exception 'No safety section (4.1 to 4.9) was found in this label.' using errcode = '22023';
  end if;

  -- One saving at a time per product, so two saves never leave two current versions.
  perform pg_advisory_xact_lock(hashtext('our_label:' || p_ingredient::text || ':' || lower(trim(p_product))));
  update our_label set superseded_at = now()
   where ingredient_id = p_ingredient and lower(product_name) = lower(trim(p_product)) and superseded_at is null;
  insert into our_label (ingredient_id, product_name, version, lang, sections, file_name, uploaded_by)
  values (p_ingredient, trim(p_product), trim(p_version), trim(p_lang), p_sections, nullif(trim(p_file), ''), v_person)
  returning id into v_id;
  return v_id;
end $$;

revoke all on function save_our_label(uuid, text, text, text, jsonb, text) from public, anon;
grant execute on function save_our_label(uuid, text, text, text, jsonb, text) to authenticated;
