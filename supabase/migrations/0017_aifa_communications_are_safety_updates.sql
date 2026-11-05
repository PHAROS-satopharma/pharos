-- AIFA's second list (AIFA/EMA communications, adtCategories=1960205) was read as DHPC letters. Its items
-- are communications ("EMA raccomanda…", "AIFA richiama…"); from now on the reader types them
-- safety_update (collectors/parsers/aifa.py, doc_type_by_url). The ones already stored are corrected
-- here: an AIFA notice typed dhpc whose title is not an NIIS ("Nota Informativa Importante…"), and the
-- issues anchored on one. The audit trigger records every changed row.

update issue i
   set doc_type = 'safety_update'
  from document d
 where i.anchor_document_id = d.id
   and d.source_id = 'aifa-sicurezza'
   and d.doc_type = 'dhpc'
   and i.doc_type = 'dhpc'
   and d.title_orig !~* '^\s*nota informativa importante';

update document
   set doc_type = 'safety_update'
 where source_id = 'aifa-sicurezza'
   and doc_type = 'dhpc'
   and title_orig !~* '^\s*nota informativa importante';
