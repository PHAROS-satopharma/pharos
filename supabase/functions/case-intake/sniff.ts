// What an uploaded case document really is, from its first bytes; the name decides only between a zip and a Word
// file, and between a saved email and a plain text file. Anything else is refused by the case-intake function.
export const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

function startsWith(b: Uint8Array, sig: number[], at = 0): boolean {
  return sig.every((x, i) => b[at + i] === x);
}

/** What the file really is, from its first bytes (and, for a zip or plain text, its name). */
export function sniff(bytes: Uint8Array, name: string): string | null {
  const lower = name.toLowerCase();
  if (startsWith(bytes, [0x25, 0x50, 0x44, 0x46])) return "application/pdf"; // %PDF
  if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47])) return "image/png";
  if (startsWith(bytes, [0xff, 0xd8, 0xff])) return "image/jpeg";
  if (startsWith(bytes, [0x47, 0x49, 0x46, 0x38])) return "image/gif"; // GIF8
  if (startsWith(bytes, [0x52, 0x49, 0x46, 0x46]) && startsWith(bytes, [0x57, 0x45, 0x42, 0x50], 8)) return "image/webp";
  if (startsWith(bytes, [0x50, 0x4b, 0x03, 0x04]) && lower.endsWith(".docx")) return DOCX;
  // A saved email or a text file: no binary bytes in the first 4 KB.
  const head = bytes.subarray(0, 4096);
  if (head.some((c) => c === 0)) return null;
  if (lower.endsWith(".eml")) return "message/rfc822";
  if (lower.endsWith(".txt")) return "text/plain";
  return null;
}
