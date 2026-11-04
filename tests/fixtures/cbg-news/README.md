# cbg-news (PHAROS fixture)

Source: https://www.cbg-meb.nl/actueel/nieuws (CBG-MEB, Netherlands; Dutch).

`list.html` is the page as a plain request got it on 4 November 2026: a Next.js frame with no news items (they
are drawn client-side). No public JSON or RSS endpoint was found (`/actueel/nieuws/rss` → 404).
The parser (`cbg.py`) reads the rendered page with the headless browser.
