-- PHAROS — every page in Dr Sama's reference list is read, or says why not (2026-11-06).
--
-- 0032 listed her pages; nine of her safety and DHPC pages were not read, or not fully. Now:
--   EMA home page news                   read by ema-news (EMA's news list), a new source
--   Swissmedic updates                   read by swissmedic-updates, a new source
--   Medsafe Prescriber Update            read by medsafe-prescriber-update, a new source
--   PMDA, safety information by MHLW     read by pmda-mhlw (the Japanese page), a new source
--   Infarmed circulars                   read by infarmed-circulares, which now keeps every circular
--   HPRA newsletters                     read by hpra-notices: each Drug Safety Newsletter is a safety notice
--   MFDS safety letters (health.kr)      read by mfds-letters: health.kr republishes MFDS's own letters
--   Health Canada InfoWatch, FDA press   still not read: both sites refuse the servers PHAROS runs on
--                                        (checked from them on 6 Nov 2026); the note says how to get them
-- A page whose address no longer opens gets the page that replaced it; her address stays in the note.
-- The new sources' rows are made by the collector's next catalogue sync (collectors/sources.yaml); until
-- then the Sources screen shows those pages as not read, since it counts only sources that exist and are on.
-- Matched on (regulator, her address): a page an admin has since moved is left as it is.

update regulator_page p
   set url = v.url, read_by = v.read_by::text[], partial = v.partial, note = v.note
  from (values
  ('EMA', 'https://www.ema.europa.eu/en/homepage', 'https://www.ema.europa.eu/en/homepage', '{ema-news}', false, 'Read from EMA''s news list, every news item; the events and podcasts on this page are not read.'),
  ('HC', 'https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/health-product-infowatch.html', 'https://www.canada.ca/en/health-canada/services/drugs-health-products/medeffect-canada/health-product-infowatch.html', '{}', false, 'Not read: Health Canada''s site does not answer our servers (every request timed out, 6 Nov 2026). Health Canada also sends each issue by e-mail (MedEffect e-Notice).'),
  ('HPRA', 'https://www.hpra.ie/homepage/about-us/publications-forms/newsletters', 'https://www.hpra.ie/safety-information/safety-notices', '{hpra-notices}', false, 'The address in the reference list, https://www.hpra.ie/homepage/about-us/publications-forms/newsletters, no longer opens. HPRA now posts each Drug Safety Newsletter as a safety notice on this page (edition 123, 13 Jul 2026).'),
  ('PMDA', 'https://www.pmda.go.jp/english/safety/info-services/drugs/mhlw-released/0001.html', 'https://www.pmda.go.jp/english/safety/info-services/drugs/mhlw-released/0001.html', '{pmda-mhlw}', false, 'Read from the Japanese page; the English page has not changed since June 2013.'),
  ('MEDSAFE', 'https://www.medsafe.govt.nz/publications/prescriber-update.asp', 'https://www.medsafe.govt.nz/publications/prescriber-update.asp', '{medsafe-prescriber-update}', false, 'Each article of the latest issue, and the issue PDF.'),
  ('INFARMED', 'https://www.infarmed.pt/web/infarmed/circulares?p_p_id=paginasagregadoras_WAR_paginasagregadorasportlet&p_p_lifecycle=1&p_p_state=normal&p_p_mode=view&p_p_col_id=column-1&p_p_col_pos=1&p_p_col_count=2&_paginasagregadoras_WAR_paginasagregadorasportlet_javax.portlet.action=advanceSearch&_paginasagregadoras_WAR_paginasagregadorasportlet_selectedOrderBy=default', 'https://www.infarmed.pt/web/infarmed/circulares?p_p_id=paginasagregadoras_WAR_paginasagregadorasportlet&p_p_lifecycle=1&p_p_state=normal&p_p_mode=view&p_p_col_id=column-1&p_p_col_pos=1&p_p_col_count=2&_paginasagregadoras_WAR_paginasagregadorasportlet_javax.portlet.action=advanceSearch&_paginasagregadoras_WAR_paginasagregadorasportlet_selectedOrderBy=default', '{infarmed-circulares}', false, 'Read from the medicines circulars page, which lists the same circulars, together with Infarmed''s Alerts list.'),
  ('MFDS', 'https://www.health.kr/notice/safety.asp', 'https://www.health.kr/notice/safety.asp', '{mfds-letters}', false, 'health.kr republishes MFDS''s safety letters; the app reads every one of them from MFDS''s own board (nedrug.mfds.go.kr). This address now opens https://www.health.kr/academic/safety-letter.'),
  ('SWISSMEDIC', 'https://www.swissmedic.ch/swissmedic/en/home/news/updates.html', 'https://www.swissmedic.ch/swissmedic/en/home/news/updates.html', '{swissmedic-updates}', false, null),
  ('FDA', 'https://www.fda.gov/', 'https://www.fda.gov/', '{}', false, 'Not read: the FDA''s site refuses our servers. The FDA sends press releases by e-mail (the FDA Press Releases list); once the PHAROS mailbox is subscribed, they arrive with the MedWatch e-mails.')
  ) as v(regulator_id, old_url, url, read_by, partial, note)
 where p.regulator_id = v.regulator_id and p.url = v.old_url;
