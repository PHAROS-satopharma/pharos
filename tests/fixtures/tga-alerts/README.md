# tga-alerts (PHAROS fixture)

Source: https://www.tga.gov.au/safety/safety-alerts (TGA, Australia; English).

Not reachable from the build machine on 4 November 2026: a plain request timed out after 40 s with 0 bytes
(the site drops non-browser clients). No page could be saved, so there is no HTML fixture.
The parser `collectors/parsers/tga.py` reads it with the headless browser (`channel: browser`) and
raises `SourceBlocked` on a challenge page; `tga-email` (newsletter) is the second path in.
Tests cover its option logic only; no page is invented.
