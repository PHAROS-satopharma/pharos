-- PHAROS — the regulator's own version of each label snapshot (2026-11-07).
--
-- Every regulator list the label watch reads names a label's version: DailyMed's SPL version, PMDA's package id
-- (its version suffix), CIMA's document date, EMA's last update of the product information, MHRA's document id.
-- They were kept only on spc_product.extra, overwritten at each run, and never used: a revised label waited its
-- turn among hundreds (paracetamol in Spain is read over two or three weeks), and an unchanged one was read
-- again every week. Now each snapshot keeps the version it was read at; the label watch reads first a label
-- whose listed version moved, and does not read again, for up to 28 days, a label still listed at the version
-- last read (collectors/spc/run.py, plan_reads). Null for snapshots before this and for sources whose list
-- names no version (France's BDPM).

alter table public.spc_snapshot add column if not exists regulator_version text;

comment on column public.spc_snapshot.regulator_version is
  'The label''s version as the regulator''s list gave it when this snapshot was read (0086); null when not given.';
