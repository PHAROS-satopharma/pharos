-- PHAROS — the label watch reads labels in turn, within the run's time (2026-11-06).
--
-- On 6 Nov 2026 the label watch, with paracetamol's hundreds of products, ran past GitHub's timeout and the
-- run was killed before it reached Japan. The watch now keeps to the run's time budget and reads each
-- source's labels in turn: our reference products first, then labels never read, then the one read longest
-- ago. checked_at is when the collector last read the product's label (a label without text counts as read);
-- null = never. Written only by the collector (collectors/spc/run.py mark_checked).

alter table spc_product add column if not exists checked_at timestamptz;

comment on column spc_product.checked_at is
  'When the label watch last read this label (null = never); the watch reads the oldest first.';
