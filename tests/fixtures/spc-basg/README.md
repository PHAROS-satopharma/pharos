# spc-basg (PHAROS fixture)

BASG Medikamente Info Austria, saved 7 November 2026.

* `search_ivabradin.json`: `POST https://medikamente.basg.gv.at/api/api/v1/medication/search?page=1&size=100`
  with `{"substance": "Ivabradin", …}`: 24 products, ten of them centrally authorised (`EU/…`).
* `137618__DOTC_FACH_INFO.pdf`: `https://medikamente.basg.gv.at/documents/137618__DOTC_FACH_INFO.pdf`, the
  Fachinformation of Ivabradin Stada 5 mg ("Stand der Information" 12.2021).

The front end's script is not saved: it carries the site's token. The tests use a one-line script with a made-up
token instead.
