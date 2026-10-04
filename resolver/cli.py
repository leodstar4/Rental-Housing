"""Command line: ``python -m resolver.cli <command>``."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help="Module B: building facts and jurisdiction resolution.")


@app.callback()
def _main() -> None:
    """Module B: building facts and jurisdiction resolution."""


def _pct(k: int, n: int) -> str:
    return f"{k:3d} ({100 * k / n:3.0f}%)"


@app.command("facts")
def facts() -> None:
    """Building facts for every sample address -> data/building_facts.json."""
    from .facts import FACTS_PATH, summary, write_facts

    data = write_facts()
    typer.echo(f"{len(data['facts'])} addresses -> {FACTS_PATH}\n")
    typer.echo(f"{'city':20} {'n':>3}  {'units exact':>11} {'parsed':>11} {'range':>11} {'unknown':>11}  "
               f"{'year_built':>11}  use_flags")
    for r in summary(data):
        n = r["n"]
        typer.echo(f"{r['city']:20} {n:3d}  {_pct(r['exact'], n):>11} {_pct(r['parsed'], n):>11} "
                   f"{_pct(r['range'], n):>11} {_pct(r['unknown'], n):>11}  {_pct(r['year_built'], n):>11}  {r['flags']}")
    typer.echo(f"\nwarnings ({len(data['warnings'])}): {dict(Counter(w['code'] for w in data['warnings']))}")
    for w in data["warnings"]:
        typer.echo(f"  {w['address_id']} [{w['code']}] {w['message']}")


@app.command("geocode")
def geocode(refresh: bool = typer.Option(False, help="Query the Census Geocoder again instead of data/geocode_raw/.")) -> None:
    """Jurisdiction stack for every sample address -> data/jurisdictions.json."""
    from .geocode import JURISDICTIONS_PATH, match_summary, resolve

    data = resolve(refresh=refresh, log=typer.echo)
    typer.echo(f"\n{len(data['stacks'])} stacks -> {JURISDICTIONS_PATH}\n")
    typer.echo(f"{'city (dataset)':20} {'n':>3}  {'exact':>10} {'non_exact':>10} {'no_match':>10}")
    tot: Counter = Counter()
    for city, n, c in match_summary(data):
        tot.update(c)
        typer.echo(f"{city:20} {n:3d}  {_pct(c['exact'], n):>10} {_pct(c['non_exact'], n):>10} {_pct(c['no_match'], n):>10}")
    n = sum(tot.values())
    typer.echo(f"{'TOTAL':20} {n:3d}  {_pct(tot['exact'], n):>10} {_pct(tot['non_exact'], n):>10} {_pct(tot['no_match'], n):>10}")
    typer.echo(f"\ndiscrepancies ({len(data['discrepancies'])}):")
    for d in data["discrepancies"]:
        typer.echo("  " + json.dumps(d, ensure_ascii=False))


@app.command("compile")
def compile_cmd(refresh: bool = typer.Option(False, help="Ignore data/compiled_exemptions.json and .cache/compile.")) -> None:
    """Coverage conditions + exemptions -> predicates (data/compiled_exemptions.json + review table)."""
    from extractor import config

    from .compile_exemptions import COMPILED_PATH, compile_all
    from .predicates import render

    data = compile_all(refresh=refresh, log=typer.echo)
    review = config.DATA_DIR / "compiled_exemptions_review.md"
    lines = ["# Compiled coverage conditions and exemptions (review)", "",
             f"Model `{data['model']}`, prompt `{data['prompt_version']}`. Conditions are ANDed (rule covers the "
             "building), exemptions ORed (rule does not apply). Scope `building` is evaluated; "
             "`unit_or_tenancy` is a caveat; `other_law` is deferred to precedence (B3).", "",
             "| rule | kind | scope | origin | original text | predicate | irreducible |", "|---|---|---|---|---|---|---|"]
    counts: Counter = Counter()
    for rid, c in data["rules"].items():
        for e in c["conditions"] + c["exemptions"]:
            counts[(e["kind"], e["scope"], e.get("irreducible", False))] += 1
            txt = (e["text"] or "").replace("|", "/").replace("\n", " ")
            lines.append(f"| {rid} | {e['kind']} | {e['scope']} | {e['origin']} | {txt} | "
                         f"`{render(e['predicate']).replace('|', '/')}` | {'**yes**' if e.get('irreducible') else ''} |")
    review.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    typer.echo(f"{len(data['rules'])} rules -> {COMPILED_PATH}; review table -> {review}")
    for (kind, scope, irr), n in sorted(counts.items()):
        typer.echo(f"  {kind:10} {scope:16} {'irreducible' if irr else '':12} {n}")


@app.command("coverage")
def coverage_cmd(as_of: str = typer.Option("2026-10-01", help="Query date (ISO).")) -> None:
    """Kleene coverage of every rule at every address -> out/coverage.json (coverage only; no status)."""
    from datetime import date

    from .coverage import COVERAGE_PATH, load_inputs, run_all, summarize

    data = run_all(date.fromisoformat(as_of))
    facts = load_inputs()[2]
    s = summarize(data, facts)
    n = sum(len(v) for v in data["results"].values())
    typer.echo(f"{n} (address, rule) pairs as of {as_of} -> {COVERAGE_PATH}\n")
    cols = ("covered", "unknown", "not_covered", "exempt")
    typer.echo(f"{'city':20} {'pairs':>5}  " + "  ".join(f"{c:>13}" for c in cols))
    for city in sorted(s["by_city"], key=lambda c: (c[-2:], c)):
        c = s["by_city"][city]
        t = sum(c.values())
        typer.echo(f"{city:20} {t:5d}  " + "  ".join(f"{_pct(c[k], t):>13}" for k in cols))
    typer.echo("\n10 most frequent missing facts (unknown pairs they appear in):")
    for f, k in s["top_missing"].most_common(10):
        typer.echo(f"  {k:5d}  {f}")
    typer.echo("\nfacts behind more than 30% of a city's unknowns:")
    for city in sorted(s["missing_by_city"], key=lambda c: (c[-2:], c)):
        unk = s["by_city"][city]["unknown"]
        for f, k in s["missing_by_city"][city].most_common():
            if unk and k / unk > 0.30:
                typer.echo(f"  {city:20} {f:45} {k:4d}/{unk} ({100 * k / unk:.0f}%)")


def render_address(d: dict, facts: dict, as_of: str) -> str:
    from .results import CATEGORY_LABEL

    j, f = d["jurisdiction"], facts
    u = f["units"]
    units = ("unknown" if not u["range"] else f"{u['range'][0]}" if u["range"][0] == u["range"][1]
             else f"{u['range'][0]}+" if u["range"][1] is None else f"{u['range'][0]}-{u['range'][1]}")
    lines = [f"{d['address_id']}  ·  {j['city'] or '(no city)'} / {j['state']}  ·  geocode {j['match_quality']} "
             f"({j['source']})  ·  built {f['year_built']['value'] or 'unknown'}  ·  units {units} "
             f"({u['certainty']})  ·  as of {as_of}", "Not legal advice."]
    by: dict[str, list] = {}
    for r in d["results"]:
        by.setdefault(r["category"], []).append(r)
    for cat, label in CATEGORY_LABEL.items():
        if cat not in by:
            continue
        lines.append(f"\n  {label}")
        for r in by[cat]:
            extra = (f" by {r['superseded_by']}" if r["superseded_by"] else "") + (
                f" (eff. {r['effective_date']})" if r["result"] == "not_yet_effective" else "") + (
                "  [attested, lookups_full only]" if r["attested"] else "")
            flag = "  ⚑" if r["conflict_flag"] else ""
            lines.append(f"    {r['team_rule_id']:12} {r['result']:17}{extra}{flag}   conf {r['confidence']:.2f}")
            lines.append(f"      {r['explanation'].split(' Source:')[0][:300]}")
    return "\n".join(lines)


@app.command("lookup")
def lookup_cmd(as_of: str = typer.Option("2026-10-01", help="Query date (ISO)."),
               address: list[str] = typer.Option(None, help="Address id(s) to print (repeatable).")) -> None:
    """Results for all 500 addresses -> out/lookups.json + out/lookups_full.json; prints a summary."""
    from datetime import date

    from .results import FULL_PATH, LOOKUPS_PATH, run

    out = run(date.fromisoformat(as_of))
    full, eng = out["full"], out["engine"]
    if address:
        for a in address:
            typer.echo(render_address(full[a], eng.facts[a], as_of) + "\n")
        return
    typer.echo(f"500 addresses -> {LOOKUPS_PATH} (rules.json only) and {FULL_PATH} (+ attested, details)\n")
    cols = ("applies", "unknown", "superseded", "not_yet_effective", "pending")
    typer.echo(f"{'city':20} {'results':>7}  " + "  ".join(f"{c:>17}" for c in cols) + "  flagged addr")
    by: dict[str, Counter] = {}
    flagged: dict[str, set] = {}
    for aid, d in full.items():
        city = eng.facts[aid]["dataset_city"]
        c = by.setdefault(city, Counter())
        for r in d["results"]:
            if not r["attested"]:
                c[r["result"]] += 1
                if r["conflict_flag"]:
                    flagged.setdefault(city, set()).add(aid)
    for city in sorted(by, key=lambda c: (c[-2:], c)):
        c, t = by[city], sum(by[city].values())
        typer.echo(f"{city:20} {t:7d}  " + "  ".join(f"{_pct(c[k], t):>17}" for k in cols)
                   + f"  {len(flagged.get(city, ())):5d}")
    per_rule, review = Counter(), Counter()
    for d in full.values():
        for r in d["results"]:
            if r["conflict_flag"]:
                per_rule[r["team_rule_id"] + (" (attested)" if r["attested"] else "")] += 1
            if r["needs_review"] and not r["attested"]:
                review[r["team_rule_id"]] += 1
    typer.echo(f"\naddresses with at least one conflict_flag: {len(set().union(*flagged.values()))} / 500")
    typer.echo(f"results with conflict_flag (legal conflict only): {sum(per_rule.values())}")
    for rid, n in sorted(per_rule.items()):
        typer.echo(f"  {rid:24} {n:4d}")
    typer.echo(f"results with needs_review (combined confidence < 0.5, lookups_full only): {sum(review.values())} "
               f"in {len(review)} rules")


@app.command("changes")
def changes_cmd(new_doc: Path = typer.Option(None, exists=True, dir_okay=False,
                                             help="Hour 16: a new document (.txt/.pdf/.html) -> entry T6."),
                jurisdiction: str = typer.Option(None, help='Jurisdiction hint for --new-doc, e.g. "Cambridge, MA".')) -> None:
    """Change tests T1-T5 -> out/changes.json + out/changes_full.json and a dashboard; or T6 for --new-doc."""
    import time

    from . import changes as ch

    if new_doc:
        out = ch.new_doc(new_doc, jurisdiction, log=typer.echo)
        typer.echo(f"\nT6 · {out['doc_id']} · new rules: {', '.join(out['new_rule_ids']) or 'none'}")
        for rid, v in out["rules"].items():
            typer.echo(f"  {rid}: {v['status_now']} on {config_default()}, effective {v['effective_date']}")
            for d, x in v["by_date"].items():
                typer.echo(f"    as of {d}: {len(x['affected_address_ids'])} affected {x['by_city']} results {x['results']}")
        typer.echo(f"  notes: {out['entry']['notes']}")
        typer.echo(f"  timings: {out['timings_s']}  total {out['total_s']} s  -> {ch.CHANGES_PATH} (T6)")
        return
    t0 = time.perf_counter()
    changes, full, tl = ch.run_all_tests()
    ch.write(changes, full)
    typer.echo(f"-> {ch.CHANGES_PATH}, {ch.CHANGES_FULL_PATH}\n")
    for tid, e in changes.items():
        typer.echo(f"{tid}: affected {len(e['affected_address_ids'])}, conflict-flagged "
                   f"{len(e['conflict_flag_address_ids'])}\n    {e['notes']}")
    typer.echo("\n" + ch.render(ch.verify(changes, tl), time.perf_counter() - t0))


def config_default() -> str:
    from extractor import config

    return config.DEFAULT_AS_OF.isoformat()


if __name__ == "__main__":
    app()
