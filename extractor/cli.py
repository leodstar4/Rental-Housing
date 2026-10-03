"""Command line: ``python -m extractor.cli <command>``."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer

from . import config

app = typer.Typer(add_completion=False, help="Module A: extract rule records from the corpus.")

EXTRACTED_DIR = config.OUT_DIR / "extracted"


def _save_and_report(results: list) -> None:
    """Write out/extracted/<doc_id>.json per document, print per-document usage and
    validation, then rebuild the run-wide artifacts from ALL per-document files."""
    from .llm import LLMUsage, estimate_cost

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    total, total_cost = LLMUsage(), 0.0
    typer.echo(
        f"\n{'doc':5} {'cand':>4} {'acc':>3} {'held':>4} {'rej':>3} {'exact':>5} {'norm':>4} {'fuzzy':>5} "
        f"{'retry':>5} {'in':>7} {'c_w':>6} {'c_r':>6} {'out':>6} {'USD':>7}  model"
    )
    for r in results:
        payload = {
            "doc_id": r.doc_id,
            "error": r.error,
            "rules": [x.model_dump(mode="json") for x in r.rules],
            "schema_rejected": r.rejected,
            "validation": r.validation.to_dict() if r.validation else None,
            "llm": None if r.result is None else {
                "model": r.result.model, "served_model": r.result.served_model,
                "prompt_version": r.result.prompt_version, "attempts": r.result.attempts,
                "cache_hit": r.result.usage.cached, "usage": vars(r.result.usage),
                "retry_usage": vars(r.retry_usage), "notes": r.result.tool_input.get("notes"),
            },
        }
        (EXTRACTED_DIR / f"{r.doc_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        if r.error:
            typer.echo(f"{r.doc_id:5} ERROR: {r.error}")
            continue
        u = r.result.usage
        paid = (LLMUsage() if u.cached else u) + r.retry_usage
        cost = estimate_cost(paid, r.result.served_model) or 0.0
        cost += estimate_cost(r.classifier_usage, config.DATE_CLASSIFIER_MODEL) or 0.0  # small model
        total, total_cost = total + paid + r.classifier_usage, total_cost + cost
        v = r.validation
        mt, dp = (v.match_types, v.dispositions) if v else ({}, {})
        typer.echo(
            f"{r.doc_id:5} {v.candidates if v else len(r.rules):4d} {dp.get('accepted', 0):3d} {dp.get('held', 0):4d} "
            f"{dp.get('rejected', 0):3d} {mt.get('exact', 0):5d} {mt.get('normalized', 0):4d} {mt.get('fuzzy', 0):5d} "
            f"{mt.get('retry', 0):5d} {paid.input_tokens:7d} {paid.cache_creation_input_tokens:6d} "
            f"{paid.cache_read_input_tokens:6d} {paid.output_tokens:6d} {cost:7.4f}  "
            f"{r.result.served_model}{' (cache)' if u.cached else ''}"
        )
    typer.echo(
        f"{'RUN':5} cost of API calls made in this run: in={total.input_tokens} cache_w={total.cache_creation_input_tokens} "
        f"cache_r={total.cache_read_input_tokens} out={total.output_tokens} USD={total_cost:.4f}"
    )
    _rebuild_run_artifacts()


def _rebuild_run_artifacts() -> None:
    """out/rules_internal.json (accepted+held), out/rejected.json, out/validation_report.json,
    aggregated over every out/extracted/*.json so partial (--only) runs stay consistent."""
    from collections import Counter

    internal, rejected, per_doc = [], [], {}
    glob_ = {"candidates": 0, "match_types": Counter(), "dispositions": Counter(), "reasons": Counter(),
             "quote_retries": 0, "dates_dropped": 0}
    errors = {}
    for f in sorted(EXTRACTED_DIR.glob("D*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if p.get("error"):
            errors[p["doc_id"]] = p["error"]
        for r in p["rules"]:
            (rejected if r["disposition"] == "rejected" else internal).append(r)
        for s in p.get("schema_rejected", []):
            rejected.append({"source_doc_id": p["doc_id"], "disposition": "rejected",
                             "disposition_reason": "schema_invalid", "errors": s["errors"], "raw": s["raw"]})
        v = p.get("validation")
        if v:
            per_doc[p["doc_id"]] = v
            glob_["candidates"] += v["candidates"]
            glob_["quote_retries"] += v["quote_retries"]
            glob_["dates_dropped"] += v["dates_dropped"]
            for k in ("match_types", "dispositions", "reasons"):
                glob_[k].update(v[k])
    report = {"global": {k: dict(v) if isinstance(v, Counter) else v for k, v in glob_.items()},
              "llm_errors": errors, "per_document": per_doc}
    for path, data in [(config.OUT_DIR / "rules_internal.json", {"rules": internal}),
                       (config.REJECTED_PATH, {"rejected": rejected}),
                       (config.VALIDATION_REPORT_PATH, report)]:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    g = report["global"]
    typer.echo(f"\nALL DOCS: candidates={g['candidates']} match_types={g['match_types']} "
               f"dispositions={g['dispositions']} reasons={g['reasons']} quote_retries={g['quote_retries']} "
               f"dates_dropped={g['dates_dropped']} llm_errors={len(errors)}")
    typer.echo(f"Wrote {config.OUT_DIR / 'rules_internal.json'}, {config.REJECTED_PATH}, {config.VALIDATION_REPORT_PATH}")


@app.command("extract-all")
def extract_all(
    no_cache: bool = typer.Option(False, help="Ignore .cache/ and call the API."),
    only: list[str] = typer.Option(None, help="Restrict to these doc_ids (repeatable)."),
    from_snapshot: Path = typer.Option(None, help="Serve extraction from a frozen snapshot; no API calls."),
) -> None:
    """Load -> clean -> extract + validate all loadable documents (or --only ones)."""
    from .corpus import load_documents
    from .extract import extract_all as run

    if from_snapshot is not None:
        from .snapshot import activate

        m = activate(from_snapshot, offline=True)
        typer.echo(f"[snapshot] {from_snapshot} (prompt {m['prompt_version']}, {m['model']}) - offline, no API calls")
    docs = load_documents(only or None)
    typer.echo(f"Extracting {len(docs)} document(s) with {config.EXTRACT_MODEL} "
               f"(effort={config.EXTRACT_EFFORT}, prompt={config.PROMPT_VERSION}, "
               f"concurrency={config.EXTRACT_CONCURRENCY})")
    _save_and_report(run(docs, use_cache=not no_cache))


DEFAULT_SNAPSHOT = config.SNAPSHOTS_DIR / "a-0.4.0"


@app.command("extract-doc")
def extract_doc(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="New document: .txt, .pdf or .html"),
    jurisdiction: str = typer.Option(None, help='Jurisdiction hint, e.g. "Cambridge, MA".'),
    snapshot: Path = typer.Option(DEFAULT_SNAPSHOT, help="Frozen snapshot for everything else."),
    as_of: datetime = typer.Option(config.DEFAULT_AS_OF.isoformat(), formats=["%Y-%m-%d"]),
    no_cache: bool = typer.Option(False, help="Re-call the API for this document even if cached."),
) -> None:
    """Incremental mode: extract ONE new document with the frozen prompt; everything else comes
    from the snapshot; then validate -> normalize -> status -> conflicts -> export."""
    from .incremental import render, run_increment

    summary = run_increment(path, jurisdiction=jurisdiction, snapshot_dir=snapshot, as_of=as_of.date(),
                            use_cache=not no_cache)
    typer.echo(render(summary))
    typer.echo(f"\nSummary: {config.OUT_DIR / ('increment_' + summary['doc_id'] + '.json')}")


@app.command("snapshot")
def snapshot(name: str = typer.Option(..., help='Snapshot name, e.g. "a-0.4.0".')) -> None:
    """Freeze the current extraction (cache + out/) into snapshots/<name>/ (versioned in git)."""
    from .snapshot import create_snapshot, load_manifest

    dst = create_snapshot(name)
    m = load_manifest(dst)
    typer.echo(f"{dst}: {m['counts']} | prompt {m['prompt_version']} ({m['prompt_sha256'][:12]}) | "
               f"{m['model']} effort={m['effort']} | cost ${m['cost_usd']['total']}")


@app.command("reproduce")
def reproduce(
    snapshot: Path = typer.Option(DEFAULT_SNAPSHOT, help="Frozen snapshot to reproduce from."),
    as_of: datetime = typer.Option(config.DEFAULT_AS_OF.isoformat(), formats=["%Y-%m-%d"]),
) -> None:
    """Rebuild out/rules.json from a snapshot without an API key:
    extract-all --from-snapshot -> normalize -> export."""
    extract_all(no_cache=False, only=None, from_snapshot=snapshot)
    normalize(ids_from=snapshot / "ids.json")
    export(as_of=as_of, out=config.RULES_PATH)


@app.command("normalize")
def normalize(
    ids_from: Path = typer.Option(None, help="ids.json of a snapshot: keep its team_rule_ids stable."),
) -> None:
    """Cross-document normalization + conflicts (no LLM): out/rules_normalized.json, out/conflicts.json."""
    from collections import Counter

    from . import audit
    from .conflicts import detect_conflicts
    from .corpus import load_documents
    from .models import RuleInternal
    from .normalize import CAT_CODES, JUR_CODES, normalize_rules

    rules = []
    for f in sorted(EXTRACTED_DIR.glob("D*.json")):
        rules += [RuleInternal.model_validate(r) for r in json.loads(f.read_text(encoding="utf-8"))["rules"]]
    docs = {d.doc_id: d for d in load_documents()}
    existing = json.loads(ids_from.read_text(encoding="utf-8")) if ids_from else None
    rules, rep = normalize_rules(rules, docs, existing)
    conflicts = detect_conflicts(rules)

    config.NORMALIZED_PATH.write_text(
        json.dumps({"rules": [r.model_dump(mode="json") for r in rules]}, ensure_ascii=False, indent=2),
        encoding="utf-8", newline="\n")
    config.CONFLICTS_PATH.write_text(json.dumps({"conflicts": conflicts}, ensure_ascii=False, indent=2),
                                     encoding="utf-8", newline="\n")
    run_id = audit.new_run_id()
    audit.append(audit.AuditEvent("normalize", run_id, data={
        "dispositions": dict(Counter(r.disposition for r in rules)),
        "resolved_citations": rep.resolved_citations, "defaults_applied": rep.defaults_applied,
        "admin_links": rep.admin_links, "precedence": rep.precedence, "conflicts": len(conflicts)}))
    for c in conflicts:
        audit.append(audit.AuditEvent("conflict_flagged", run_id, data=c))

    typer.echo(f"dispositions: {dict(Counter(r.disposition for r in rules))}")
    typer.echo(f"reasons (held/merged/rejected): "
               f"{dict(Counter(r.disposition_reason for r in rules if r.disposition != 'accepted'))}")
    typer.echo(f"\ncitations resolved (held -> source): {rep.resolved_citations}")
    typer.echo(f"calendar defaults applied: {rep.defaults_applied}")
    typer.echo("\nadministrative figures:")
    for uid, aid, tgt in rep.admin_links:
        typer.echo(f"  {uid:8} -> {tgt or 'HELD administrative_unlinked'}")
    typer.echo(f"\nprecedence: {rep.precedence}")
    typer.echo(f"conflicts: {len(conflicts)} -> {config.CONFLICTS_PATH}")
    cats = list(CAT_CODES)
    typer.echo("\n" + f"{'jurisdiction':18}" + "".join(f"{CAT_CODES[c]:>6}" for c in cats) + "  total")
    for j in JUR_CODES:
        row = [rep.cells.get((j, c), 0) for c in cats]
        typer.echo(f"{j:18}" + "".join(f"{x or '.':>6}" for x in row) + f"  {sum(row):5d}")
    typer.echo(f"{'TOTAL':18}" + "".join(f"{sum(rep.cells.get((j, c), 0) for j in JUR_CODES):>6}" for c in cats)
               + f"  {sum(rep.cells.values()):5d}")


@app.command("export")
def export(
    as_of: datetime = typer.Option(
        config.DEFAULT_AS_OF.isoformat(), formats=["%Y-%m-%d"], help="Query date."
    ),
    out: Path = typer.Option(config.RULES_PATH),
) -> None:
    """Compute status for ``--as-of`` and write schema-valid ``rules.json`` (accepted rules only)."""
    from collections import Counter

    from . import audit
    from .export import export_rules, load_internal

    rules = load_internal()
    path = export_rules(rules, as_of.date(), out)
    data = json.loads(path.read_text(encoding="utf-8"))["rules"]
    audit.append(audit.AuditEvent("export", audit.new_run_id(), data={
        "as_of": as_of.date().isoformat(), "path": str(path), "rules": len(data),
        "status": dict(Counter(r["status"] for r in data))}))
    typer.echo(f"{len(data)} rules -> {path} (as_of {as_of.date()}, schema-valid)")
    typer.echo(f"status: {dict(Counter(r['status'] for r in data))}")


@app.command("smoke-check")
def smoke_check() -> None:
    """Offline dashboard: pipeline invariants, expected citations (measurement only) and
    behaviour checks T1/T3/T4/T5 over the current out/ artifacts. No API calls."""
    from .smoke import render, run

    if not config.NORMALIZED_PATH.exists() or not config.RULES_PATH.exists():
        typer.echo("No outputs yet: run `python -m extractor.cli reproduce` first.")
        raise typer.Exit(1)
    res = run()
    typer.echo(render(res))
    (config.OUT_DIR / "smoke_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    app()
