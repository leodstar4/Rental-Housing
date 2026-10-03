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

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .clean import CleanResult


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
    raise NotImplementedError


def load_manifest(path: Path | None = None) -> list[ManifestRow]:
    """Read every row of ``corpus_manifest.csv`` (defaults to ``config.MANIFEST_PATH``)."""
    raise NotImplementedError


def is_loadable(row: ManifestRow) -> bool:
    """True iff ``row.status == "ok"`` and ``row.text_file`` is set."""
    raise NotImplementedError


def load_document(row: ManifestRow, text_dir: Path | None = None) -> Document:
    """Read, split, and clean one document.

    Raises:
        HeaderError: bad header.
        ValueError: header URL differs from the manifest URL.
    """
    raise NotImplementedError


def load_documents(doc_ids: list[str] | None = None) -> list[Document]:
    """Load all loadable documents (or only ``doc_ids``), sorted by ``doc_id``."""
    raise NotImplementedError


def load_path(path: Path) -> Document:
    """Load a single text file by path, looking up its manifest row by file name."""
    raise NotImplementedError
