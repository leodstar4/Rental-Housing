"""Verify every requirement quote against the downloaded official text.

``python -m mx.verify`` writes out/mx_validation.json and exits 1 if any quote fails, any
document fails its hash checks, or a manifest/YAML is malformed.

Quote cascade (no fuzzy matching, no LLM retry; same steps as
``extractor.validate.match_span(raw, quote, allow_fuzzy=False)``, with the normalized
text cached per document because the civil codes are several MB):

1. ``exact``          substring of the text.
2. ``normalized``     whitespace runs / line breaks collapsed, then curly quotes, dashes and
                      NBSP folded (``extractor.clean._normalize_with_map`` / ``_QUOTE_FOLD``).
3. ``normalized_mx``  same as 2 after a Spanish-PDF pre-fold of both texts: soft hyphen removed,
                      end-of-line hyphenation joined (``(\\w)-\\n(\\w)``) and «» → ".
                      The pre-fold keeps an index map, so offsets are never reordered and
                      the literal source fragment is recovered.

Both texts are NFC-normalized first. The API serves ``quote_verified``: the literal source
fragment with whitespace runs collapsed.
"""

from __future__ import annotations

import bisect
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

from extractor.clean import _normalize_with_map

from . import paths
from .models import REQ_ID_RE, Requirement
from .sources import DocCheck, Sources, doc_jurisdiction, doc_text, load_manifests

QUOTE_MIN, QUOTE_MAX = 40, 1500
_ARTICLE = re.compile(r"Art[íi]culo\s+(\d+)", re.IGNORECASE)
_NUM_WORDS = {1: ("un", "uno", "una"), 2: ("dos",), 3: ("tres",), 4: ("cuatro",), 5: ("cinco",), 6: ("seis",),
              7: ("siete",), 8: ("ocho",), 9: ("nueve",), 10: ("diez",), 11: ("once",), 12: ("doce",)}


def mx_fold(text: str) -> tuple[str, list[int]]:
    """Spanish-PDF pre-fold with an index map (folded char i came from text[idx[i]])."""
    out: list[str] = []
    idx: list[int] = []
    n, i = len(text), 0
    while i < n:
        ch = text[i]
        if ch == "­":
            i += 1
            continue
        if ch == "-" and i > 0 and text[i - 1].isalnum():
            j = i + 1
            if j < n and text[j] == "\r":
                j += 1
            if j < n and text[j] == "\n" and j + 1 < n and text[j + 1].isalnum():
                i = j + 1
                continue
        out.append('"' if ch in "«»" else ch)
        idx.append(i)
        i += 1
    return "".join(out), idx


class DocIndex:
    """NFC text of one document plus lazily built normalization maps."""

    def __init__(self, raw: str):
        self.raw = unicodedata.normalize("NFC", raw)
        self._norm: dict[bool, tuple[str, list[int]]] = {}
        self._mx: tuple[str, list[int]] | None = None
        self._mx_norm: dict[bool, tuple[str, list[int]]] = {}
        self._articles: tuple[list[int], list[str]] | None = None

    def norm(self, fold: bool):
        if fold not in self._norm:
            self._norm[fold] = _normalize_with_map(self.raw, fold)
        return self._norm[fold]

    def mx(self):
        if self._mx is None:
            self._mx = mx_fold(self.raw)
        return self._mx

    def mx_norm(self, fold: bool):
        if fold not in self._mx_norm:
            self._mx_norm[fold] = _normalize_with_map(self.mx()[0], fold)
        return self._mx_norm[fold]

    def articles(self):
        if self._articles is None:
            ms = list(_ARTICLE.finditer(self.raw))
            self._articles = ([m.start() for m in ms], [m.group(1) for m in ms])
        return self._articles

    def match(self, quote: str) -> tuple[str, int, int] | None:
        q = unicodedata.normalize("NFC", quote).strip()
        if not q:
            return None
        k = self.raw.find(q)
        if k >= 0:
            return "exact", k, k + len(q)
        for fold in (False, True):
            nr, idx = self.norm(fold)
            nq = _normalize_with_map(q, fold)[0]
            k = nr.find(nq) if nq else -1
            if k >= 0:
                return "normalized", idx[k], idx[k + len(nq) - 1] + 1
        mtext, mmap = self.mx()
        mq = mx_fold(q)[0]
        for fold in (False, True):
            nr, idx = self.mx_norm(fold)
            nq = _normalize_with_map(mq, fold)[0]
            k = nr.find(nq) if nq else -1
            if k >= 0:
                a, b = idx[k], idx[k + len(nq) - 1]
                return "normalized_mx", mmap[a], mmap[b] + 1
        return None

    def anchors(self, start: int, end: int) -> list[str]:
        """Article numbers: the nearest heading before ``start`` plus any inside the span."""
        pos, nums = self.articles()
        i = bisect.bisect_right(pos, start) - 1
        out = [nums[i]] if i >= 0 else []
        j = bisect.bisect_left(pos, start)
        while j < len(pos) and pos[j] < end:
            out.append(nums[j])
            j += 1
        return out


