"""Three-valued (Kleene) coverage of each rule at each address (``out/coverage.json``).

For an address and a rule of its jurisdiction stack (state rule -> same state; city rule ->
same city; anything else is not evaluated), with the compiled predicates of
``data/compiled_exemptions.json`` (scope ``building`` only):

    conditions = AND(all conditions)      exemption = OR(all exemptions)
    conditions F             -> not_covered
    exemption T              -> exempt
    conditions T, exemption F -> covered
    otherwise                -> unknown   (missing_facts lists what made it U)

Facts (``data/building_facts.json``) are compared as intervals: units [min, max];
``co_date`` = [Jan 1, Dec 31] of year_built (the certificate date is not in the data, so a
cutoff inside the building's year is unknown); ``building_age`` at ``as_of`` from that same
interval (a rolling cutoff falling in the building's year is unknown). owner_type and
owner_occupied are always unknown; another term can still decide (Kleene: F AND U = F).

Special-status items (``special_status`` in the compiled rules: affordability restriction, HUD
subsidy, nonprofit co-op, single-sex, conversion, institutional use, government / university
owner) are presumed absent unless a use flag shows them (``PRESUME_SPECIAL_STATUS``, default
true): their unknown use-flag, status-owner and ``missing`` leaves become F, with a
"presumed: no evidence of <status> in assessor data" note. Generic owner type, owner
occupancy, cutoff-year and missing units / year_built stay unknown.

``confidence_coverage`` = 1.0, x0.9 if a unit range (not an exact count) or a dataset-fallback
city was used, x0.8 if a certificate-of-occupancy / building-age test used year_built as proxy,
x0.9 if the result rests on a special-status presumption.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date
from enum import Enum
from pathlib import Path

from extractor import config

from .predicates import render

COVERAGE_PATH: Path = config.OUT_DIR / "coverage.json"


class Tri(str, Enum):
    T = "T"
    F = "F"
    U = "U"

    def __and__(self, o: Tri) -> Tri:
        return Tri.F if Tri.F in (self, o) else Tri.T if (self, o) == (Tri.T, Tri.T) else Tri.U

    def __or__(self, o: Tri) -> Tri:
        return Tri.T if Tri.T in (self, o) else Tri.F if (self, o) == (Tri.F, Tri.F) else Tri.U

    def __invert__(self) -> Tri:
        return {Tri.T: Tri.F, Tri.F: Tri.T, Tri.U: Tri.U}[self]


def all_(xs) -> Tri:
    out = Tri.T
    for x in xs:
        out = out & x
    return out


def any_(xs) -> Tri:
    out = Tri.F
    for x in xs:
        out = out | x
    return out


def tri(b: bool) -> Tri:
    return Tri.T if b else Tri.F


def cmp_interval(lo, hi, op: str, v) -> Tri:
    """Compare an unknown value known to lie in [lo, hi] (hi None = unbounded) with ``v``."""
    if op == "in":
        return any_(cmp_interval(lo, hi, "==", x) for x in v)
    if op == "!=":
        return ~cmp_interval(lo, hi, "==", v)
    above = hi is not None
    if op == "<=":
        return Tri.T if above and hi <= v else Tri.F if lo > v else Tri.U
    if op == "<":
        return Tri.T if above and hi < v else Tri.F if lo >= v else Tri.U
    if op == ">=":
        return Tri.T if lo >= v else Tri.F if above and hi < v else Tri.U
    if op == ">":
        return Tri.T if lo > v else Tri.F if above and hi <= v else Tri.U
    if op == "==":
        return Tri.T if lo == hi == v else Tri.F if v < lo or (above and v > hi) else Tri.U
    raise ValueError(op)


def _years_between(d: date, as_of: date) -> int:
    return as_of.year - d.year - ((as_of.month, as_of.day) < (d.month, d.day))


#: Special-status exemptions/conditions (compile_exemptions.SPECIAL_STATUS: affordability
#: restriction, HUD subsidy, nonprofit co-op, single-sex, conversion, institutional use...) are
#: presumed absent unless a use flag in the data shows them. Set PRESUME_SPECIAL_STATUS=false to
#: leave them unknown.
PRESUME_SPECIAL_STATUS = os.getenv("PRESUME_SPECIAL_STATUS", "true").strip().lower() not in ("0", "false", "no")
_FLAG_LABEL = {"use.affordable": "an affordability restriction", "use.section8": "a Section 8 / HUD subsidy",
               "use.coop": "cooperative ownership", "use.elderly": "elderly / age-restricted housing",
               "use.condo": "condominium ownership", "use.single_family": "single-family use"}


class Context:
    """Fact access for one address; records which facts were used and which were missing."""

    def __init__(self, facts: dict, stack: dict, as_of: date, presume: bool | None = None):
        self.f, self.stack, self.as_of = facts, stack, as_of
        self.proxies: set[str] = set()  # units_range, co_approx
        self.presume = PRESUME_SPECIAL_STATUS if presume is None else presume
        self.special = False  # evaluating a special-status item
        self.presumed: list[str] = []

    def _presume(self, info: dict, label: str) -> tuple[Tri, dict]:
        note = f"presumed: no evidence of {label} in assessor data"
        if note not in self.presumed:
            self.presumed.append(note)
        info = {k: v for k, v in info.items() if k != "missing"}
        return Tri.F, {**info, "presumed": note}

    def leaf(self, p: dict) -> tuple[Tri, dict]:
        """Evaluate one comparison: (result, {fact, value_used, source, missing?})."""
        fact, op, v = p["fact"], p["op"], p["value"]
        info = {"fact": fact}
        if fact == "units":
            u = self.f["units"]
            if u["range"] is None:
                return Tri.U, {**info, "value_used": None, "source": None, "missing": "units"}
            lo, hi = u["range"]
            if u["certainty"] == "range":
                self.proxies.add("units_range")
            return cmp_interval(lo, hi, op, v), {**info, "value_used": u["range"], "source": u["source"]}
        if fact in ("year_built", "co_date", "building_age"):
            y = self.f["year_built"]["value"]
            if y is None:
                return Tri.U, {**info, "value_used": None, "source": None, "missing": "year_built"}
            if fact == "year_built":
                return cmp_interval(y, y, op, v), {**info, "value_used": y, "source": "year_built column"}
            self.proxies.add("co_approx")
            first, last = date(y, 1, 1), date(y, 12, 31)
            src = f"year_built {y} as certificate-of-occupancy proxy"
            if fact == "co_date":
                vv = [date.fromisoformat(x) for x in v] if op == "in" else date.fromisoformat(v)
                r = cmp_interval(first, last, op, vv)
                return r, {**info, "value_used": f"{first}..{last}", "source": src,
                           **({"missing": "certificate of occupancy date (built in cutoff year)"} if r == Tri.U else {})}
            lo, hi = _years_between(last, self.as_of), _years_between(first, self.as_of)
            r = cmp_interval(lo, hi, op, v)
            return r, {**info, "value_used": [lo, hi], "source": f"{src}, as of {self.as_of}",
                       **({"missing": "certificate of occupancy date (rolling cutoff in building year)"}
                          if r == Tri.U else {})}
        if fact.startswith("use."):
            flag = self.f["use_flags"].get(fact[4:], {"value": None, "basis": "not in facts"})
            if flag["value"] is None:
                out = {**info, "value_used": None, "source": flag.get("basis"), "missing": fact}
                if self.special and self.presume and op == "==" and v is True:
                    return self._presume(out, _FLAG_LABEL.get(fact, fact))
                return Tri.U, out
            return _eq(flag["value"], op, v), {**info, "value_used": flag["value"], "source": flag["basis"]}
        if fact == "use_class":
            uc = self.f["use_class"]
            return _eq(uc["value"], op, v), {**info, "value_used": uc["value"], "source": uc["basis"]}
        if fact in ("owner_type", "owner_occupied"):
            out = {**info, "value_used": None, "source": "no owner data in the sample", "missing": fact}
            if fact == "owner_type" and self.special and self.presume and op in ("==", "in"):
                return self._presume(out, f"owner type {v if isinstance(v, str) else ' / '.join(v)}")
            return Tri.U, out
        raise ValueError(f"unknown fact {fact!r}")

    def eval(self, p: dict, leaves: list[dict]) -> Tri:
        if "and" in p:
            return all_([self.eval(a, leaves) for a in p["and"]])
        if "or" in p:
            return any_([self.eval(a, leaves) for a in p["or"]])
        if "not" in p:
            return ~self.eval(p["not"], leaves)
        if "const" in p:
            return tri(p["const"])
        if "missing" in p:
            if self.special and self.presume:
                _, info = self._presume({"fact": None, "value_used": None, "source": None}, p["missing"])
                leaves.append({**info, "result": "F"})
                return Tri.F
            leaves.append({"fact": None, "value_used": None, "source": None, "missing": p["missing"], "result": "U"})
            return Tri.U
        r, info = self.leaf(p)
        leaves.append({**info, "result": r.value})
        return r


def _eq(actual, op: str, v) -> Tri:
    if op == "==":
        return tri(actual == v)
    if op == "!=":
        return tri(actual != v)
    if op == "in":
        return tri(actual in v)
    raise ValueError(f"op {op} on a categorical fact")


def jurisdiction_match(rule: dict, stack: dict) -> bool:
    if rule["level"] == "state":
        return rule["jurisdiction"] == stack["state"]
    return stack["city"] is not None and rule["jurisdiction"] == stack["city"]


def evaluate(rule: dict, compiled: dict, facts: dict, stack: dict, as_of: date,
             presume: bool | None = None) -> dict | None:
    """Coverage of one rule at one address, or None if the rule is not in the address's stack."""
    if not jurisdiction_match(rule, stack):
        return None
    ctx = Context(facts, stack, as_of, presume)
    reasons, missing = [], []

    def run(items: list[dict], kind: str) -> Tri:
        results = []
        for it in items:
            leaves: list[dict] = []
            ctx.special = bool(it.get("special_status"))
            r = ctx.eval(it["predicate"], leaves)
            ctx.special = False
            results.append(r)
            presumed = [lf["presumed"] for lf in leaves if lf.get("presumed")]
            reasons.append({"kind": kind, "condition": it["text"], "predicate": render(it["predicate"]),
                            "value_used": {lf["fact"]: lf["value_used"] for lf in leaves if lf["fact"]},
                            "fact_source": {lf["fact"]: lf["source"] for lf in leaves if lf["fact"]},
                            "result": r.value, **({"presumed": presumed} if presumed else {}),
                            "_missing": [lf["missing"] for lf in leaves if lf.get("missing") and lf["result"] == "U"]})
        return (all_ if kind == "condition" else any_)(results)

    cond = run([c for c in compiled["conditions"] if c["scope"] == "building"], "condition")
    exem = run([e for e in compiled["exemptions"] if e["scope"] == "building"], "exemption")
    if cond == Tri.F:
        coverage = "not_covered"
    elif exem == Tri.T:
        coverage = "exempt"
    elif cond == Tri.T and exem == Tri.F:
        coverage = "covered"
    else:
        coverage = "unknown"
    if coverage == "unknown":
        for rs in reasons:
            if rs["result"] == "U" and (rs["kind"] == "condition" and cond == Tri.U
                                        or rs["kind"] == "exemption" and exem == Tri.U):
                for m in rs["_missing"]:
                    if m not in missing:
                        missing.append(m)
    for rs in reasons:
        rs.pop("_missing")

    conf, factors = 1.0, []
    if "units_range" in ctx.proxies or stack.get("source") == "dataset_fallback":
        conf *= 0.9
        factors.append({"factor": 0.9, "reason": "units_range" if "units_range" in ctx.proxies else "dataset_fallback"})
    if "co_approx" in ctx.proxies:
        conf *= 0.8
        factors.append({"factor": 0.8, "reason": "co_approx"})
    # a presumption counts only if it was decisive (covered / not_covered resting on it)
    presumptions = ctx.presumed if coverage in ("covered", "not_covered") else []
    if presumptions:
        conf *= 0.9
        factors.append({"factor": 0.9, "reason": "special_status_presumption"})
    return {
        "rule_id": rule["team_rule_id"], "coverage": coverage, "conditions": cond.value, "exemption": exem.value,
        "missing_facts": missing, "presumptions": presumptions, "reasons": reasons,
        "confidence_coverage": round(conf, 3), "confidence_factors": factors,
        "caveats": [e["text"] for e in compiled["exemptions"] + compiled["conditions"] if e["scope"] == "unit_or_tenancy"],
        "deferred_other_law": [e["text"] for e in compiled["exemptions"] + compiled["conditions"]
                               if e["scope"] == "other_law"],
        "jurisdiction_source": stack.get("source"),
    }


