"""Load the corpus: manifest rows + text files -> ``Document`` objects.

Each ``corpus/text/Dxxx.txt`` starts with::

    SOURCE: <url>
    RETRIEVED: 2026-10-01 22:35 UTC
    <blank line>
    <body...>

``raw_text`` is the body after that header, byte-for-byte (quotes are verified
against it). Rows whose ``status`` is not ``ok`` or that have no ``text_file``
(``link-only``, ``check-terms``, and D056's 403 capture failure) are excluded;
``links_only.csv`` is never loaded as content.

Note: the manifest ``sha256`` hashes the *original capture* (HTML/PDF bytes),
not the .txt. ``text_sha256`` is computed here over ``raw_text`` and is what
the LLM cache keys on.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .clean import CleanResult, clean

_HEADER = re.compile(r"SOURCE: (?P<url>[^\n]*)\nRETRIEVED: (?P<ts>[^\n]*)\n\n")


@dataclass(frozen=True)
class ManifestRow:
    """One row of ``corpus_manifest.csv`` (strings as in the file)."""

    doc_id: str
    jurisdictions: str
    url: str
    source_type: str
    capture: str
    retrieved_at: str
    sha256: str
    text_file: str
    status: str


@dataclass(frozen=True)
class Document:
    """A loadable corpus document.

    Attributes:
        doc_id: e.g. ``"D022"``.
        jurisdictions: Manifest value split on ``;`` e.g. ``["CA"]``, ``["Boston, MA"]``.
        url: From the ``SOURCE:`` header (checked against the manifest URL).
        retrieved_at: From the ``RETRIEVED:`` header, UTC.
        sha256: Manifest hash of the original capture.
        raw_text: Body after the header, unmodified.
        clean_text: ``clean.clean(raw_text, url).clean_text`` (what the LLM sees).
        source_type: Manifest ``source_type`` (``official``, ``code publisher``...).
        text_sha256: sha256 of ``raw_text`` (UTF-8); cache key component.
        clean_result: Full cleaning result, incl. the clean->raw offset map.
    """

    doc_id: str
    jurisdictions: list[str]
    url: str
    retrieved_at: datetime
    sha256: str
    raw_text: str
    clean_text: str
    source_type: str = ""
    text_sha256: str = ""
    clean_result: CleanResult | None = field(default=None, compare=False, repr=False)


class HeaderError(ValueError):
    """The text file lacks the ``SOURCE:/RETRIEVED:`` header."""


def split_header(file_text: str) -> tuple[str, datetime, str]:
    """Split a corpus file into ``(url, retrieved_at, raw_text)``.

    Consumes exactly ``SOURCE: ...\\n``, ``RETRIEVED: ...\\n`` and one blank line.

    Raises:
        HeaderError: if the header is missing or malformed.
    """
    m = _HEADER.match(file_text)
    if not m:
        raise HeaderError("missing 'SOURCE:/RETRIEVED:' header")
    ts = m.group("ts").strip()
    try:
        retrieved = datetime.strptime(ts.removesuffix(" UTC"), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HeaderError(f"bad RETRIEVED value {ts!r}") from e
    return m.group("url").strip(), retrieved, file_text[m.end():]


def load_manifest(path: Path | None = None) -> list[ManifestRow]:
    """Read every row of ``corpus_manifest.csv`` (defaults to ``config.MANIFEST_PATH``)."""
    with open(path or config.MANIFEST_PATH, encoding="utf-8", newline="") as f:
        return [ManifestRow(**{k: (v or "").strip() for k, v in row.items()}) for row in csv.DictReader(f)]


def is_loadable(row: ManifestRow) -> bool:
    """True iff ``row.status == "ok"`` and ``row.text_file`` is set."""
    return row.status == "ok" and bool(row.text_file)


def load_document(row: ManifestRow, text_dir: Path | None = None) -> Document:
    """Read, split, and clean one document.

    Raises:
        HeaderError: bad header.
        ValueError: header URL differs from the manifest URL.
    """
    text_path = (text_dir or config.TEXT_DIR) / Path(row.text_file).name
    # newline="" keeps the file's bytes as-is (no CRLF translation): quotes are
    # verified against raw_text character by character.
    with open(text_path, encoding="utf-8", newline="") as f:
        url, retrieved, raw = split_header(f.read())
    if url != row.url:
        raise ValueError(f"{row.doc_id}: header URL {url!r} != manifest URL {row.url!r}")
    cr = clean(raw, url)
    return Document(
        doc_id=row.doc_id,
        jurisdictions=[j.strip() for j in row.jurisdictions.split(";") if j.strip()],
        url=url,
        retrieved_at=retrieved,
        sha256=row.sha256,
        raw_text=raw,
        clean_text=cr.clean_text,
        source_type=row.source_type,
        text_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        clean_result=cr,
    )


def load_documents(doc_ids: list[str] | None = None) -> list[Document]:
    """Load all loadable documents (or only ``doc_ids``), sorted by ``doc_id``.

    Raises:
        KeyError: a requested doc_id is unknown or not loadable (link-only etc.).
    """
    rows = {r.doc_id: r for r in load_manifest() if is_loadable(r)}
    if doc_ids:
        missing = [d for d in doc_ids if d not in rows]
        if missing:
            raise KeyError(f"not loadable (unknown, link-only or failed capture): {missing}")
        rows = {d: rows[d] for d in doc_ids}
    return [load_document(rows[d]) for d in sorted(rows)]


def load_path(path: Path) -> Document:
    """Load a single text file by path, looking up its manifest row by file name."""
    name = Path(path).name
    for row in load_manifest():
        if row.text_file and Path(row.text_file).name == name:
            if not is_loadable(row):
                raise KeyError(f"{row.doc_id} is not loadable (status={row.status!r})")
            return load_document(row, Path(path).parent)
    raise KeyError(f"{name} is not in the manifest")


def document_from_file(path: Path, *, doc_id: str, jurisdictions: list[str], source_type: str,
                       sha256: str = "") -> Document:
    """Build a Document from a corpus-format file outside the manifest (corpus/new/)."""
    with open(path, encoding="utf-8", newline="") as f:
        url, retrieved, raw = split_header(f.read())
    cr = clean(raw, url)
    return Document(
        doc_id=doc_id, jurisdictions=jurisdictions, url=url, retrieved_at=retrieved, sha256=sha256,
        raw_text=raw, clean_text=cr.clean_text, source_type=source_type,
        text_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(), clean_result=cr,
    )
