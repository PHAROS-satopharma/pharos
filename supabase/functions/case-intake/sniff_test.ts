// deno test --allow-env supabase/functions/
import { assertEquals } from "jsr:@std/assert@1.0.13";
import { DOCX, sniff } from "./sniff.ts";

const bytes = (s: string) => new TextEncoder().encode(s);

Deno.test("a case document is known by its bytes, not its name", () => {
  assertEquals(sniff(bytes("%PDF-1.7 ..."), "report.txt"), "application/pdf");
  assertEquals(sniff(new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d]), "photo.pdf"), "image/png");
  assertEquals(sniff(new Uint8Array([0xff, 0xd8, 0xff, 0xe0]), "x"), "image/jpeg");
  assertEquals(sniff(bytes("RIFF\x00\x00\x00\x00WEBPVP8 "), "x.webp"), "image/webp");
  assertEquals(sniff(new Uint8Array([0x50, 0x4b, 0x03, 0x04, 1]), "form.docx"), DOCX);
});

Deno.test("text is taken only as a saved email or a text file", () => {
  assertEquals(sniff(bytes("From: a@b.c\r\nSubject: x\r\n\r\nbody"), "fwd.eml"), "message/rfc822");
  assertEquals(sniff(bytes("Patient A.M."), "notes.txt"), "text/plain");
  assertEquals(sniff(bytes("<script>alert(1)</script>"), "page.html"), null);
});

Deno.test("anything else is refused", () => {
  assertEquals(sniff(new Uint8Array([0x4d, 0x5a, 0x90, 0x00]), "tool.exe"), null);
  assertEquals(sniff(new Uint8Array([0x50, 0x4b, 0x03, 0x04, 1]), "archive.zip"), null);
  assertEquals(sniff(new Uint8Array([0x00, 0x01, 0x02]), "data.txt"), null);
});
