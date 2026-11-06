# spc-nedrug (PHAROS fixture)

Korea, MFDS 의약품안전나라 (nedrug.mfds.go.kr), saved 6 November 2026, 23:45–23:50 Cairo, with plain requests.

* `search_ivabradine.html`: `/searchDrug?searchYn=true&page=1&ingrEngName=ivabradine&cancelCode=0`, 총 2 건:
  프로코라란정5밀리그램 (item 200906066) and 프로코라란정7.5밀리그램 (200906065), 한국세르비에(주), ATC C01EB17.
* `search_acetaminophen_p72.html`: `…ingrEngName=acetaminophen&cancelCode=0&sort=ITEM_SEQ&sortOrder=ASC&page=72`,
  the last page of 1,069 products (15 a page): rows 1066–1069. Every page's footer also links item 200500904,
  which is not a result.
* `drb_200906066_NB.xml`, `_EE.xml`, `_UD.xml`: `/pbp/cmn/xml/drb/200906066/NB` (사용상의주의사항), `EE` (효능효과)
  and `UD` (용법용량).
* `hist_200906066_NB.html`: `/pbp/CCBBB01/getItemChangeHistList?itemSeq=200906066&docType=NB&page=1`, two
  versions in `data-docdata`: 2017-11-10 (the published label, the same text as `drb_200906066_NB.xml`) and
  2017-09-23. Between them 일반적 주의, 상호작용 and 임부 및 수유부에 대한 투여 changed; the 이상반응 table changed only
  its cell widths and centring.