# --------------------------------------------------------------------------- #
# Full run
# --------------------------------------------------------------------------- #


def load_inputs() -> tuple[list[dict], dict, dict, dict]:
    from .compile_exemptions import COMPILED_PATH, load_rules
    from .facts import FACTS_PATH
    from .geocode import JURISDICTIONS_PATH

    rules = load_rules()
    compiled = json.loads(COMPILED_PATH.read_text(encoding="utf-8"))["rules"]
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))["facts"]
    stacks = json.loads(JURISDICTIONS_PATH.read_text(encoding="utf-8"))["stacks"]
    return rules, compiled, facts, stacks


def run_all(as_of: date) -> dict:
    rules, compiled, facts, stacks = load_inputs()
    results = {}
    for aid in sorted(facts):
        out = []
        for rule in rules:
            r = evaluate(rule, compiled[rule["team_rule_id"]], facts[aid], stacks[aid], as_of)
            if r:
                out.append(r)
        results[aid] = out
    data = {"as_of": as_of.isoformat(), "results": results}
    COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return data


def summarize(data: dict, facts: dict) -> dict:
    """Per city: coverage counts, unknown count, and missing-fact shares of the unknowns."""
    by_city: dict[str, Counter] = {}
    miss_city: dict[str, Counter] = {}
    top: Counter = Counter()
    for aid, rs in data["results"].items():
        city = facts[aid]["dataset_city"]
        c = by_city.setdefault(city, Counter())
        m = miss_city.setdefault(city, Counter())
        for r in rs:
            c[r["coverage"]] += 1
            if r["coverage"] == "unknown":
                for f in set(r["missing_facts"]):
                    m[f] += 1
                    top[f] += 1
    return {"by_city": by_city, "missing_by_city": miss_city, "top_missing": top}
