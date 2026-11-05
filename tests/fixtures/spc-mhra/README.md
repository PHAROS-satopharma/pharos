# spc-mhra (PHAROS fixture)

`search_naproxen.html` — https://products.mhra.gov.uk/search/?search=naproxen&page=1&doc=Spc&rerouteType=0
as a plain request got it on 4 November 2026: a static Next.js export showing "Loading results for …"; the
results are drawn by script. The SPC module reads it with the headless browser.

`search_lornoxicam_agreed.html` and `search_naproxen_agreed.html`: the result rows (`div.search-result`)
that the same searches showed in a browser on 5 November 2026, after the disclaimer box was ticked and
Agree was pressed. Only the result markup was copied; the page around it is a minimal wrapper. The
first four of the 51 lornoxicam hits are fluconazole SPCs that mention lornoxicam only among their
interactions. The first three naproxen hits are naproxen SPCs. The licence number is in the file name,
"PL 00142-0278".
