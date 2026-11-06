-- PHAROS — a reply, an automatic reply or a subscription mail is not a notice (2026-11-06).
--
-- The mailbox's first three mails became "safety documents" on 5 Nov 2026: famhp's automatic reply
-- ("automatisch antwoord - ADR - réponse automatique"), its reply to the VIG-news sign-up ("RE: Inscription
-- VIG-news / Flash VIG-news") and FDA's "Welcome to FDA's Email Updates". The mail parser now leaves such
-- mails out (NOT_A_NOTICE in collectors/parsers/email_inbox.py, the same rule as mail_not_a_notice below).
-- The three already stored stay in the archive, untouched; new_items() (the Sources screen and section 5 of
-- the weekly report) no longer lists a mail item whose title, the subject as sent, is one of them.
--
-- 1. mail_not_a_notice(subject): the rule.
-- 2. new_items(): as in 0039, without those mail items.

create or replace function mail_not_a_notice(p_subject text) returns boolean
language sql immutable set search_path = public as $$
  select coalesce(p_subject, '') ~* (
           '^\s*(re|aw|sv|antw|antwort|réf|ref|tr|fw|fwd|wg)\s*:'
        || '|automatic reply|auto[- ]?reply|automatisch antwoord|réponse automatique|abwesenheitsnotiz'
        || '|out of office|automaattinen vastaus'
        || '|^\s*welcome to\y|subscription (confirmed|confirmation)|confirm your subscription'
        || '|you are (now )?(subscribed|registered)')
$$;
revoke all on function mail_not_a_notice(text) from public, anon;
grant execute on function mail_not_a_notice(text) to authenticated;

-- As in 0039, and a mail item that is not a notice is left out. create or replace keeps the owner, grants and
-- revokes.
create or replace function new_items(p_from timestamptz, p_to timestamptz default now())
returns table (
  document_id     uuid,
  source_id       text,
  regulator_id    text,
  regulator_name  text,
  country_name    text,
  country_code    text,
  source_kind     source_kind,
  title_orig      text,
  lang            text,
  link            text,
  published_date  date,
  first_seen_at   timestamptz,
  doc_type        doc_type,
  matched         boolean,
  r2_key          text,
  mime            text,
  email_id        uuid,
  email_r2_key    text
)
language sql stable security invoker set search_path = public as $$
  select d.id, d.source_id, r.id, r.name, r.country_name, r.country_code, s.kind, d.title_orig, d.lang,
         document_link(d, s, r),
         d.published_date, d.first_seen_at, d.doc_type,
         exists (select 1 from match m where m.document_id = d.id),
         d.r2_key, d.mime,
         case when d.structured ->> 'inbound_email_id' ~* '^[0-9a-f-]{36}$'
              then (d.structured ->> 'inbound_email_id')::uuid end,
         d.structured ->> 'raw_r2_key'
    from document d
    join source s on s.id = d.source_id
    join regulator r on r.id = s.regulator_id
   where d.first_seen_at >= p_from
     and d.first_seen_at < coalesce(p_to, now())
     and not d.is_backfill
     and s.kind not in ('spc', 'literature')
     and not (s.channel = 'email' and mail_not_a_notice(d.title_orig))
$$;
