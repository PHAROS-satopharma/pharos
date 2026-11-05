-- PHAROS — switch off the four web sources whose sites refuse the collectors' network (2026-11-05).
--
-- TGA cuts connections from datacenter addresses, and FDA MedWatch and famhp answer with a bot check
-- that is never bypassed. Each is read from the PV mailbox instead (tga-email, fda-email, famhp-email).
-- The catalogue marks them enabled: false, but the catalogue sets "enabled" only when a source is first
-- added (switching a source off is an admin's call), so the rows already in the database stayed on and
-- failed every run as "Blocks automated reading". The admin switched them off here, once; switching one
-- back on stays a click on the Sources screen.

update source set enabled = false
 where origin = 'catalogue'
   and id in ('tga-alerts', 'tga-updates', 'fda-medwatch', 'famhp-news')
   and enabled;
