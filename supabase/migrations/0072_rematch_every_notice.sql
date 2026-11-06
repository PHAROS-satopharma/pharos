-- PHAROS — every watched word is looked for in every stored notice, not only those of the last 12 months
-- (2026-11-06).
--
-- The check of the past (collectors/rematch.py) looked for a new or changed word only in the notices of the
-- last 12 months (app_setting.backfill_months) and then marked the word checked, so nothing older was ever
-- looked at again. On 6 November 2026 an audit found 48 stored notices that name a watched ingredient and
-- carry no link to it, every one older than 6 November 2025: MHRA "Paracetamol and pregnancy" (September
-- 2025), Egypt's paracetamol reminder (June 2025), Health Canada acetaminophen recalls, EMA PSUSAs for
-- levofloxacin, ivabradine and phenylephrine, Denmark's ivabradine letters (2014). A check now covers every
-- stored notice, and only such a check marks its words checked.
--
-- Once, on deploy: every word is due again, so the next checks (15 minutes after each daily run, or the
-- "PHAROS check of the past" workflow by hand) look for it in every stored notice. What they find is history:
-- no Telegram message, no digest. A word that already matched a notice is skipped for that notice.
-- The names found on 6 November to belong to another substance stay as they are (not due): they are removed in
-- their own change and must not reach further back first.
update ingredient_term
   set rematched_at = null
 where rematched_at is not null
   and lower(term) not in ('ofloxacin', 'floxin', 'floxacin', 'ペントキシベリン', 'buchenteer', 'c10h14o4',
                           'canada og japan', 'acetaminophen i usa', 'c9h13no2');

update class_term
   set rematched_at = null
 where rematched_at is not null;
