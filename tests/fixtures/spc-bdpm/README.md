# spc-bdpm (PHAROS fixture)

`telechargement.html` — https://base-donnees-publique.medicaments.gouv.fr/telechargement, saved 4 November 2026:
lists the bulk files at `/download/file/CIS_bdpm.txt`, `/download/file/CIS_COMPO_bdpm.txt` …
(each 2.6–4.5 MB, above the 1 MB fixture limit, so not saved). The old
`telechargement.php?fichier=` address answers 404. The new front end is script-driven: the RCP
page address (`affichageDoc.php?specid=<CIS>&typedoc=R`) could not be confirmed from here.
