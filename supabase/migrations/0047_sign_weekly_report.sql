-- PHAROS — inspection evidence, part 2 (2026-11-06, the QPPV plan, phase 14).
--
-- The weekly report is signed as the monthly report was (0030): a reviewer or an administrator types their
-- password again, and the signature carries their name and role at that moment, what it means ("I have
-- reviewed this report" / "I approve this report"), the database time and the SHA-256 of the report as it was
-- signed. sign_off stays append-only; when the week is made again (a new PDF or Excel file, so new hashes on the
-- weekly_report row), record_fingerprint() no longer matches and the Reports page says "File changed since
-- signing".
--
-- 1. record_fingerprint(): the same signature, the same grants and the same answers for the monthly report and
--    the signal; now plpgsql so that a kind that cannot be signed yet can say so.
--    weekly_report: the SHA-256 of pdf_sha256 || ':' || xlsx_sha256, exactly as the monthly report.
--    pack: raises "not yet" (feature_not_supported) — the pack table comes with the next phase, which replaces
--    this branch. The simpler of the two ways: no dynamic read of a table that does not exist yet.
-- 2. sign_record(): a reviewer or an administrator signs a weekly report (or a pack, once it exists), with
--    either meaning. Everything else as 0030: the five-minute password rule, one signature per person, meaning
--    and fingerprint, the monthly report for administrators only, a signal once it is closed.

-- ───────────────────────────── 1. the fingerprint of a record ─────────────────────────────
create or replace function record_fingerprint(p_kind sign_kind, p_id uuid)
returns text language plpgsql stable security definer set search_path = public as $$
declare
  v_sha text;
begin
  if my_role() is null then
    return null;
  end if;
  case p_kind
    when 'monthly_report' then
      select encode(sha256(convert_to(r.pdf_sha256 || ':' || r.xlsx_sha256, 'UTF8')), 'hex') into v_sha
        from monthly_report r where r.id = p_id;
    when 'weekly_report' then
      select encode(sha256(convert_to(r.pdf_sha256 || ':' || r.xlsx_sha256, 'UTF8')), 'hex') into v_sha
        from weekly_report r where r.id = p_id;
    when 'signal' then
      select encode(sha256(convert_to(jsonb_build_object(
                'signal', to_jsonb(s) - 'updated_at',
                'events', (select coalesce(jsonb_agg(e.id order by e.created_at, e.id), '[]') from signal_event e where e.signal_id = s.id),
                'issues', (select coalesce(jsonb_agg(si.issue_id order by si.issue_id), '[]') from signal_issue si where si.signal_id = s.id)
              )::text, 'UTF8')), 'hex') into v_sha
        from signal s where s.id = p_id;
    when 'pack' then
      raise exception 'A pack cannot be signed yet: packs are not yet made in PHAROS.' using errcode = '0A000';
  end case;
  return v_sha;
end $$;
revoke all on function record_fingerprint(sign_kind, uuid) from public, anon;
grant execute on function record_fingerprint(sign_kind, uuid) to authenticated;

-- ───────────────────────────── 2. who signs what ─────────────────────────────
create or replace function sign_record(p_kind sign_kind, p_id uuid, p_meaning sign_meaning, p_comment text default null)
returns uuid language plpgsql security definer set search_path = public as $$
declare
  v_person  person%rowtype;
  v_sha     text;
  v_fresh   boolean;
  v_id      uuid;
begin
  select * into v_person from person where id = my_person_id();
  if v_person.id is null then
    raise exception 'Sign in to sign.' using errcode = '42501';
  end if;
  if p_kind = 'monthly_report' and v_person.role <> 'admin' then
    raise exception 'Only an administrator can sign the monthly report.' using errcode = '42501';
  end if;
  if p_kind = 'signal' and v_person.role not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can sign a signal.' using errcode = '42501';
  end if;
  if p_kind = 'weekly_report' and v_person.role not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can sign the weekly report.' using errcode = '42501';
  end if;
  if p_kind = 'pack' and v_person.role not in ('admin', 'reviewer') then
    raise exception 'Only a reviewer or an administrator can sign a pack.' using errcode = '42501';
  end if;
  select exists (
    select 1 from jsonb_array_elements(coalesce(auth.jwt() -> 'amr', '[]'::jsonb)) a
     where a ->> 'method' = 'password'
       and (a ->> 'timestamp')::bigint >= extract(epoch from now())::bigint - 300
  ) into v_fresh;
  if not v_fresh then
    raise exception 'Enter your password to sign.' using errcode = '28P01';
  end if;
  if p_kind = 'signal' and not exists (select 1 from signal where id = p_id and stage = 'closed') then
    raise exception 'A signal is signed once it is closed.' using errcode = '22023';
  end if;
  v_sha := record_fingerprint(p_kind, p_id);
  if v_sha is null then
    raise exception 'That record does not exist.' using errcode = '22023';
  end if;
  if exists (select 1 from sign_off where record_kind = p_kind and record_id = p_id and record_sha256 = v_sha
                                       and person_id = v_person.id and meaning = p_meaning) then
    raise exception 'You have already signed this record with that meaning.' using errcode = '23505';
  end if;
  insert into sign_off (record_kind, record_id, record_sha256, meaning, person_id, signed_name, signed_role, comment)
  values (p_kind, p_id, v_sha, p_meaning, v_person.id, v_person.full_name, v_person.role,
          nullif(trim(p_comment), ''))
  returning id into v_id;
  return v_id;
end $$;
revoke all on function sign_record(sign_kind, uuid, sign_meaning, text) from public, anon;
grant execute on function sign_record(sign_kind, uuid, sign_meaning, text) to authenticated;
