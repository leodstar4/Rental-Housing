"""Module C: change tracking over the address results of results.py (no duplicated logic).

``diff(address, rule_ids, before, after)`` gives each rule's result at two dates ("omitted"
when the lookup drops it, with the reason; "not_in_stack" when the rule is not in the address's
jurisdiction stack). Attested rules are included (lookups_full).

``changes.json`` for the supplied tests (``dev/change_tests.json`` through
``data/test_rule_map.yaml``), always with affected_address_ids, conflict_flag_address_ids, notes:

* ``as_of``    (T1, T3): the test rule's result CHANGES between as_of_before and as_of_after.
* ``boundary`` (T2): the rule's result is applies / unknown / not_yet_effective at as_of.
* ``pending``  (T4): the rule's result is pending (addresses it would cover if enacted).
* ``negative`` (T5): addresses with an in-force rent CAP in the test's states (must be empty);
  a rule that bars local rent control (M.G.L. c. 40P) is not a cap.

conflict_flag_address_ids = affected addresses whose test-rule result carries conflict_flag (at
either date). ``out/changes_full.json`` keeps the before/after per address.

Hour 16 (``new_doc``): extract-doc of Module A, then each new rule's affected addresses at the
default query date and the day after its effective date -> entry "T6".
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import yaml

from extractor import config

from .results import Engine

CHANGES_PATH: Path = config.OUT_DIR / "changes.json"
CHANGES_FULL_PATH: Path = config.OUT_DIR / "changes_full.json"
ACTIVE = {"applies", "unknown", "not_yet_effective"}


class Timeline:
    """Lookups at several dates, computed once per (date, address)."""

    def __init__(self, **engine_kw):
        self.engine_kw = engine_kw
        self._eng: dict[date, Engine] = {}
        self._res: dict[tuple[date, str], dict] = {}

    def engine(self, d: date) -> Engine:
        if d not in self._eng:
            self._eng[d] = Engine(d, **self.engine_kw)
        return self._eng[d]

    def results(self, d: date, aid: str) -> dict[str, dict]:
        """rule_id -> {result, conflict_flag, ...} or {result: 'omitted', reason}."""
        if (d, aid) not in self._res:
            lk = self.engine(d).lookup(aid)
            out = {r["team_rule_id"]: r for r in lk["results"]}
            out.update({o["team_rule_id"]: {"result": "omitted", "reason": o["reason"], "conflict_flag": False}
                        for o in lk["omitted"]})
            self._res[(d, aid)] = out
        return self._res[(d, aid)]

    def result(self, d: date, aid: str, rid: str) -> dict:
        return self.results(d, aid).get(rid, {"result": "not_in_stack", "conflict_flag": False})

    @property
    def addresses(self) -> list[str]:
        return sorted(next(iter(self._eng.values())).facts) if self._eng else sorted(self.engine(config.DEFAULT_AS_OF).facts)


def diff(tl: Timeline, aid: str, rule_ids: list[str], before: date, after: date) -> dict[str, dict]:
    return {rid: {"before": tl.result(before, aid, rid)["result"], "after": tl.result(after, aid, rid)["result"]}
            for rid in rule_ids}


# --------------------------------------------------------------------------- #
# Supplied tests
# --------------------------------------------------------------------------- #


def load_tests() -> tuple[list[dict], dict]:
    tests = json.loads(config.CHANGE_TESTS_PATH.read_text(encoding="utf-8"))
    m = yaml.safe_load(config.TEST_RULE_MAP_PATH.read_text(encoding="utf-8"))["map"]
    return tests, {tid: e.get("ours") or e.get("attested") for tid, e in m.items()}


def _is_cap(rule: dict, eng: Engine) -> bool:
    from extractor.smoke import _bars_local_control

    internal = eng.internal.get(rule["team_rule_id"])
    return bool(rule.get("key_value")) and not (internal and _bars_local_control(internal))


def run_test(t: dict, ours: dict, tl: Timeline) -> tuple[dict, dict]:
    rids = [ours[x] for x in t["rule_ids"]]
    kind = t["type"]
    states = set(t.get("states", []))
    eng = tl.engine(date.fromisoformat(t.get("as_of_before") or t["as_of"]))
    in_states = [a for a in tl.addresses if not states or eng.facts[a]["state"] in states]
    affected, flagged, full = [], [], {}
    if kind == "as_of":
        b, a = date.fromisoformat(t["as_of_before"]), date.fromisoformat(t["as_of_after"])
        for aid in in_states:
            d = diff(tl, aid, rids, b, a)
            full[aid] = d
            if any(x["before"] != x["after"] for x in d.values()):
                affected.append(aid)
                if any(tl.result(dt, aid, r)["conflict_flag"] for r in rids for dt in (b, a)):
                    flagged.append(aid)
    else:
        d0 = date.fromisoformat(t["as_of"])
        for aid in in_states:
            res = {r: tl.result(d0, aid, r) for r in rids}
            if kind == "negative":
                caps = [r for r in tl.results(d0, aid).values() if r.get("category") == "rent_increase_limits"
                        and r.get("result") == "applies" and _is_cap(_rule(eng, r["team_rule_id"]), eng)]
                full[aid] = {"test_rules": {r: v["result"] for r, v in res.items()},
                             "rent_caps_in_force": [c["team_rule_id"] for c in caps]}
                hit = bool(caps)
            else:
                full[aid] = {r: v["result"] for r, v in res.items()}
                want = {"boundary": ACTIVE, "pending": {"pending"}}[kind]
                hit = any(v["result"] in want for v in res.values())
            if hit:
                affected.append(aid)
                if any(v["conflict_flag"] for v in res.values()):
                    flagged.append(aid)
    entry = {"affected_address_ids": affected, "conflict_flag_address_ids": flagged,
             "notes": notes(t, rids, tl, affected, flagged)}
    return entry, {"test": t, "our_rule_ids": rids, "addresses": full}


def _rule(eng: Engine, rid: str) -> dict:
    return next(r for r in eng.rules if r["team_rule_id"] == rid)


def notes(t: dict, rids: list[str], tl: Timeline, affected: list[str], flagged: list[str]) -> str:
    eng = tl.engine(date.fromisoformat(t.get("as_of_before") or t["as_of"]))
    cities = Counter(eng.facts[a]["dataset_city"] for a in affected)
    where = ", ".join(f"{c} {n}" for c, n in sorted(cities.items())) or "none"
    ids = ", ".join(rids)
    if t["type"] == "as_of":
        trans = Counter((tl.result(date.fromisoformat(t["as_of_before"]), a, rids[0])["result"],
                         tl.result(date.fromisoformat(t["as_of_after"]), a, rids[0])["result"]) for a in affected)
        tr = "; ".join(f"{b} -> {a}: {n}" for (b, a), n in trans.items())
        eff = _rule(eng, rids[0]).get("effective_date")
        s = (f"{ids} changes between {t['as_of_before']} and {t['as_of_after']} (effective {eff}) at "
             f"{len(affected)} addresses ({where}); {tr}.")
        if flagged:
            s += (f" {len(flagged)} addresses carry a conflict flag: possible preemption of the local "
                  f"algorithmic ordinances, flagged for human review.")
        return s
    if t["type"] == "boundary":
        return (f"{ids} apply only inside their own city limits as of {t['as_of']} ({where}); none elsewhere. "
                f"Local ordinance text not in corpus; scope from organizer brief (manifest-attested rules). "
                f"All {len(flagged)} carry a conflict flag: the NJ FAIR Act may preempt them once effective.")
    if t["type"] == "pending":
        return (f"{ids} are pending bills, not law, as of {t['as_of']}; if enacted they would cover "
                f"{len(affected)} Massachusetts addresses ({where}). Bill text not in corpus: scope stated "
                f"statewide from the bill status pages.")
    rule = _rule(eng, rids[0])
    return (f"No rent cap in force in Massachusetts as of {t['as_of']}: affected set is empty "
            f"({len(affected)}). The rent-control ballot question ({rids[0]}, IP 25-21) is recorded as "
            f"{rule['status']} (struck 2026-06-23); M.G.L. c. 40P bars local rent control and is not a cap.")


def run_all_tests(tl: Timeline | None = None) -> tuple[dict, dict, Timeline]:
    """T1-T5 from dev/change_tests.json, then one entry (T6, T7, ...) per hour-16 document kept
    in corpus/new/ — so `changes` (and the Render build) always reports them."""
    from extractor.incremental import increments

    tl = tl or Timeline()
    tests, ours = load_tests()
    changes, full = {}, {}
    for t in tests:
        changes[t["test_id"]], full[t["test_id"]] = run_test(t, ours, tl)
    n = 6
    for inc in increments():
        if inc["meta"].get("new_rule_ids"):
            tid = f"T{n}"
            changes[tid], full[tid] = doc_test(tid, inc["meta"], tl)
            n += 1
    return changes, full, tl


def write(changes: dict, full: dict | None = None) -> None:
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    CHANGES_PATH.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    if full is not None:
        CHANGES_FULL_PATH.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- #
# Verification dashboard
# --------------------------------------------------------------------------- #


def verify(changes: dict, tl: Timeline) -> list[dict]:
    eng = tl.engine(config.DEFAULT_AS_OF)
    city = {a: eng.facts[a]["dataset_city"] for a in eng.facts}
    by_state = Counter(eng.facts[a]["state"] for a in eng.facts)
    ids_of = lambda c: {a for a, x in city.items() if x == c}  # noqa: E731
    checks = []

    def add(test, what, expected, got):
        checks.append({"test": test, "check": what, "expected": expected, "got": got,
                       "result": "PASS" if expected == got else "FAIL"})

    t1 = changes["T1"]
    add("T1", "CA addresses affected", by_state["CA"], len(t1["affected_address_ids"]))
    d1 = [(tl.result(date(2025, 12, 31), a, "CA-ALG-01")["result"], tl.result(date(2026, 1, 2), a, "CA-ALG-01")["result"])
          for a in t1["affected_address_ids"]]
    add("T1", "not_yet_effective -> applies", len(d1), sum(x == ("not_yet_effective", "applies") for x in d1))
    hob = {a for a in changes["T2"]["affected_address_ids"]
           if tl.result(date(2026, 10, 1), a, "HOB-ALG-A1")["result"] in ACTIVE}
    jc = {a for a in changes["T2"]["affected_address_ids"]
          if tl.result(date(2026, 10, 1), a, "JC-ALG-A1")["result"] in ACTIVE}
    add("T2", "Hoboken ban = Hoboken addresses", len(ids_of("Hoboken, NJ")), len(hob & ids_of("Hoboken, NJ")))
    add("T2", "Hoboken ban outside Hoboken", 0, len(hob - ids_of("Hoboken, NJ")))
    add("T2", "Jersey City ban = Jersey City addresses", len(ids_of("Jersey City, NJ")),
        len(jc & ids_of("Jersey City, NJ")))
    add("T2", "Jersey City ban outside Jersey City", 0, len(jc - ids_of("Jersey City, NJ")))
    add("T2", "Newark addresses affected", 0, len(set(changes["T2"]["affected_address_ids"]) & ids_of("Newark, NJ")))
    add("T3", "NJ addresses affected", by_state["NJ"], len(changes["T3"]["affected_address_ids"]))
    add("T3", "conflict flags = Hoboken + Jersey City", len(ids_of("Hoboken, NJ") | ids_of("Jersey City, NJ")),
        len(set(changes["T3"]["conflict_flag_address_ids"]) & (ids_of("Hoboken, NJ") | ids_of("Jersey City, NJ"))))
    add("T3", "conflict flags outside Hoboken/JC", 0,
        len(set(changes["T3"]["conflict_flag_address_ids"]) - ids_of("Hoboken, NJ") - ids_of("Jersey City, NJ")))
    add("T4", "MA addresses pending", by_state["MA"], len(changes["T4"]["affected_address_ids"]))
    add("T4", "MA addresses with applies", 0, sum(tl.result(date(2026, 10, 1), a, r)["result"] == "applies"
                                                    for a in eng.facts if eng.facts[a]["state"] == "MA"
                                                    for r in ("MA-ALG-P1", "MA-ALG-P2")))
    add("T5", "affected set", 0, len(changes["T5"]["affected_address_ids"]))
    add("T5", "IP 25-21 status", "failed", _rule(eng, "MA-RENT-A1")["status"])
    return checks


def render(checks: list[dict], seconds: float) -> str:
    w = 92
    lines = ["=" * w, " MODULE C · CHANGE TESTS T1-T5 (as recorded in out/changes.json)".ljust(w), "=" * w]
    for c in checks:
        lines.append(f"  [{c['result']}] {c['test']}  {c['check']:<42} expected {str(c['expected']):>7}   "
                     f"got {str(c['got']):>7}")
    n = sum(c["result"] == "FAIL" for c in checks)
    lines += ["", f"  RESULT: {'ALL CHECKS PASS' if not n else f'{n} CHECK(S) FAILED'}   ({seconds:.1f} s)", "=" * w]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Hour 16: a new document
# --------------------------------------------------------------------------- #


def doc_test(tid: str, meta: dict, tl: Timeline) -> tuple[dict, dict]:
    """Entry for an hour-16 document: each new rule's result at the default query date and the day
    after its effective date; affected = addresses where it applies / is unknown / not yet
    effective / pending on the later date."""
    eng = tl.engine(config.DEFAULT_AS_OF)
    rids = meta["new_rule_ids"]
    rules = {r["team_rule_id"]: r for r in eng.rules}
    after = max([date.fromisoformat(rules[r]["effective_date"][:10]) + timedelta(days=1)
                 for r in rids if rules.get(r, {}).get("effective_date")] or [config.DEFAULT_AS_OF])
    before = config.DEFAULT_AS_OF
    addresses, affected, flagged = {}, [], []
    for aid in tl.addresses:
        d = diff(tl, aid, rids, before, after)
        if any(x["before"] != "not_in_stack" or x["after"] != "not_in_stack" for x in d.values()):
            addresses[aid] = d
        if any(x["after"] in ACTIVE | {"pending"} for x in d.values()):
            affected.append(aid)
            if any(tl.result(after, aid, r)["conflict_flag"] for r in rids):
                flagged.append(aid)
    cities = Counter(eng.facts[a]["dataset_city"] for a in affected)
    where = ", ".join(f"{c} {n}" for c, n in sorted(cities.items())) or "none"
    parts = []
    for rid in rids:
        r = rules.get(rid, {})
        parts.append(f"New rule {rid} ({r.get('jurisdiction')}, {r.get('category')}) from {meta['doc_id']}: "
                     f"{r.get('status')} on {before}, effective {r.get('effective_date')}")
    notes = "; ".join(parts) + f". From {after} it covers {len(affected)} addresses ({where})."
    test = {"test_id": tid, "type": "new_document", "title": f"New document {meta['original_file']}: {', '.join(rids)}",
            "doc_id": meta["doc_id"], "original_file": meta["original_file"], "original_sha256": meta["original_sha256"],
            "retrieved_at": meta["retrieved_at"], "rule_ids": rids, "as_of_before": before.isoformat(),
            "as_of_after": after.isoformat()}
    return ({"affected_address_ids": affected, "conflict_flag_address_ids": flagged, "notes": notes},
            {"test": test, "our_rule_ids": rids, "addresses": addresses})


def new_doc(path: Path, jurisdiction: str | None, *, log=print) -> dict:
    """Hour 16, KEPT: extract-doc (Module A) -> persist the increment in corpus/new/ -> compile the
    coverage of the new rules into data/compiled_exemptions.json -> change tests with the T6 entry."""
    from extractor import incremental
    from extractor.cli import DEFAULT_SNAPSHOT
    from extractor.snapshot import activate

    from .compile_exemptions import compile_all

    t0 = time.perf_counter()
    timings = {}
    summary = incremental.run_increment(path, jurisdiction=jurisdiction, snapshot_dir=DEFAULT_SNAPSHOT,
                                        as_of=config.DEFAULT_AS_OF)
    timings["extract + validate + normalize (Module A)"] = round(time.perf_counter() - t0, 1)
    activate(DEFAULT_SNAPSHOT, offline=False)  # back to the frozen run for everything else
    meta = incremental.persist_increment(summary)
    from extractor.cli import attest
    attest()
    t = time.perf_counter()
    compiled = compile_all(log=log)
    timings["compile coverage"] = round(time.perf_counter() - t, 1)
    t = time.perf_counter()
    changes, full, tl = run_all_tests()
    write(changes, full)
    timings["change tests (T1-T6)"] = round(time.perf_counter() - t, 1)
    tid = next((k for k, v in full.items() if (v.get("test") or {}).get("doc_id") == meta["doc_id"]), None)
    return {"doc_id": meta["doc_id"], "meta": meta, "increment": summary, "test_id": tid,
            "entry": changes.get(tid), "full": full.get(tid), "compiled": {r: compiled["rules"].get(r)
                                                                       for r in meta["new_rule_ids"]},
            "timeline": tl, "timings_s": timings, "total_s": round(time.perf_counter() - t0, 1)}
