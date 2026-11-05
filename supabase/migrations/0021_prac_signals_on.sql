-- PHAROS — switch on the EMA PRAC signal recommendations (ema-prac), on the owner's word (2026-11-05).
--
-- The QPPV expects PHAROS to cover signals as well as DHPCs. ema-prac came in as enabled: false,
-- "needs live probe". The live probe of 5 Nov 2026 read 159 PRAC documents (signal recommendations
-- and meeting highlights) with HTTP 200 and no error. The catalogue sets "enabled" only when a source
-- is first added, so the row already in the database is switched on here, once. Its first run stores
-- what it finds as history and sends no alerts (the seed rule).

update source set enabled = true
 where origin = 'catalogue'
   and id = 'ema-prac'
   and not enabled;