@dataclass
class ReqResult:
    id: str
    file: str
    status: str = "failed"              # verified | failed
    match_type: str | None = None
    raw_start: int | None = None
    raw_end: int | None = None
    quote_verified: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    req: Requirement | None = None

    def as_json(self) -> dict:
        return {"id": self.id, "file": self.file, "status": self.status, "match_type": self.match_type,
                "raw_start": self.raw_start, "raw_end": self.raw_end, "errors": self.errors,
                "warnings": self.warnings}


@dataclass
class VerifiedRequirement:
    req: Requirement
    doc: DocCheck
    match_type: str
    quote_verified: str


@dataclass
class ValidationReport:
    sources: Sources
    results: list[ReqResult]
    errors: list[str]                   # file-level errors (YAML, duplicates, zones)
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return (not self.errors and not self.sources.errors and all(r.status == "verified" for r in self.results)
                and all(c.ok for c in self.sources.docs.values()))

    def verified(self) -> dict[str, VerifiedRequirement]:
        return {r.id: VerifiedRequirement(r.req, self.sources.docs[r.req.doc_id], r.match_type, r.quote_verified)
                for r in self.results if r.status == "verified"}

    def as_json(self) -> dict:
        docs = {did: {"manifest": c.manifest, "status": c.status, "errors": c.errors, "warnings": c.warnings,
                      "text_sha256_computed": c.text_sha256_computed} for did, c in sorted(self.sources.docs.items())}
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ok": self.ok,
            "counts": {"documents": len(self.sources.docs),
                       "documents_ok": sum(c.ok for c in self.sources.docs.values()),
                       "requirements": len(self.results),
                       "verified": sum(r.status == "verified" for r in self.results),
                       "failed": sum(r.status != "verified" for r in self.results),
                       "by_match_type": _count(r.match_type for r in self.results if r.match_type),
                       "warnings": len(self.warnings) + sum(len(r.warnings) for r in self.results)},
            "manifests": self.sources.manifests,
            "errors": self.sources.errors + self.errors,
            "warnings": self.warnings,
            "documents": docs,
            "requirements": [r.as_json() for r in self.results],
        }


def _count(xs) -> dict:
    out: dict[str, int] = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def _value_in_quote(value, quote: str) -> bool:
    q = quote.casefold()
    s = format(value.normalize(), "f") if value == value.to_integral() else str(value)
    if re.search(rf"(?<![\d.,]){re.escape(s)}(?![\d])", q):
        return True
    words = _NUM_WORDS.get(int(value), ()) if value == value.to_integral() else ()
    return any(re.search(rf"\b{w}\b", q) for w in words)


def verify_requirement(req: Requirement, file_stem: str, sources: Sources, index: dict[str, DocIndex],
                       res: ReqResult) -> None:
    m = REQ_ID_RE.match(req.id)
    if not m:
        res.errors.append(f"id {req.id!r} no cumple ^MX-(FED|ABBR)-TEMA-NN$")
    elif not (m.group(1) == req.jurisdiction == file_stem):
        res.errors.append(f"prefijo del id, jurisdiction ({req.jurisdiction}) y archivo ({file_stem}.yaml) no coinciden")
    if req.kind == "practica" and req.applies_to_contract:
        res.errors.append("kind: practica no puede tener applies_to_contract: true")
    if not req.reviewed_by:
        res.warnings.append("sin reviewed_by")
    # Measure after removing soft hyphens (U+00AD): the mx pre-fold strips them, so counting them
    # toward QUOTE_MIN would let a trivial quote padded with soft hyphens clear the minimum.
    nq = " ".join(req.quote.replace("\u00ad", "").split())
    if not QUOTE_MIN <= len(nq) <= QUOTE_MAX:
        res.errors.append(f"longitud de quote {len(nq)} fuera de [{QUOTE_MIN}, {QUOTE_MAX}]")
    check = sources.docs.get(req.doc_id)
    if check is None:
        res.errors.append(f"doc_id {req.doc_id} no está en ningún manifest_*.json")
    elif not check.ok:
        res.errors.append(f"documento {req.doc_id} inválido ({check.status})")
    elif check.text_file is None:
        res.errors.append(f"documento {req.doc_id} no tiene text_path: no puede respaldar una cita")
    elif doc_jurisdiction(req.doc_id) != req.jurisdiction:
        res.errors.append(f"un requisito {req.jurisdiction} no puede citar {req.doc_id}")
    for c in req.checks:
        if not _value_in_quote(c.value, req.quote):
            res.errors.append(f"check {c.field} {c.op} {c.value}: el número no aparece en la quote")
    if res.errors:
        return
    if req.doc_id not in index:
        index[req.doc_id] = DocIndex(doc_text(check))
    di = index[req.doc_id]
    found = di.match(req.quote)
    if found is None:
        res.errors.append("quote no encontrada en el texto (exacto/normalizado)")
        return
    res.match_type, res.raw_start, res.raw_end = found
    res.quote_verified = " ".join(di.raw[res.raw_start:res.raw_end].split())
    nums = di.anchors(res.raw_start, res.raw_end)
    if nums and not any(re.search(rf"(?<!\d){n}(?!\d)", req.citation) for n in nums):
        res.warnings.append(f"ancla de artículo: el texto cercano dice Artículo {'/'.join(dict.fromkeys(nums))}, "
                            f"la citation dice {req.citation!r}")
    res.status = "verified"
    res.req = req


