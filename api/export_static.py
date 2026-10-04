"""Static backup of the API (``python -m api.export_static``) -> static/.

Same builders as api/main.py, written as files a front end can fetch when the backend sleeps:

    static/index.json                 addresses + file map + as_of + disclaimer
    static/lookup/<id>.en.json        GET /lookup/<id>?as_of=2026-10-01&lang=en
    static/lookup/<id>.es.json        ... lang=es
    static/rules.<lang>.json          GET /rules
    static/changes.json, static/changes/<test_id>.json, static/conflicts.json, static/audit.json
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from extractor import config

from . import main as api

STATIC_DIR: Path = config.ROOT / "static"


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")


def export(out: Path = STATIC_DIR, as_of=None) -> dict:
    t0 = time.perf_counter()
    as_of = as_of or config.DEFAULT_AS_OF
    if out.exists():
        shutil.rmtree(out)
    s = api.store()
    ids = sorted(s.facts)
    for aid in ids:
        for lang in ("en", "es"):
            _write(out / "lookup" / f"{aid}.{lang}.json", api.lookup_payload(aid, as_of, lang))
    for lang in ("en", "es"):
        _write(out / f"rules.{lang}.json", api.rules_payload(as_of, lang))
    _write(out / "changes.json", api.changes_payload("en"))
    for tid in s.changes:
        _write(out / "changes" / f"{tid}.json", api.change_detail(tid))
    _write(out / "conflicts.json", api.conflicts())
    _write(out / "audit.json", api.audit())
    _write(out / "index.json", {
        "as_of": as_of.isoformat(), "disclaimer": api.DISCLAIMER, "api_version": api.API_VERSION,
        "addresses": [api.address_info(a) for a in ids],
        "files": {"lookup": "lookup/{address_id}.{lang}.json", "rules": "rules.{lang}.json", "changes": "changes.json",
                  "change_detail": "changes/{test_id}.json", "conflicts": "conflicts.json", "audit": "audit.json"}})
    files = list(out.rglob("*.json"))
    return {"dir": str(out), "files": len(files), "bytes": sum(f.stat().st_size for f in files),
            "seconds": round(time.perf_counter() - t0, 1)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    r = export()
    print(f"{r['files']} files, {r['bytes'] / 1e6:.1f} MB -> {r['dir']} ({r['seconds']} s)")
