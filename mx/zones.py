"""Zones index loaded from data/mx/zones.json (built by scripts/build_mx_zones.py, never by hand).

``legal_coverage`` in the file is ignored: it is computed from verified requirements.
A stat is kept only if its ``source`` is a doc_id present (and intact) in the manifests.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


def fold(s: str) -> str:
    """Accent- and case-insensitive key ("Cuauhtémoc" == "cuauhtemoc")."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)).casefold().strip()


@dataclass
class Municipio:
    cve_ent: str
    cve_mun: str
    name: str
    lat: float | None
    lon: float | None
    stats: dict
    extra: dict = field(default_factory=dict)
    coord: dict | None = None

    def public(self) -> dict:
        out = {"cve_ent": self.cve_ent, "cve_mun": self.cve_mun, "name": self.name, "stats": self.stats,
               "has_stats": bool(self.stats), "has_coords": self.lat is not None and self.lon is not None}
        if out["has_coords"]:
            out.update(lat=self.lat, lon=self.lon, coord=self.coord)
        # Never spread ``extra``: any scalar on a municipio outside ``stats`` has no source check,
        # so a fabricated figure (e.g. viviendas_alquiladas) must not be served. ``extra`` is kept
        # internally only; nothing from it reaches the API payload.
        return out


@dataclass
class State:
    cve_ent: str
    name: str
    abbr: str | None
    municipios: dict[str, Municipio]
    stats: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass
class ZonesIndex:
    states: dict[str, State]
    source_docs: list[str]
    dropped_stats: int = 0

    def state(self, cve_ent: str) -> State | None:
        return self.states.get(cve_ent)

    def municipio(self, cve_ent: str, cve_mun: str) -> Municipio | None:
        s = self.states.get(cve_ent)
        return s.municipios.get(cve_mun) if s else None

    def search(self, cve_ent: str, q: str | None, limit: int = 50) -> list[Municipio]:
        s = self.states.get(cve_ent)
        if s is None:
            return []
        items = sorted(s.municipios.values(), key=lambda m: m.cve_mun)
        if q:
            k = fold(q)
            starts = [m for m in items if fold(m.name).startswith(k)]
            contains = [m for m in items if k in fold(m.name) and m not in starts]
            items = starts + contains
        return items[:limit]


#: INEGI sample-estimate precision bands (documented in zones.json notes): CV >= 30 % is "baja".
CV_LOW_PRECISION = 30


def _clean_stats(raw: dict | None, known_docs: set[str]) -> tuple[dict, int]:
    out, dropped = {}, 0
    for k, v in (raw or {}).items():
        if isinstance(v, dict) and v.get("value") is not None and v.get("source") in known_docs:
            v = dict(v)
            if v.get("cv") is not None:
                v["precision_baja"] = v["cv"] >= CV_LOW_PRECISION
            out[k] = v
        else:
            dropped += 1
    return out, dropped


def load_zones(path: Path, known_docs: set[str]) -> ZonesIndex:
    data = json.loads(path.read_text(encoding="utf-8"))
    states: dict[str, State] = {}
    dropped = 0
    for s in data.get("states", []):
        munis = {}
        for m in s.get("municipios", []):
            stats, d = _clean_stats(m.get("stats"), known_docs)
            dropped += d
            extra = {k: v for k, v in m.items() if k not in ("cve_mun", "name", "lat", "lon", "stats")
                     and not isinstance(v, (dict, list))}
            lat, lon, coord = m.get("lat"), m.get("lon"), m.get("coord")
            # Serve coordinates only when a ``coord`` block names a known source. lat/lon with no
            # coord block at all (or an unknown/absent source) are dropped: no coordinate is shown
            # without provenance.
            if not (isinstance(coord, dict) and coord.get("source") in known_docs):
                lat = lon = coord = None
            munis[m["cve_mun"]] = Municipio(s["cve_ent"], m["cve_mun"], m["name"], lat, lon, stats, extra, coord)
        sstats, d = _clean_stats(s.get("stats"), known_docs)
        dropped += d
        sextra = {k: v for k, v in s.items() if k in ("nom_abrev_inegi",)}
        states[s["cve_ent"]] = State(s["cve_ent"], s["name"], s.get("abbr"), munis, sstats, sextra)
    return ZonesIndex(states, list(data.get("source_docs", [])), dropped)
