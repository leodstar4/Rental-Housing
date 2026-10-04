"""Hour 16 (T6) in ONE reproducible command.

    python scripts/hour16.py PATH_TO_DOCUMENT [--jurisdiction "Cambridge, MA"] [--dry-run] [--no-git]

a) copy the document byte for byte to corpus/new/ (sha256, retrieval date); .txt .pdf .html .docx
b) extraction + validation + normalization (Module A), the increment KEPT in corpus/new/,
   coverage compiled into data/compiled_exemptions.json, change tests with the T6 entry
c) T6 summary: new rules, jurisdiction, category, effective date (derived?), status on 2026-10-01,
   affected addresses by city, exemptions applied, new conflicts
d) sanity checks: affected addresses inside the rule's jurisdiction; effective_date set; literal
   quote verified; smoke-check and the T1-T5 dashboard still green. Failures are reported in red;
   no rule is ever edited by hand.
e) regenerate out/lookups.json, out/changes.json, out/rules.json, plain language (new rules only)
   and static/
f) out/hour16_report.md (source, timings, cost, results, checks)
g) without --dry-run / --no-git: git add the kept artifacts, commit "T6: hour-16 ordinance", push

--dry-run runs everything in a temporary copy of the repository and leaves the repo untouched.
Needs ANTHROPIC_API_KEY in .env (one Opus extraction + small Haiku calls).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.system("")  # enable ANSI colours on Windows consoles

G, R, Y, B, D, X = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[2m", "\033[0m"
SANDBOX_ENV = "HOUR16_SANDBOX"
SUPPORTED = {".txt", ".pdf", ".html", ".htm", ".docx"}


class Run:
    """Collects timings, report lines and check results while printing them."""

    def __init__(self):
        self.t0 = time.perf_counter()
        self.timings: dict[str, float] = {}
        self.report: list[str] = []
        self.checks: list[tuple[str, bool, str]] = []
        self.cost: dict[str, float | str] = {}

    def step(self, key: str, title: str):
        run = self

        class _Step:
            def __enter__(self):
                self.t = time.perf_counter()
                print(f"\n{B}[{key}] {title}{X}", flush=True)
                run.report += ["", f"## {key}) {title}", ""]
                return self

            def __exit__(self, *exc):
                dt = time.perf_counter() - self.t
                run.timings[f"{key}) {title}"] = round(dt, 1)
                if exc[0] is None:
                    print(f"{D}    … {dt:.1f} s{X}", flush=True)
                return False

        return _Step()

    def say(self, text: str = "", md: str | None = None) -> None:
        print(f"    {text}", flush=True)
        self.report.append(md if md is not None else text)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))
        mark = f"{G}PASS{X}" if ok else f"{R}FAIL{X}"
        print(f"    [{mark}] {name}{(' — ' + detail) if detail else ''}", flush=True)
        self.report.append(f"- **{'PASS' if ok else 'FAIL'}** {name}{(' — ' + detail) if detail else ''}")


# --------------------------------------------------------------------------- #
# The run (in the repo, or in the sandbox for --dry-run)
# --------------------------------------------------------------------------- #


def hour16(path: Path, jurisdiction: str | None, *, git: bool, dry_run: bool) -> int:
    from extractor import config, incremental, llm
    from extractor.cli import DEFAULT_SNAPSHOT, attest
    from extractor.snapshot import activate
    from resolver import changes as ch
    from resolver.compile_exemptions import compile_all, write_review_table
    from resolver.predicates import render

    run = Run()
    as_of = config.DEFAULT_AS_OF
    print(f"{B}HOUR 16 · {path.name}{X}  ({'DRY RUN in ' + str(ROOT) if dry_run else 'repository ' + str(ROOT)})")
    run.report += [f"# Hour 16 report — {path.name}", "",
                   f"Run: {'dry run (temporary copy)' if dry_run else 'repository'} · as of {as_of} · "
                   "Not legal advice."]

    # a) copy ---------------------------------------------------------------------------------
    with run.step("a", "Copy the document to corpus/new/ (unchanged)"):
        if path.suffix.lower() not in SUPPORTED:
            raise SystemExit(f"unsupported file type {path.suffix} (use {', '.join(sorted(SUPPORTED))})")
        ingested = incremental.ingest(path, jurisdiction)
        doc_id, text_path, meta = ingested
        run.say(f"doc_id        {doc_id}")
        run.say(f"original      {meta['source_copy']}  ({path.stat().st_size:,} bytes, byte-identical copy)")
        run.say(f"sha256        {meta['original_sha256']}")
        run.say(f"retrieved_at  {meta['retrieved_at']}")
        run.say(f"text          {meta['text_file']}  (corpus format; what extraction and quote checks read)")

    # b) pipeline -----------------------------------------------------------------------------
    with run.step("b", "Extract + validate + normalize, compile coverage, change tests (kept)"):
        summary = incremental.run_increment(path, jurisdiction=jurisdiction, snapshot_dir=DEFAULT_SNAPSHOT,
                                            as_of=as_of, ingested=ingested)
        activate(DEFAULT_SNAPSHOT, offline=False)
        for k, v in summary["timings_s"].items():
            run.say(f"{k:<16} {v:6.2f} s")
        meta = incremental.persist_increment(summary)
        attest()
        logs: list[str] = []
        compiled = compile_all(log=logs.append)
        write_review_table(compiled)
        for line in logs:
            run.say(line.strip())
        changes, full, tl = ch.run_all_tests()
        ch.write(changes, full)
        tid = next((k for k, v in full.items() if (v.get("test") or {}).get("doc_id") == doc_id), None)
        run.say(f"change tests written: {', '.join(changes)}  (new document entry: {tid or 'none — no new rule'})")
        usage = summary.get("llm_usage") or {}
        if usage and not usage.get("cached"):
            run.cost["extraction (Opus)"] = round(llm.estimate_cost(llm.LLMUsage(**usage), config.EXTRACT_MODEL) or 0, 4)
        else:
            run.cost["extraction (Opus)"] = "0 (cache hit)"
        for line in logs:
            if "USD≈" in line:
                run.cost["coverage compiler (Haiku)"] = float(line.split("USD≈")[1])

    # c) summary ------------------------------------------------------------------------------
    new_ids = meta.get("new_rule_ids", [])
    eng = tl.engine(as_of)
    rules = {r["team_rule_id"]: r for r in eng.rules}
    with run.step("c", "T6 summary"):
        if not new_ids:
            run.say(f"{Y}no new rule extracted from {doc_id}{X}", "**No new rule extracted.**")
        for r in summary["rules"]:
            rid = r["team_rule_id"]
            run.say(f"{'NEW' if r['change'] == 'new' else 'MODIFIED':8} {rid} · {r.get('jurisdiction')} · "
                    f"{r.get('category')} · {r.get('citation')}", f"- **{r['change'].upper()} {rid}** · "
                    f"{r.get('jurisdiction')} · {r.get('category')} · `{r.get('citation')}`")
            basis = f"derived: {r['effective_date_basis']}" if r.get("effective_date_derived") else "stated in the text"
            run.say(f"         effective_date {r.get('effective_date')} ({basis}); status on {as_of}: {r.get('status')}")
            for e in (compiled["rules"].get(rid) or {}).get("exemptions", []):
                if e["scope"] == "building":
                    run.say(f"         exemption: {e['text'][:90]}  →  {render(e['predicate'])}")
            for c in (compiled["rules"].get(rid) or {}).get("conditions", []):
                if c["scope"] == "building" and c["predicate"] != {"const": True}:
                    run.say(f"         coverage:  {c['text'][:90]}  →  {render(c['predicate'])}")
        if tid:
            e, f = changes[tid], full[tid]
            after = f["test"]["as_of_after"]
            cities = Counter(eng.facts[a]["dataset_city"] for a in e["affected_address_ids"])
            res_after = Counter(x["after"] for d in f["addresses"].values() for x in d.values())
            res_before = Counter(x["before"] for d in f["addresses"].values() for x in d.values())
            run.say(f"{tid}: {len(e['affected_address_ids'])} affected addresses from {after} "
                    f"({', '.join(f'{c} {n}' for c, n in sorted(cities.items())) or 'none'}); "
                    f"conflict-flagged {len(e['conflict_flag_address_ids'])}")
            run.say(f"results on {as_of}: {dict(res_before)} · on {after}: {dict(res_after)}")
            run.say(f"notes: {e['notes']}")
        nc = summary.get("new_conflicts") or []
        run.say(f"new conflicts: {len(nc)}" + "".join(f"\n      {c['type']}: {', '.join(c['rule_ids'])} — "
                                                     f"{c['detail'][:100]}" for c in nc))

    # d) checks -------------------------------------------------------------------------------
    with run.step("d", "Sanity checks (reported, never fixed by hand)"):
        normalized = {r["team_rule_id"]: r for r in json.loads(config.NORMALIZED_PATH.read_text(encoding="utf-8"))["rules"]
                      if r.get("team_rule_id") and r["disposition"] == "accepted"}
        run.check("at least one new rule", bool(new_ids), ", ".join(new_ids) or "none")
        for rid in new_ids:
            rule = rules[rid]
            affected = changes[tid]["affected_address_ids"] if tid else []
            outside = [a for a in affected if (eng.facts[a]["dataset_city"] if rule["level"] == "city"
                                               else eng.facts[a]["state"]) != rule["jurisdiction"]
                       and (eng.stacks[a]["city"] if rule["level"] == "city" else eng.stacks[a]["state"]) != rule["jurisdiction"]]
            run.check(f"{rid}: every affected address is in {rule['jurisdiction']}", not outside,
                      f"{len(affected)} affected" + (f", outside: {outside[:5]}" if outside else ""))
            run.check(f"{rid}: effective_date is set", bool(rule.get("effective_date")), str(rule.get("effective_date")))
            q = normalized.get(rid, {}).get("quote_location")
            run.check(f"{rid}: literal quote verified in the source text", bool(q),
                      f"match {q['match_type']}" if q else "no verified quote")
        from extractor.smoke import run as smoke_run

        sm = smoke_run()
        bad = [c["check"] for c in sm["invariants"] + sm["behaviour"] + sm["test_rule_map"] if c["result"] != "PASS"]
        run.check("smoke-check green", not bad, ", ".join(bad) or f"{len(sm['invariants'] + sm['behaviour'] + sm['test_rule_map'])} checks")
        dash = ch.verify(changes, tl)
        bad = [f"{c['test']} {c['check']}" for c in dash if c["result"] != "PASS"]
        run.check("change tests T1-T5 dashboard green", not bad, ", ".join(bad) or f"{len(dash)}/{len(dash)} pass")

    # e) regenerate ---------------------------------------------------------------------------
    with run.step("e", "Regenerate lookups, plain language (new rules), static/; check the API"):
        from api.plain_language import build as build_plain
        from resolver.results import run as lookups_run

        lk = lookups_run(as_of)
        run.say(f"out/lookups.json: {len(lk['lookups']['lookups'])} addresses · out/changes.json: {len(changes)} tests · "
                f"out/rules.json: {len(eng.rules)} rules incl. attested")
        pl_logs: list[str] = []
        pl = build_plain(log=pl_logs.append)
        for rid in new_ids:
            p = pl["rules"].get(rid, {})
            run.say(f"plain language {rid} [{p.get('method')}]: {(p.get('en') or {}).get('what_it_means', '')[:110]}")
            run.say(f"                    ES: {(p.get('es') or {}).get('what_it_means', '')[:110]}")
        run.cost["plain language (Haiku)"] = "not metered (new rules only)"
        from api import export_static, main as api_main

        api_main.store.cache_clear()
        api_main.engine.cache_clear()
        st = export_static.export()
        run.say(f"static/: {st['files']} files, {st['bytes'] / 1e6:.1f} MB")

        # the API picks the new entry up by itself (same code the deployed service runs)
        if tid and new_ids:
            from fastapi.testclient import TestClient

            with TestClient(api_main.app) as client:
                lst = client.get("/changes").json()["summary"].get(tid, {})
                en = client.get(f"/changes/{tid}").json()
                es = client.get(f"/changes/{tid}", params={"lang": "es"}).json()
                run.say(f"GET /changes            {tid}: {lst.get('type_label')} · affected {lst.get('affected')}")
                run.say(f"GET /changes/{tid}       {en['title']}")
                run.say(f"GET /changes/{tid}?lang=es  {es['type_label']} · {es['title']}")
                run.say(f"                        {es['notes']}")
                rid = new_ids[0]
                aid = changes[tid]["affected_address_ids"][0] if changes[tid]["affected_address_ids"] else None
                after = full[tid]["test"]["as_of_after"]
                got = None
                if aid:
                    body = client.get(f"/lookup/{aid}", params={"as_of": after}).json()
                    got = next((x for g in body["results"].values() for x in g if x["team_rule_id"] == rid), None)
                    run.say(f"GET /lookup/{aid}?as_of={after}  {rid}: {got and got['result']} · "
                            f"{got and got['plain_language']['status_line']}")
            run.check(f"API lists {tid} in /changes (en, es)", bool(lst) and es.get("type_label") == "Documento nuevo (hora 16)")
            run.check(f"API /lookup shows {new_ids[0]} as applies after its effective date",
                      bool(got) and got["result"] == "applies", f"{aid} as of {after}")

    # f) report -------------------------------------------------------------------------------
    total = round(time.perf_counter() - run.t0, 1)
    ok = all(c[1] for c in run.checks)
    with run.step("f", "Report out/hour16_report.md"):
        lines = run.report + ["", "## Timings", "", "| step | seconds |", "|---|---:|"]
        lines += [f"| {k} | {v} |" for k, v in run.timings.items()] + [f"| **total** | **{total}** |", "",
                                                                       "## Cost (USD)", ""]
        lines += [f"- {k}: {v}" for k, v in run.cost.items()]
        lines += ["", f"**Result: {'ALL CHECKS PASS' if ok else 'SOME CHECKS FAILED — review before publishing'}**",
                  "", "*Not legal advice.*"]
        report = config.OUT_DIR / "hour16_report.md"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        run.say(f"{report}")

    # g) git ----------------------------------------------------------------------------------
    if git and not dry_run:
        with run.step("g", "git add + commit + push"):
            docs = ROOT / "docs" / "hour16_report.md"
            shutil.copyfile(config.OUT_DIR / "hour16_report.md", docs)
            paths = [str(p.relative_to(ROOT)) for p in sorted(config.NEW_DOCS_DIR.glob(f"{doc_id}.*"))]
            paths += ["data/compiled_exemptions.json", "data/compiled_exemptions_review.md",
                      "data/plain_language.json", "docs/hour16_report.md"]
            gitexe = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
            for cmd in (["add", *paths], ["commit", "-m", "T6: hour-16 ordinance", "-m", f"{doc_id}: {', '.join(new_ids)}"],
                        ["push", "origin", "HEAD"]):
                p = subprocess.run([gitexe, *cmd], cwd=ROOT, capture_output=True, text=True)
                run.say(f"git {cmd[0]}: {'ok' if p.returncode == 0 else 'FAILED'} {(p.stdout + p.stderr).strip()[:200]}")
    elif not dry_run:
        print(f"\n{D}(--no-git: nothing committed){X}")

    print(f"\n{B}TOTAL {total} s · {(G + 'ALL CHECKS PASS') if ok else (R + 'SOME CHECKS FAILED')}{X}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(description="Hour 16 (T6): one new document, end to end.")
    ap.add_argument("path", type=Path, help="the new document (.txt, .pdf, .html, .docx)")
    ap.add_argument("--jurisdiction", default=None, help='hint, e.g. "Cambridge, MA" (the model reads it from the text)')
    ap.add_argument("--dry-run", action="store_true", help="rehearse in a temporary copy; the repo is untouched")
    ap.add_argument("--no-git", action="store_true", help="do not commit / push")
    args = ap.parse_args()
    path = args.path.resolve()
    if not path.exists():
        raise SystemExit(f"not found: {path}")

    if args.dry_run and not os.environ.get(SANDBOX_ENV):
        t0 = time.perf_counter()
        sandbox = Path(tempfile.mkdtemp(prefix="hour16-"))
        print(f"{D}dry run: copying the repository to {sandbox} …{X}", flush=True)
        shutil.copytree(ROOT, sandbox / "repo", ignore=shutil.ignore_patterns(
            ".venv", ".git", "static", "__pycache__", ".pytest_cache"))
        env = {**os.environ, SANDBOX_ENV: "1", "PYTHONIOENCODING": "utf-8"}
        cmd = [sys.executable, str(sandbox / "repo" / "scripts" / "hour16.py"), str(path), "--dry-run"]
        if args.jurisdiction:
            cmd += ["--jurisdiction", args.jurisdiction]
        code = subprocess.run(cmd, cwd=sandbox / "repo", env=env).returncode
        kept = Path(tempfile.gettempdir()) / f"hour16_dryrun_{path.stem}{path.suffix.replace('.', '_')}.md"
        report = sandbox / "repo" / "out" / "hour16_report.md"
        if report.exists():
            shutil.copyfile(report, kept)
            print(f"{D}dry-run report kept at {kept}{X}")
        shutil.rmtree(sandbox, ignore_errors=True)
        print(f"{D}sandbox removed; repository untouched · wall clock {time.perf_counter() - t0:.1f} s{X}")
        return code
    return hour16(path, args.jurisdiction, git=not args.no_git, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
