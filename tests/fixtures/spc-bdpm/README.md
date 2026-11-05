# spc-bdpm (PHAROS fixture)

`telechargement.html` — https://base-donnees-publique.medicaments.gouv.fr/telechargement, saved 4 November 2026:
lists the bulk files at `/download/file/CIS_bdpm.txt`, `/download/file/CIS_COMPO_bdpm.txt` …
(each 2.6–4.5 MB, above the 1 MB fixture limit, so not saved whole). The old
`telechargement.php?fichier=` address answers 404. The new front end is script-driven: the RCP
page address (`affichageDoc.php?specid=<CIS>&typedoc=R`) could not be confirmed from here.

`CIS_COMPO_slice.txt`, `CIS_slice.txt` — real rows of `CIS_COMPO_bdpm.txt` and `CIS_bdpm.txt`, downloaded
5 November 2026, byte for byte (ISO-8859-1, CRLF, served as `application/octet-stream`), for five
specialities: IBUPROFENE BIOGARAN CONSEIL (60073914, active), IBUPROFENE ZENTIVA FRANCE (64481322,
lysinate SA + ibuprofène FT), IBUPROFENE ALMUS (62611169, abrogée), PEDEA (67747504, EU/1/04/284)
and EFFERALGAN (60025403, paracétamol). Lornoxicam has no French product.
