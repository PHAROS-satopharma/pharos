"""The source document as the reader receives it: one or more content blocks of the Messages API.

PDF and photos go in as they are (a ``document`` or an ``image`` block, base64), so the reader sees the pages, the
handwriting and the tables itself. A Word file is unpacked to its text (``word/document.xml``: paragraphs and table
cells, in order). A saved email becomes its headers and body as text, followed by each attachment the reader can
take, at most ``MAX_PARTS`` of them. Anything else is refused with a message the reviewer reads.
"""

from __future__ import annotations

import base64
import email
import io
import zipfile
from email import policy
from email.message import EmailMessage

PDF = "application/pdf"
IMAGES = ("image/png", "image/jpeg", "image/gif", "image/webp")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EML = "message/rfc822"
TEXT = "text/plain"

MAX_PARTS = 10                 # attachments of one email
MAX_TEXT_CHARS = 400_000       # of text sent from one document
MAX_DOCX_XML = 30 * 1024 * 1024
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Unreadable(Exception):
    """The document cannot be given to the reader; the message is for the reviewer."""


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("ascii")


def _text_block(text: str, title: str | None = None) -> dict:
    block: dict = {"type": "document", "source": {"type": "text", "media_type": "text/plain",
                                                  "data": text[:MAX_TEXT_CHARS] or "(empty)"}}
    if title:
        block["title"] = title[:200]
    return block


def docx_text(data: bytes) -> str:
    """The text of a Word file, a paragraph per line (table cells are paragraphs too)."""
    from lxml import etree

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML:
                raise Unreadable("The Word file is too large to read.")
            xml = z.read(info)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise Unreadable("The Word file is damaged or is not a .docx file.") from exc
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    root = etree.fromstring(xml, parser)
    lines = []
    for p in root.iter(f"{_W}p"):
        parts = []
        for node in p.iter(f"{_W}t", f"{_W}tab", f"{_W}br"):
            if node.tag == f"{_W}t":
                parts.append(node.text or "")
            else:
                parts.append("\t" if node.tag == f"{_W}tab" else "\n")
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _html_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    return "\n".join(s.strip() for s in soup.get_text("\n").splitlines() if s.strip())


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1256", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _mime_of(name: str, declared: str, data: bytes) -> str | None:
    """What an attachment really is, from its bytes first (a declared type is only a hint)."""
    lower = (name or "").lower()
    if data.startswith(b"%PDF"):
        return PDF
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"PK\x03\x04") and (lower.endswith(".docx") or declared == DOCX):
        return DOCX
    if b"\x00" not in data[:4096] and (lower.endswith((".txt", ".eml")) or declared in (TEXT, EML)):
        return EML if (lower.endswith(".eml") or declared == EML) else TEXT
    return None


def _email_blocks(data: bytes, depth: int = 0) -> list[dict]:
    msg: EmailMessage = email.message_from_bytes(data, policy=policy.default)  # type: ignore[assignment]
    head = "\n".join(f"{h}: {msg.get(h)}" for h in ("From", "To", "Date", "Subject") if msg.get(h))
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = _html_text(content) if body_part.get_content_type() == "text/html" else content
    blocks = [_text_block(f"{head}\n\n{body}".strip(), "The email")]
    skipped: list[str] = []
    parts = 0
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        if part.get_content_type() == EML:
            inner = part.get_payload(0) if part.is_multipart() else None
            payload = inner.as_bytes() if inner is not None else part.get_payload(decode=True) or b""
        else:
            payload = part.get_payload(decode=True) or b""
        mime = _mime_of(name, part.get_content_type(), payload)
        if mime is None or parts >= MAX_PARTS or (mime == EML and depth >= 1):
            skipped.append(name)
            continue
        parts += 1
        blocks.extend(blocks_for(payload, mime, name, depth + 1))
    if skipped:
        blocks.append(_text_block("Attachments PHAROS could not pass on: " + ", ".join(skipped[:20]),
                                  "Attachments not read"))
    return blocks


def blocks_for(data: bytes, mime: str, name: str | None = None, depth: int = 0) -> list[dict]:
    """The content blocks of one document."""
    if not data:
        raise Unreadable("The document is empty.")
    if mime == PDF:
        block = {"type": "document", "source": {"type": "base64", "media_type": PDF, "data": _b64(data)}}
        if name:
            block["title"] = name[:200]
        return [block]
    if mime in IMAGES:
        return [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": _b64(data)}}]
    if mime == DOCX:
        return [_text_block(docx_text(data), name)]
    if mime == EML:
        return _email_blocks(data, depth)
    if mime.startswith("text/"):
        return [_text_block(_decode_text(data), name)]
    raise Unreadable(f"PHAROS cannot read a file of type {mime}.")
