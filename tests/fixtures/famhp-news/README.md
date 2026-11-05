# famhp-news (PHAROS fixture)

Source: https://www.afmps.be/fr/news (AFMPS/FAGG, Belgium; French and Dutch).

On 4 November 2026 a plain request answered an F5 "TSPD" JavaScript interstitial instead of the news list:
`challenge_fr.html` is that answer, saved as received. The parser (`famhp.py`) reads the page with
the headless browser and raises `SourceBlocked` if it still ends on the interstitial; it never tries
to get past it. The live list markup was therefore not seen; the parser uses link mode
(`/<lang>/news/<slug>`).

On 5 November 2026 both lists were seen in a browser (the interstitial cleared by itself): `/fr/news`
forwards to `/fr/actualites` and `/nl/news` to `/nl/nieuws`; ten `/<lang>/news/<slug>` links a page, each
with its title and summary but **no date**. The date is on the news page itself, in the
publication-date field ("Date: 15/10/2026" / "Datum: 15/10/2026"); the "last updated" stamp below
it is a different date. `detail_fr.html` and `detail_nl.html` are trimmed slices of the same news
item in both languages (title, date field, first paragraph, last-updated block), markup as served.
