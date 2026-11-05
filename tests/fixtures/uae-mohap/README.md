# uae-mohap (PHAROS fixture)

Source tried: https://mohap.gov.ae/ar/media-center/drug-alerts (UAE Ministry of Health and
Prevention; Arabic/English).

Unreachable on 4 November 2026: the connection was reset (curl error 35) before any byte was received. No page
saved, so `generic_html` has no preset for this source; its `item_selector`/`link_pattern` must be
set in sources.yaml once the page has been seen (the source should stay disabled until then).

Tried again on 5 November 2026 from three networks: this machine (Egypt), an outside fetch service and
GitHub's runners (the website's link test, run 42075843713): every one ended in "Connection reset by
peer" before any reply. The site answers only networks it accepts, so the source stays off.
