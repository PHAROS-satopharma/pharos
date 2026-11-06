"""Content-addressed archive of every original the collectors read.

Objects live in Cloudflare R2 (bucket lock forbids overwrite and delete) under
``sha256/<first 2 hex>/<sha256>``. The hash is always of the original bytes. Text-like originals
(HTML, XML, JSON, plain text) are stored gzipped with ``Content-Encoding: gzip`` so a pre-signed GET
still returns the original; PDFs and images are stored as they are.

When the R2 variables are absent (tests, local dry runs) objects go to ``./.archive/`` instead.

``put(..., meta=…)`` keeps a few words about an original with it (an open-access PDF's licence and version): R2
user metadata on the object (ASCII, each value at most 300 characters), or ``<key>.meta.json`` beside a local
object. Like the object, they are written once and never changed.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_TEXT_MIMES = ("text/", "application/json", "application/xml", "application/rss+xml",
               "application/atom+xml", "application/xhtml+xml", "application/ld+json")


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def key_for(sha: str) -> str:
    return f"sha256/{sha[:2]}/{sha}"


def _is_text(mime: str) -> bool:
    mime = (mime or "").split(";")[0].strip().lower()
    return mime.startswith(_TEXT_MIMES) or mime.endswith("+xml")


META_VALUE_MAX = 300


def clean_meta(meta: dict | None) -> dict[str, str]:
    """User metadata R2 accepts: lower-case names of letters, digits and dashes; ASCII values, at most
    ``META_VALUE_MAX`` characters; empty values left out."""
    out: dict[str, str] = {}
    for name, value in (meta or {}).items():
        key = "".join(c if c.isascii() and (c.isalnum() or c == "-") else "-" for c in str(name).lower()).strip("-")
        text = str(value if value is not None else "").encode("ascii", "replace").decode("ascii")
        text = " ".join(text.split())[:META_VALUE_MAX]
        if key and text and key != "sha256":
            out[key] = text
    return out


class Archive:
    """Write-once store. ``put`` is idempotent: an existing object is never uploaded again."""

    def __init__(self, local_dir: str | os.PathLike | None = None, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.bucket = os.environ.get("R2_BUCKET")
        account = os.environ.get("R2_ACCOUNT_ID")
        key_id = os.environ.get("R2_ACCESS_KEY_ID")
        secret = os.environ.get("R2_SECRET_ACCESS_KEY")
        self._s3 = None
        self._known: set[str] = set()
        self.local_dir = Path(local_dir or os.environ.get("ARCHIVE_DIR", ".archive"))
        if enabled and account and key_id and secret and self.bucket:
            import boto3  # imported lazily: tests and dry runs never need it
            from botocore.config import Config

            self._s3 = boto3.client(
                "s3",
                endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
                aws_access_key_id=key_id,
                aws_secret_access_key=secret,
                region_name="auto",
                config=Config(retries={"max_attempts": 4, "mode": "standard"},
                              signature_version="s3v4"),
            )

    @property
    def backend(self) -> str:
        if not self.enabled:
            return "disabled"
        return "r2" if self._s3 is not None else "local"

    def put(self, content: bytes, mime: str, meta: dict | None = None) -> tuple[str, str]:
        """Store ``content``; return ``(sha256, key)``. Never overwrites an existing object."""
        sha = sha256_hex(content)
        key = key_for(sha)
        if not self.enabled or key in self._known:
            return sha, key
        if self._s3 is not None:
            self._put_r2(key, content, mime, sha, meta=meta)
        else:
            self._put_local(key, content, meta=meta)
        self._known.add(key)
        return sha, key

    def exists(self, key: str) -> bool:
        if not self.enabled:
            return False
        if key in self._known:
            return True
        if self._s3 is None:
            return (self.local_dir / key).exists()
        from botocore.exceptions import ClientError

        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def put_named(self, key: str, content: bytes, mime: str, *, revise: bool = False) -> tuple[str, str]:
        """Store under a fixed key (``inbound/…``, ``reports/…``). Never overwrites: with ``revise``
        a taken key gets ``-r2``, ``-r3`` … before its extension; without it the existing object
        stands. Returns ``(sha256, key actually used)``."""
        if key.startswith(("sha256/", "backups/")):
            raise ValueError(f"put_named may not write under {key.split('/')[0]}/")
        sha = sha256_hex(content)
        if not self.enabled:
            return sha, key
        chosen = key
        if self.exists(chosen):
            if not revise:
                return sha, chosen
            stem, dot, ext = key.rpartition(".")
            n = 2
            while self.exists(chosen := f"{stem}-r{n}{dot}{ext}" if dot else f"{key}-r{n}"):
                n += 1
        if self._s3 is not None:
            self._put_r2(chosen, content, mime, sha, check=False)
        else:
            self._put_local(chosen, content)
        self._known.add(chosen)
        return sha, chosen

    def _put_r2(self, key: str, content: bytes, mime: str, sha: str, *, check: bool = True,
                meta: dict | None = None) -> None:
        if check and self.exists(key):
            return  # already archived; the bucket lock would refuse an overwrite anyway
        extra: dict = {"ContentType": mime or "application/octet-stream",
                       "Metadata": {**clean_meta(meta), "sha256": sha}}
        body = content
        if _is_text(mime):
            body = gzip.compress(content, mtime=0)
            extra["ContentEncoding"] = "gzip"
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, **extra)

    def _put_local(self, key: str, content: bytes, meta: dict | None = None) -> None:
        path = self.local_dir / key
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
        if clean_meta(meta):
            path.with_name(path.name + ".meta.json").write_text(json.dumps(clean_meta(meta), sort_keys=True))

    def meta(self, key: str) -> dict[str, str]:
        """The metadata kept with an original (``sha256`` included on R2); {} when there is none."""
        if not self.enabled:
            return {}
        if self._s3 is not None:
            from botocore.exceptions import ClientError

            try:
                return dict(self._s3.head_object(Bucket=self.bucket, Key=key).get("Metadata") or {})
            except ClientError:
                return {}
        side = self.local_dir / (key + ".meta.json")
        return json.loads(side.read_text()) if side.exists() else {}

    def get(self, key: str) -> bytes | None:
        """Read an original back (used to attach a PDF to a Telegram message). ``None`` if missing."""
        if not self.enabled:
            return None
        if self._s3 is not None:
            from botocore.exceptions import ClientError

            try:
                obj = self._s3.get_object(Bucket=self.bucket, Key=key)
            except ClientError:
                return None
            data = obj["Body"].read()
            if obj.get("ContentEncoding") == "gzip":
                data = gzip.decompress(data)
            return data
        path = self.local_dir / key
        return path.read_bytes() if path.exists() else None
