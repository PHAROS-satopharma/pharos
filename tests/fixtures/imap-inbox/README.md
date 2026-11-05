# imap-inbox — a constructed message

`fimea-newsletter.eml` is **constructed for the tests**, not captured: it was written by hand to the
shape of a Fimea newsletter so `tests/test_run_imap.py` can exercise the mailbox reader without a
real mailbox. It is the one non-live fixture in `tests/fixtures/`. Fimea did not send it, and its
text says so.

Its first header is the verdict a receiving server (Yahoo, which hosts the PHAROS mailbox) writes:
`Authentication-Results` with DKIM, SPF and DMARC passing for fimea.fi. The reader accepts a message only
with such a verdict.

`fda-dkim-signed.eml` is also **constructed for the tests**: a short message shaped like GovDelivery's FDA
mail, DKIM-signed for d=public.govdelivery.com with a throwaway key (selector `pharos-test`) made only for
this. The private key was discarded; `fda-dkim-dns.txt` is its public half, the DNS record the tests serve
in place of a real lookup. It has no Authentication-Results header, as Yahoo's IMAP handed over the real
FDA welcome mail on 5 Nov 2026, so the reader must check the signature itself.
