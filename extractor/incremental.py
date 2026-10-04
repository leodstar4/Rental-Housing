"""Incremental mode (hour 16): add ONE new document on top of a frozen snapshot.

``run_increment(path)``:

1. ingest     .txt / .pdf / .html -> text; saved to ``corpus/new/<doc_id>.txt`` in corpus
              format (SOURCE/RETRIEVED header) + ``<doc_id>.meta.json`` (sha256, retrieval
              date, original file, jurisdiction hint).
2. extract    ONLY this document, with the frozen prompt (aborts if it changed).
3. validate   quote cascade, dates, dispositions.
4. normalize  snapshot rules + the new rules (merges with same-law rules, stage merge),
              keeping the snapshot's team_rule_ids stable.
5. conflicts  + 6. status/export (out/rules.json, schema-validated).

Changes are reported against the snapshot normalized with the current code (baseline),
so only the new document's effect shows up.

Prints a readable summary (new/modified rules, status, effective date and whether it is
derived, new conflicts, time per stage) and writes ``out/increment_<doc_id>.json``.
"""

from __future__ import annotations

import hashlib
import html.parser
import json
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import audit, config
from .conflicts import detect_conflicts
from .corpus import document_from_file, load_documents
from .export import export_rules, to_rule_out
from .extract import _validate, extract_document
from .models import RuleInternal
from .normalize import normalize_rules
from .snapshot import activate, check_frozen_prompt
from .status import compute_status, effective_date_for


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #


class _HTMLText(html.parser.HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "td", "th"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _docx_text(path: Path) -> str:
    """Paragraph text of a .docx (word/document.xml), one paragraph per line; no extra dependency."""
    import xml.etree.ElementTree as ET
    import zipfile

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = ["".join(t.text or "" for t in p.iter(f"{{{ns['w']}}}t")) for p in root.iter(f"{{{ns['w']}}}p")]
    return "\n".join(p for p in paras if p.strip()) + "\n"


def read_text(path: Path) -> str:
    """Plain text of a .txt, .html/.htm or .pdf file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if suffix == ".docx":
        return _docx_text(path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    if suffix in (".html", ".htm"):
        parser = _HTMLText()
        parser.feed(raw)
        text = "".join(parser.parts)
        return re.sub(r"\n\s*\n+", "\n", text).strip() + "\n"
    if suffix in (".txt", ".md", ""):
        return raw
    raise ValueError(f"unsupported file type {suffix!r} (use .txt, .pdf, .html or .docx)")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(config.ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def ingest(path: Path, jurisdiction: str | None) -> tuple[str, Path, dict]:
    """Copy the document into corpus/new/: the original file byte for byte
    (``<doc_id>.source<ext>``, sha256 checked) and its text in corpus format (``<doc_id>.txt``,
    what extraction and quote verification read); return (doc_id, text_path, meta)."""
    blob = path.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_")[:40]
    doc_id = f"NEW-{slug}"
    retrieved = datetime.now(timezone.utc)
    config.NEW_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    source_copy = config.NEW_DOCS_DIR / f"{doc_id}.source{path.suffix.lower()}"
    source_copy.write_bytes(blob)
    if hashlib.sha256(source_copy.read_bytes()).hexdigest() != sha:
        raise RuntimeError(f"copy of {path} does not match its sha256")
    text_path = config.NEW_DOCS_DIR / f"{doc_id}.txt"
    body = read_text(path)
    text_path.write_text(f"SOURCE: file://corpus/new/{path.name}\nRETRIEVED: {retrieved:%Y-%m-%d %H:%M} UTC\n\n{body}",
                         encoding="utf-8", newline="\n")
    meta = {"doc_id": doc_id, "original_file": path.name, "original_sha256": sha,
            "source_copy": _rel(source_copy), "retrieved_at": retrieved.isoformat(timespec="seconds"),
            "jurisdiction_hint": jurisdiction, "text_file": _rel(text_path)}
    (config.NEW_DOCS_DIR / f"{doc_id}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")
    return doc_id, text_path, meta


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #


def _snapshot_rules(snapshot_dir: Path) -> list[RuleInternal]:
    rules: list[RuleInternal] = []
    for f in sorted((snapshot_dir / "extracted").glob("D*.json")):
        rules += [RuleInternal.model_validate(r) for r in json.loads(f.read_text(encoding="utf-8"))["rules"]]
    return rules


def increments(exclude: str | None = None) -> list[dict]:
    """Persisted hour-16 documents (corpus/new/<doc_id>.meta.json + .extracted.json): their
    Document, validated rules and meta. Replayed by `normalize` / `reproduce` with no API call."""
    out = []
    for m in sorted(config.NEW_DOCS_DIR.glob("*.meta.json")) if config.NEW_DOCS_DIR.exists() else []:
        meta = json.loads(m.read_text(encoding="utf-8"))
        doc_id = meta["doc_id"]
        ext = config.NEW_DOCS_DIR / f"{doc_id}.extracted.json"
        if doc_id == exclude or not ext.exists():
            continue
        doc = document_from_file(config.NEW_DOCS_DIR / f"{doc_id}.txt", doc_id=doc_id,
                                 jurisdictions=[meta["jurisdiction_hint"]] if meta.get("jurisdiction_hint") else [],
                                 source_type="user-supplied (incremental)", sha256=meta["original_sha256"])
        rules = [RuleInternal.model_validate(r) for r in json.loads(ext.read_text(encoding="utf-8"))["rules"]]
        out.append({"doc": doc, "rules": rules, "meta": meta})
    return out


def persist_increment(summary: dict) -> dict:
    """Keep an increment: its validated rules (corpus/new/<doc_id>.extracted.json) and the new
    rule ids in its meta, so `reproduce` replays it and Module C reports it as a T6 entry."""
    doc_id = summary["doc_id"]
    src = config.OUT_DIR / "extracted_new" / f"{doc_id}.json"
    (config.NEW_DOCS_DIR / f"{doc_id}.extracted.json").write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))
    meta_path = config.NEW_DOCS_DIR / f"{doc_id}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(new_rule_ids=[r["team_rule_id"] for r in summary["rules"] if r["change"] == "new"],
                modified_rule_ids=[r["team_rule_id"] for r in summary["rules"] if r["change"] == "modified"],
                prompt_version=summary.get("prompt_version"), as_of=summary.get("as_of"))
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")
    return meta


def _conflict_key(c: dict) -> tuple:
    return (c["type"], tuple(sorted(c["rule_ids"])))


def run_increment(path: Path, *, jurisdiction: str | None, snapshot_dir: Path, as_of: date,
                  use_cache: bool = True, ingested: tuple[str, Path, dict] | None = None) -> dict:
    """``ingested``: the result of ``ingest(path, jurisdiction)`` when the caller already copied the
    document (scripts/hour16.py times that step on its own)."""
    timings: dict[str, float] = {}
    run_id = audit.new_run_id()

    def stage(name: str, t0: float) -> float:
        timings[name] = round(time.perf_counter() - t0, 2)
        return time.perf_counter()

    t = time.perf_counter()
    manifest = activate(snapshot_dir, offline=False)
    check_frozen_prompt(snapshot_dir)
    doc_id, text_path, meta = ingested or ingest(path, jurisdiction)
    doc = document_from_file(text_path, doc_id=doc_id, jurisdictions=[jurisdiction] if jurisdiction else [],
                             source_type="user-supplied (incremental)", sha256=meta["original_sha256"])
    t = stage("ingest", t)

    out = extract_document(doc, use_cache=use_cache, run_id=run_id, validate=False)
    if out.error:
        raise RuntimeError(f"extraction failed: {out.error}")
    t = stage("extract (LLM)", t)
    _validate(out, doc, run_id, use_cache)
    new_dir = config.OUT_DIR / "extracted_new"
    new_dir.mkdir(parents=True, exist_ok=True)
    (new_dir / f"{doc_id}.json").write_text(json.dumps(
        {"doc_id": doc_id, "rules": [r.model_dump(mode="json") for r in out.rules],
         "validation": out.validation.to_dict()}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    t = stage("validate", t)

    docs = {d.doc_id: d for d in load_documents()}
    prior = increments(exclude=doc_id)  # documents kept from earlier hour-16 runs
    docs.update({p["doc"].doc_id: p["doc"] for p in prior})
    prior_rules = [r for p in prior for r in p["rules"]]
    existing = json.loads((snapshot_dir / "ids.json").read_text(encoding="utf-8"))
    # Baseline = the snapshot (+ earlier increments) run through the CURRENT normalization (not
    # the snapshot's frozen rules.json, which predates later normalization changes such as the
    # id style), so the diff below shows only what the new document changed.
    base_rules, _ = normalize_rules(_snapshot_rules(snapshot_dir) + prior_rules, docs, existing)
    base_conflicts = detect_conflicts(base_rules)
    before = {r.team_rule_id: to_rule_out(r, as_of).model_dump(mode="json")
              for r in base_rules if r.disposition == "accepted"}
    docs[doc_id] = doc
    rules, rep = normalize_rules(_snapshot_rules(snapshot_dir) + prior_rules + out.rules, docs, existing)
    t = stage("normalize", t)
    conflicts = detect_conflicts(rules)
    t = stage("conflicts", t)
    config.NORMALIZED_PATH.write_text(json.dumps({"rules": [r.model_dump(mode="json") for r in rules]},
                                                 ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    config.CONFLICTS_PATH.write_text(json.dumps({"conflicts": conflicts}, ensure_ascii=False, indent=2),
                                     encoding="utf-8", newline="\n")
    export_rules(rules, as_of)
    t = stage("status + export", t)

    # ---- what changed vs the snapshot baseline ------------------------------------------
    after = {r["team_rule_id"]: r for r in json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]}
    by_id = {r.team_rule_id: r for r in rules if r.team_rule_id and r.disposition == "accepted"}
    touched = {rid for rid, r in by_id.items() if r.source_doc_id == doc_id
               or any(e.source_doc_id == doc_id for e in r.evidence)}
    changed = []
    for rid in sorted(set(after) | set(before)):
        a, b = before.get(rid), after.get(rid)
        if a == b and rid not in touched:
            continue
        kind = "new" if a is None else "removed" if b is None else "modified"
        if kind == "modified" and a == b:
            continue
        entry = {"team_rule_id": rid, "change": kind}
        if b is not None:
            r = by_id[rid]
            eff = effective_date_for(r, as_of)
            derived = next((d for d in r.effective_dates if d.value == eff and d.kind == "effective"), None)
            entry.update({
                "jurisdiction": b["jurisdiction"], "level": b["level"], "category": b["category"],
                "title": b["title"], "citation": b["citation"], "status": compute_status(r, as_of),
                "effective_date": b["effective_date"],
                "effective_date_derived": bool(derived and derived.derived),
                "effective_date_basis": (derived.raw if derived and derived.derived else None),
                "key_value": b["key_value"], "coverage_conditions": b["coverage_conditions"],
                "quoted_span": b["quoted_span"], "confidence": b["confidence"],
                "fields_changed": sorted(k for k in b if a is not None and a.get(k) != b.get(k)),
            })
        changed.append(entry)
    old_conf = {_conflict_key(c) for c in base_conflicts}
    new_conflicts = [c for c in conflicts if _conflict_key(c) not in old_conf]

    summary = {
        "doc_id": doc_id, "as_of": as_of.isoformat(), "snapshot": manifest["snapshot"],
        "prompt_version": manifest["prompt_version"], "ingest": meta,
        "candidates": out.validation.candidates, "validation": out.validation.to_dict(),
        "rules": changed, "new_conflicts": new_conflicts, "timings_s": timings,
        "total_s": round(sum(timings.values()), 2),
        "llm_usage": {k: v for k, v in vars(out.result.usage).items()} if out.result else None,
    }
    (config.OUT_DIR / f"increment_{doc_id}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                            encoding="utf-8", newline="\n")
    audit.append(audit.AuditEvent("increment", run_id, doc_id, data={
        "snapshot": manifest["snapshot"], "rules_changed": [c["team_rule_id"] for c in changed],
        "new_conflicts": len(new_conflicts), "timings_s": timings}))
    return summary


def render(summary: dict) -> str:
    """Human-readable, video-friendly summary."""
    w = 78
    lines = ["=" * w, f" INCREMENTAL RUN  ·  {summary['doc_id']}  ·  as of {summary['as_of']}".ljust(w),
             f" snapshot {summary['snapshot']} (prompt {summary['prompt_version']})  ·  "
             f"{summary['candidates']} candidate rule(s)", "=" * w]
    for r in summary["rules"]:
        lines.append(f"\n [{r['change'].upper()}] {r['team_rule_id']}  ·  {r.get('jurisdiction', '')}  ·  "
                     f"{r.get('level', '')}  ·  {r.get('category', '')}")
        if r["change"] == "removed":
            continue
        lines.append(f"   {r['title']}")
        lines.append(f"   citation       : {r['citation']}")
        lines.append(f"   STATUS         : {r['status']}")
        eff = r["effective_date"] or "—"
        if r["effective_date_derived"]:
            eff += f"   (DERIVED: {r['effective_date_basis']})"
        lines.append(f"   effective_date : {eff}")
        lines.append(f"   key_value      : {r['key_value']}")
        cov = r["coverage_conditions"] or {}
        for e in cov.get("exemption_conditions", []):
            lines.append(f"   exemption      : {e['field']} {e['op']} {e['value']}  ({e['condition'][:60]})")
        if r.get("fields_changed"):
            lines.append(f"   fields changed : {', '.join(r['fields_changed'])}")
        lines.append(f"   quote          : “{r['quoted_span'][:150]}”")
    lines.append(f"\n NEW CONFLICTS: {len(summary['new_conflicts'])}")
    for c in summary["new_conflicts"]:
        lines.append(f"   - {c['type']}: {', '.join(c['rule_ids'])} — {c['detail'][:90]}")
    lines.append("\n TIME PER STAGE")
    for k, v in summary["timings_s"].items():
        lines.append(f"   {k:<16} {v:7.2f} s")
    lines.append(f"   {'TOTAL':<16} {summary['total_s']:7.2f} s")
    lines.append("=" * w)
    return "\n".join(lines)