def load_requirement_files(data_root: Path) -> tuple[list[tuple[str, str, dict]], list[str]]:
    """[(file name, stem, raw item)], errors."""
    items, errors = [], []
    folder = data_root / "requirements"
    for path in sorted(folder.glob("*.yaml")) if folder.exists() else []:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            errors.append(f"{path.name}: YAML inválido ({e})".replace("\n", " "))
            continue
        if data is None:
            continue
        if not isinstance(data, list):
            errors.append(f"{path.name}: se esperaba una lista de requisitos")
            continue
        items.extend((path.name, path.stem, x) for x in data)
    return items, errors


def _zones_errors(data_root: Path, sources: Sources) -> list[str]:
    path = data_root / "zones.json"
    if not path.exists():
        return []
    try:
        z = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"zones.json inválido ({e})"]
    errs = []
    for s in z.get("states", []):
        for m in s.get("municipios", []):
            for k, v in (m.get("stats") or {}).items():
                src = (v or {}).get("source") if isinstance(v, dict) else None
                if not src or src not in sources.docs:
                    errs.append(f"zones.json {s.get('cve_ent')}{m.get('cve_mun')}.{k}: fuente {src!r} no está "
                                "en los manifiestos (la API no la mostrará)")
    return errs[:50] + ([f"... y {len(errs) - 50} más"] if len(errs) > 50 else [])


def verify_all(data_root: Path | None = None, corpus_root: Path | None = None) -> ValidationReport:
    data_root = data_root or paths.data_root()
    corpus_root = corpus_root or paths.corpus_root()
    sources = load_manifests(corpus_root)
    items, errors = load_requirement_files(data_root)
    warnings: list[str] = []
    if not sources.manifests:
        warnings.append(f"sin manifest_*.json en {corpus_root}")
    if not items:
        warnings.append(f"sin requisitos en {data_root / 'requirements'}")
    index: dict[str, DocIndex] = {}
    results: list[ReqResult] = []
    seen: set[str] = set()
    for fname, stem, raw in items:
        rid = raw.get("id", "?") if isinstance(raw, dict) else "?"
        res = ReqResult(str(rid), fname)
        results.append(res)
        try:
            req = Requirement(**raw)
        except (ValidationError, TypeError) as e:
            res.errors.append(f"esquema inválido: {e}".replace("\n", " "))
            continue
        if req.id in seen:
            res.errors.append("id duplicado")
            continue
        seen.add(req.id)
        verify_requirement(req, stem, sources, index, res)
    zone_errs = _zones_errors(data_root, sources)
    return ValidationReport(sources, results, errors + zone_errs, warnings)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    report = verify_all()
    out = paths.validation_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = report.as_json()
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    c = payload["counts"]
    print(f"mx.verify: {c['verified']}/{c['requirements']} citas verificadas, {c['documents_ok']}/{c['documents']} "
          f"documentos íntegros, {c['warnings']} avisos -> {out}")
    for e in payload["errors"]:
        print(f"  ERROR {e}")
    for did, d in payload["documents"].items():
        for e in d["errors"]:
            print(f"  ERROR {did}: {e}")
    for r in payload["requirements"]:
        for e in r["errors"]:
            print(f"  ERROR {r['id']} ({r['file']}): {e}")
    print("OK" if report.ok else "FALLO")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
