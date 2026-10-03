"""Command line: ``python -m resolver.cli <command>``."""

from __future__ import annotations

import json
from collections import Counter

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


if __name__ == "__main__":
    app()
