"""Source manifests (corpus_mx/manifest_*.json): load, validate ids and recompute hashes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from .models import DOC_ID_RE, SourceDoc
from .paths import resolve


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_jurisdiction(doc_id: str) -> str | None:
    m = DOC_ID_RE.match(doc_id)
    return m.group(1) if m else None


@dataclass
class DocCheck:
    doc: SourceDoc | None
    manifest: str
    status: str = "ok"                   # ok | hash_mismatch | missing_file | invalid
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    text_sha256_computed: str | None = None
    text_file: Path | None = None
    raw: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass
class Sources:
    docs: dict[str, DocCheck]           # doc_id -> check (only entries with a parseable doc_id)
    errors: list[str]                    # manifest-level errors (bad JSON, duplicate ids, schema)
    manifests: list[str]

    def valid(self) -> dict[str, DocCheck]:
        return {k: v for k, v in self.docs.items() if v.ok}


def _check_doc(raw: dict, manifest: str, corpus: Path) -> tuple[str | None, DocCheck]:
    did = raw.get("doc_id") if isinstance(raw, dict) else None
    try:
        doc = SourceDoc(**raw)
    except (ValidationError, TypeError) as e:
        c = DocCheck(None, manifest, "invalid", raw=raw if isinstance(raw, dict) else None)
        c.errors.append(f"esquema inválido: {e}".replace("\n", " "))
        return did, c
    c = DocCheck(doc, manifest, raw=raw)
    juris = doc_jurisdiction(doc.doc_id)
    if juris is None:
        c.status = "invalid"
        c.errors.append(f"doc_id {doc.doc_id!r} no cumple ^D-MX-(FED|INEGI|ABBR)-NN$")
    elif juris != "INEGI" and doc.jurisdiction != juris:
        c.status = "invalid"
        c.errors.append(f"jurisdiction {doc.jurisdiction!r} no coincide con el doc_id ({juris})")
    if juris == "FED" and not doc.last_reform:
        # Blueprint §1.11 asks for it (vigencia); a warning so a missing date never hides a valid quote.
        c.warnings.append("documento FED sin last_reform: vigencia no documentada en el manifiesto")
    fp = resolve(doc.file_path, corpus)
    if not fp.exists():
        if doc.file_in_repo:
            c.status = "missing_file"
            c.errors.append(f"no existe file_path {doc.file_path}")
        else:
            c.warnings.append(f"{doc.file_path} no está versionado (file_in_repo: false); sha256 no comprobado")
    elif sha256_file(fp) != doc.sha256:
        c.status = "hash_mismatch"
        c.errors.append("sha256 del archivo no coincide con el manifiesto")
    for df in doc.derived_files:
        dp = resolve(df.file_path, corpus)
        if not dp.exists():
            c.warnings.append(f"no existe el archivo derivado {df.file_path}")
        elif sha256_file(dp) != df.sha256:
            c.status = "hash_mismatch"
            c.errors.append(f"sha256 del archivo derivado {df.file_path} no coincide")
    if doc.text_path is None:
        return doc.doc_id, c
    tp = resolve(doc.text_path, corpus)
    c.text_file = tp
    if not tp.exists():
        c.status = "missing_file"
        c.errors.append(f"no existe text_path {doc.text_path}")
    else:
        c.text_sha256_computed = sha256_file(tp)
        if doc.text_sha256 is None:
            # A separate .txt (text_path != file_path) with no pin can be edited without detection,
            # so it could back a fabricated quote. Require the pin; without it the document cannot
            # support a quote. (When text_path == file_path the file hash already pins the text.)
            if doc.text_path != doc.file_path:
                c.status = "invalid"
                c.errors.append("manifiesto sin text_sha256 para un .txt aparte del archivo original: "
                                f"no puede respaldar citas (calculado: {c.text_sha256_computed})")
            else:
                c.warnings.append("manifiesto sin text_sha256: integridad del .txt no comprobable "
                                  f"(calculado: {c.text_sha256_computed})")
        elif doc.text_sha256 != c.text_sha256_computed:
            c.status = "hash_mismatch"
            c.errors.append("text_sha256 del .txt no coincide con el manifiesto (texto alterado)")
    return doc.doc_id, c


def load_manifests(corpus: Path) -> Sources:
    docs: dict[str, DocCheck] = {}
    errors: list[str] = []
    names = sorted(corpus.glob("manifest_*.json")) if corpus.exists() else []
    for path in names:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data["docs"]
            assert isinstance(items, list)
        except (ValueError, KeyError, AssertionError) as e:
            errors.append(f"{path.name}: no se pudo leer {{'docs': [...]}} ({e})")
            continue
        for raw in items:
            did, check = _check_doc(raw, path.name, corpus)
            if did is None:
                errors.append(f"{path.name}: documento sin doc_id")
                continue
            if did in docs:
                errors.append(f"doc_id duplicado {did} ({docs[did].manifest}, {path.name})")
                docs[did].status = "invalid"
                docs[did].errors.append("doc_id duplicado")
                continue
            docs[did] = check
    return Sources(docs, errors, [p.name for p in names])


_TEXT_CACHE: dict[tuple[str, str], str] = {}


def doc_text(check: DocCheck) -> str:
    """Text of a document, cached by (doc_id, text hash)."""
    key = (check.doc.doc_id, check.text_sha256_computed or "")
    if key not in _TEXT_CACHE:
        _TEXT_CACHE[key] = check.text_file.read_text(encoding="utf-8")
    return _TEXT_CACHE[key]


def public_doc(check: DocCheck) -> dict:
    d = check.doc
    return {"doc_id": d.doc_id, "title": d.title, "publisher": d.publisher, "jurisdiction": d.jurisdiction,
            "url": str(d.url), "retrieved_at": d.retrieved_at.isoformat().replace("+00:00", "Z"),
            "sha256": d.sha256, "text_sha256": d.text_sha256 or check.text_sha256_computed,
            "text_sha256_in_manifest": d.text_sha256 is not None, "last_reform": d.last_reform,
            "text_extractor": d.text_extractor, "file_path": d.file_path, "text_path": d.text_path,
            "file_in_repo": d.file_in_repo}
