-- PHAROS — a case can be uploaded with any past day zero (15 Nov 2026).
-- create_upload_case(), as 0099, without the one-year lower bound on day zero: historical cases (years back)
-- can now be uploaded. Day zero still cannot be in the future. Such a case shows as overdue on the case list
-- (its 15-day clock ran out long ago); the Quality tab's deviation proposals do not cover case clocks and only
-- look at deadlines due on or after deviation_proposals_since, so an old upload proposes nothing.
-- Everything else is exactly 0099's.

create or replace function create_upload_case(p_file_name text, p_mime text, p_sha256 text, p_bytes int, p_day_zero date,
                                   p_ingredient uuid default null, p_product uuid default null,
                                   p_strength uuid default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person uuid := case_require_reviewer();
  v_id     uuid;
  v_name   text := nullif(left(trim(coalesce(p_file_name, '')), 200), '');
  v_ing    uuid;
begin
  if p_sha256 is null or p_sha256 !~ '^[0-9a-f]{64}$' then
    raise exception 'The file''s SHA-256 is not valid.' using errcode = '22023';
  end if;
  if p_mime is null or p_mime not in ('application/pdf','image/png','image/jpeg','image/gif','image/webp','message/rfc822','text/plain',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document') then
    raise exception 'PHAROS reads PDF, photos (PNG, JPEG, GIF, WebP), Word (.docx), saved emails (.eml) and text files.'
      using errcode = '22023';
  end if;
  if p_bytes is null or p_bytes <= 0 or p_bytes > 10 * 1024 * 1024 then
    raise exception 'A case document is at most 10 MB.' using errcode = '22023';
  end if;
  if p_day_zero is null or p_day_zero > case_cairo_today() then
    raise exception 'Day zero is the day the company received the report: today or a past day.'
      using errcode = '22023';
  end if;
  perform case_check_form('{}'::jsonb, p_ingredient);
  v_ing := case_check_product(p_product, p_strength, p_ingredient);

  insert into safety_case (ref, origin, status, ingredient_id, product_id, product_strength_id, file_name, mime,
                           sha256, r2_key, bytes, day_zero, created_by)
  values (case_new_ref(), 'upload', 'queued', v_ing, p_product, p_strength, coalesce(v_name, 'document'), p_mime,
          p_sha256, 'sha256/' || left(p_sha256, 2) || '/' || p_sha256, p_bytes, p_day_zero, v_person)
  returning id into v_id;
  insert into case_event (case_id, step, from_status, to_status, comment, person_id)
  values (v_id, 'received', null, 'queued', coalesce(v_name, 'document'), v_person);
  return v_id;
end $$;
