"""Frozen extraction snapshots (versioned in git under ``snapshots/<name>/``).

Layout::

    snapshots/a-0.4.0/
      MANIFEST.json          prompt version + sha256, model, effort, date, cost, documents
      extract_system.md      the frozen prompt
      llm/<doc_id>.json      raw LLM result per document (tool input + usage)
      aux_cache/*.json       quote-retry and date-kind answers used by validation
      extracted/<doc_id>.json  validated rules per document (copy of out/extracted/)
      ids.json               uid -> team_rule_id of the official normalization
      rules.json, conflicts.json  official export (as_of in MANIFEST)

With ``config.SNAPSHOT_DIR`` set (CLI ``--from-snapshot`` / ``reproduce``) extraction is
served from ``llm/`` and validation re-runs locally, so ``out/rules.json`` is reproduced
without an API key.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import config, llm
from .corpus import load_documents


def _sha(path: Path) -> str:
    """sha256 of a file with line endings normalized to LF (robust to git CRLF checkouts)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _copy_lf(src: Path, dst: Path) -> None:
    """Copy a text/JSON artifact with LF line endings (byte-identical across platforms)."""
    dst.write_bytes(Path(src).read_bytes().replace(b"\r\n", b"\n"))


def load_manifest(snapshot_dir: Path) -> dict:
    return json.loads((snapshot_dir / "MANIFEST.json").read_text(encoding="utf-8"))


def create_snapshot(name: str, *, as_of: str | None = None) -> Path:
    """Freeze the current extraction (cache + out/) into ``snapshots/<name>/``."""
    dst = config.SNAPSHOTS_DIR / name
    if dst.exists():
        raise FileExistsError(f"{dst} exists; snapshots are immutable (use a new name)")
    for sub in ("llm", "aux_cache", "extracted"):
        (dst / sub).mkdir(parents=True)

    docs = load_documents()
    documents, usage, missing = {}, llm.LLMUsage(), []
    for d in docs:
        key = llm.cache_key(d.text_sha256, config.PROMPT_VERSION, config.EXTRACT_MODEL, config.EXTRACT_EFFORT)
        src = config.CACHE_DIR / f"{key}.json"
        if not src.exists():
            missing.append(d.doc_id)
            continue
        _copy_lf(src, dst / "llm" / f"{d.doc_id}.json")
        u = json.loads(src.read_text(encoding="utf-8"))["usage"]
        usage = usage + llm.LLMUsage(**{**u, "cached": False})
        documents[d.doc_id] = {"text_sha256": d.text_sha256, "llm_file": f"llm/{d.doc_id}.json",
                               "source_url": d.url, "retrieved_at": d.retrieved_at.isoformat()}
    if missing:
        shutil.rmtree(dst)
        raise RuntimeError(f"no cached extraction for {missing} with the current prompt/model; run extract-all first")

    aux_usage = llm.LLMUsage()
    for f in sorted(config.CACHE_DIR.glob("datekind-*.json")) + sorted(config.CACHE_DIR.glob("quote-*.json")):
        _copy_lf(f, dst / "aux_cache" / f.name)
        u = json.loads(f.read_text(encoding="utf-8")).get("usage")
        if u and f.name.startswith("datekind-"):
            aux_usage = aux_usage + llm.LLMUsage(**{**u, "cached": False})

    for f in sorted((config.OUT_DIR / "extracted").glob("D*.json")):
        _copy_lf(f, dst / "extracted" / f.name)
    normalized = json.loads(config.NORMALIZED_PATH.read_text(encoding="utf-8"))["rules"]
    by_uid = {r["uid"]: r for r in normalized}

    def final_id(uid: str) -> str | None:
        r = by_uid.get(uid)
        while r and r["disposition"] == "merged":
            r = by_uid.get(r["merged_into"])
        return r.get("team_rule_id") if r else None

    ids = {r["uid"]: final_id(r["uid"]) for r in normalized if final_id(r["uid"])}
    (dst / "ids.json").write_text(json.dumps(ids, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    _copy_lf(config.RULES_PATH, dst / "rules.json")
    _copy_lf(config.CONFLICTS_PATH, dst / "conflicts.json")
    _copy_lf(config.EXTRACT_PROMPT_PATH, dst / "extract_system.md")

    extraction_usd = llm.estimate_cost(usage, config.EXTRACT_MODEL) or 0.0
    classifier_usd = llm.estimate_cost(aux_usage, config.DATE_CLASSIFIER_MODEL) or 0.0
    exported = json.loads(config.RULES_PATH.read_text(encoding="utf-8"))["rules"]
    manifest = {
        "snapshot": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_version": config.PROMPT_VERSION,
        "prompt_sha256": _sha(config.EXTRACT_PROMPT_PATH),
        "prompt_fingerprint": llm.prompt_fingerprint(),  # prompt + record_rules schema
        "model": config.EXTRACT_MODEL,
        "effort": config.EXTRACT_EFFORT,
        "date_classifier_model": config.DATE_CLASSIFIER_MODEL,
        "as_of": as_of or config.DEFAULT_AS_OF.isoformat(),
        "cost_usd": {"extraction": round(extraction_usd, 4), "date_classifier": round(classifier_usd, 4),
                     "total": round(extraction_usd + classifier_usd, 4)},
        "tokens": {k: v for k, v in vars(usage).items() if k != "cached"},
        "counts": {"documents": len(documents), "exported_rules": len(exported),
                   "candidates": sum(len(json.loads(f.read_text(encoding="utf-8"))["rules"])
                                     for f in (dst / "extracted").glob("D*.json"))},
        "files_sha256": {"rules.json": _sha(dst / "rules.json"), "ids.json": _sha(dst / "ids.json")},
        "documents": documents,
    }
    (dst / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return dst


def check_frozen_prompt(snapshot_dir: Path) -> None:
    """Abort if prompts/extract_system.md differs from the snapshot's frozen prompt."""
    m = load_manifest(snapshot_dir)
    if _sha(config.EXTRACT_PROMPT_PATH) != m["prompt_sha256"] or config.PROMPT_VERSION != m["prompt_version"]:
        raise RuntimeError(
            f"prompts/extract_system.md ({config.PROMPT_VERSION}) differs from the frozen prompt of "
            f"{snapshot_dir.name} ({m['prompt_version']}); restore it before an incremental run")


def activate(snapshot_dir: Path, *, offline: bool) -> dict:
    """Point the pipeline at a snapshot (and optionally forbid API calls)."""
    m = load_manifest(snapshot_dir)
    config.SNAPSHOT_DIR = snapshot_dir
    config.OFFLINE = offline
    llm._snapshot_index.cache_clear()
    return m
