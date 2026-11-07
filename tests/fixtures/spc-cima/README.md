# spc-cima (PHAROS fixture)

CIMA REST (AEMPS, Spain), saved 4 November 2026:
* `medicamentos.json` — https://cima.aemps.es/cima/rest/medicamentos?practiv1=LORNOXICAM (7 rows).
* `secciones_65059.json` — /cima/rest/docSegmentado/secciones/1?nregistro=65059
* `contenido_65059_4.4.html` — /cima/rest/docSegmentado/contenido/1?nregistro=65059&seccion=4.4
  (served as text/html).
* `FT_65059.html` — https://cima.aemps.es/cima/dochtml/ft/65059/FT_65059.html, the full ficha técnica
  HTML (the fallback when the section list does not answer), saved 5 November 2026.
* `FT_81853.pdf`: `https://cima.aemps.es/cima/pdfs/ft/81853/FT_81853.pdf`, saved 7 November 2026 (ivabradine,
  ficha técnica of March 2017). CIMA lists no HTML ficha técnica for this product; `dochtml/ft/81853/FT_81853.html`
  answers 404.
