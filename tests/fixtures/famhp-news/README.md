# famhp-news (PHAROS fixture)

Source: https://www.afmps.be/fr/news (AFMPS/FAGG, Belgium; French and Dutch).

On 4 November 2026 a plain request answered an F5 "TSPD" JavaScript interstitial instead of the news list:
`challenge_fr.html` is that answer, saved as received. The parser (`famhp.py`) reads the page with
the headless browser and raises `SourceBlocked` if it still ends on the interstitial; it never tries
to get past it. The live list markup was therefore not seen; the parser uses link mode
(`/<lang>/news/<slug>`).
