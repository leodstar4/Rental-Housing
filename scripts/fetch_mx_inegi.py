"""Download official INEGI files for Renta MX zones (network step).

Run once:  python scripts/fetch_mx_inegi.py
Then:      python scripts/build_mx_zones.py   (offline)

Downloads (all published by INEGI):
  * ITER 2020 national CSV zip (Principales resultados por localidad, Censo 2020)
      -> corpus_mx/inegi/raw/ (gitignored, ~37 MB zip / 150 MB CSV)
      -> derived extract corpus_mx/inegi/iter2020_extract.csv (municipal totals,
         loc=0000, plus the cabecera-municipal locality row of every municipio)
  * Catálogo Único de Claves Geoestadísticas web service (wscatgeo v2):
      mgee (entidades) and mgem/<cve_ent> (municipios, incl. cve_cab)
  * Censo 2020 Cuestionario Ampliado, tabulados predefinidos "Vivienda"
      (cpv2020_a_<slug>_16_vivienda.xlsx), one per entity; the URL of each file is
      discovered through INEGI's own download-listing API (pathLogico), not guessed.

Writes corpus_mx/manifest_inegi.json. Re-running only downloads missing files
(use --force to re-download everything).
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "corpus_mx" / "inegi"
RAW = OUT / "raw"
CAT = OUT / "catgeo"
AMP = OUT / "ampliado_vivienda"
MANIFEST = ROOT / "corpus_mx" / "manifest_inegi.json"

UA = {"User-Agent": "Mozilla/5.0 (RentaMX data pipeline)"}
ITER_URL = "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/iter/iter_00_cpv2020_csv.zip"
ITER_MEMBER = "iter_00_cpv2020/conjunto_de_datos/conjunto_de_datos_iter_00CSV20.csv"
MGEE_URL = "https://gaia.inegi.org.mx/wscatgeo/v2/mgee/"
MGEM_URL = "https://gaia.inegi.org.mx/wscatgeo/v2/mgem/{ent}"
LIST_API = "https://www.inegi.org.mx/app/api/descarga/componente/descargamasiva/lista/archivoscompaginacion"
CONTENIDOS = "https://www.inegi.org.mx/contenidos"

EXTRACT = OUT / "iter2020_extract.csv"
EXTRACT_COLS = ["ENTIDAD", "NOM_ENT", "MUN", "NOM_MUN", "LOC", "NOM_LOC", "LONGITUD", "LATITUD",
                "ALTITUD", "POBTOT", "VIVTOT", "TVIVHAB", "TVIVPAR", "VIVPAR_HAB", "TVIVPARHAB"]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get(url: str, tries: int = 6, timeout: int = 180) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # network is flaky (INEGI drops connections)
            last = e
            time.sleep(3 + 4 * i)
    raise RuntimeError(f"GET failed after {tries} tries: {url}: {last}")


def download(url: str, dest: Path, force: bool, validate=None) -> tuple[bool, str | None]:
    """Returns (downloaded_now, retrieved_at)."""
    if dest.exists() and not force:
        return False, None
    data = get(url)
    if validate:
        validate(data)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True, now_iso()


def is_json(data: bytes) -> None:
    json.loads(data.decode("utf-8"))


def is_xlsx(data: bytes) -> None:
    if not data.startswith(b"PK"):
        raise ValueError("not an xlsx (INEGI returns a 200 HTML page for missing files)")


def is_zip(data: bytes) -> None:
    if not data.startswith(b"PK"):
        raise ValueError("not a zip")


def find_ampliado_vivienda_path(cve_ent: str) -> str:
    q = {
        "tema": "0", "subtema": "0", "areaGeografica": str(int(cve_ent)), "proyecto": "0", "anio": "0",
        "tipodocto": "5", "agrupacion": base64.b64encode(b"Todas").decode(), "idBiinegi": "3001",
        "desde": "1", "hasta": "400", "textoBuscar": "Vivienda", "ordenar": "orden", "ingles": "0",
        "datosAbiertos": "0", "orden": "",
    }
    rows = json.loads(get(LIST_API + "?" + urllib.parse.urlencode(q)).decode("utf-8"))
    hits = [r["pathLogico"] for r in rows
            if "/tabulados/ampliado/" in (r.get("pathLogico") or "")
            and r["pathLogico"].endswith("_16_vivienda")
            and "/cpv2020_a_d_" not in r["pathLogico"]]  # _a_d_ = desglose por distrito (Oaxaca)
    if len(hits) != 1:
        raise RuntimeError(f"cve_ent {cve_ent}: expected 1 ampliado vivienda tabulado, got {hits}")
    return hits[0]


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"docs": []}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    old = {d["doc_id"]: d for d in load_manifest().get("docs", [])}
    docs: list[dict] = []

    def add(doc_id, title, url, path: Path, fresh_ts, extra=None):
        prev = old.get(doc_id, {})
        ts = fresh_ts or prev.get("retrieved_at") or now_iso()
        d = {"doc_id": doc_id, "title": title, "publisher": "INEGI", "jurisdiction": "FED",
             "url": url, "retrieved_at": ts, "sha256": sha256(path),
             "file_path": path.relative_to(ROOT).as_posix(), "text_path": None}
        if extra:
            d.update(extra)
        docs.append(d)

    # 01 ITER
    zpath = RAW / "iter_00_cpv2020_csv.zip"
    _, ts = download(ITER_URL, zpath, args.force, is_zip)
    print("ITER zip ok")

    # 02 entidades
    mgee = CAT / "mgee.json"
    _, ts2 = download(MGEE_URL, mgee, args.force, is_json)
    add("D-MX-INEGI-02", "Catálogo Único de Claves Geoestadísticas (servicio web wscatgeo v2): áreas geoestadísticas estatales (mgee)",
        MGEE_URL, mgee, ts2)
    ents = [e["cve_ent"] for e in json.loads(mgee.read_text(encoding="utf-8"))["datos"]]
    assert len(ents) == 32, len(ents)

    # 03..34 municipios per entity
    for i, ent in enumerate(ents):
        p = CAT / f"mgem_{ent}.json"
        url = MGEM_URL.format(ent=ent)
        _, t = download(url, p, args.force, is_json)
        add(f"D-MX-INEGI-{3 + i:02d}",
            f"Catálogo Único de Claves Geoestadísticas (servicio web wscatgeo v2): áreas geoestadísticas municipales (mgem) de la entidad {ent}",
            url, p, t)
        print("mgem", ent, "ok")

    # ITER extract (municipal totals + cabecera localities)
    cab = {}
    for ent in ents:
        for m in json.loads((CAT / f"mgem_{ent}.json").read_text(encoding="utf-8"))["datos"]:
            if m.get("cve_cab") and m["cve_cab"].isdigit():
                cab[(m["cve_ent"], m["cve_mun"])] = m["cve_cab"]
    keep: list[dict] = []
    # municipios whose catalog entry has no numeric cabecera (e.g. CDMX alcaldías, "----"):
    # keep their most populated locality instead, flagged in column SELECCION.
    best: dict[tuple[str, str], dict] = {}
    with zipfile.ZipFile(zpath) as z, z.open(ITER_MEMBER) as fh:
        rdr = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline=""))
        missing = [c for c in EXTRACT_COLS if c not in rdr.fieldnames]
        assert not missing, missing
        for r in rdr:
            key = (r["ENTIDAD"], r["MUN"])
            if r["LOC"] == "0000":
                keep.append({**r, "SELECCION": "total"})
            elif cab.get(key) == r["LOC"]:
                keep.append({**r, "SELECCION": "cabecera_municipal"})
            elif (key not in cab and r["MUN"] != "000" and r["LOC"] not in ("9998", "9999")
                  and r["POBTOT"].isdigit() and r["LATITUD"]):
                b = best.get(key)
                if b is None or int(r["POBTOT"]) > int(b["POBTOT"]):
                    best[key] = r
    keep += [{**r, "SELECCION": "localidad_mas_poblada"} for r in best.values()]
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(EXTRACT_COLS + ["SELECCION"])
    for r in keep:
        w.writerow([r[c] for c in EXTRACT_COLS + ["SELECCION"]])
    n = len(keep)
    EXTRACT.write_text(buf.getvalue(), encoding="utf-8", newline="")
    print("ITER extract rows:", n)
    add("D-MX-INEGI-01",
        "Censo de Población y Vivienda 2020. Principales resultados por localidad (ITER), nacional, CSV",
        ITER_URL, zpath, ts,
        {"file_in_repo": False,
         "zip_member": ITER_MEMBER,
         "derived_files": [{
             "file_path": EXTRACT.relative_to(ROOT).as_posix(),
             "sha256": sha256(EXTRACT),
             "rule": "rows with LOC=='0000' (totals: nacional/entidad/municipio; SELECCION=total) plus, per municipio, the row whose LOC equals cve_cab from the INEGI mgem catalog (SELECCION=cabecera_municipal); for municipios whose catalog cve_cab is not numeric (e.g. '----' in CDMX) the locality with the largest POBTOT that has coordinates (SELECCION=localidad_mas_poblada). Columns copied verbatim: " + ",".join(EXTRACT_COLS),
         }]})

    # 35..66 Cuestionario ampliado, Vivienda tabulados per entity
    for i, ent in enumerate(ents):
        p_existing = sorted(AMP.glob(f"{ent}_*.xlsx"))
        prev = old.get(f"D-MX-INEGI-{35 + i:02d}")
        if p_existing and prev and not args.force:
            p, url, t = p_existing[0], prev["url"], None
        else:
            logical = find_ampliado_vivienda_path(ent)
            url = CONTENIDOS + logical + ".xlsx"
            p = AMP / f"{ent}_{logical.rsplit('/', 1)[1]}.xlsx"
            _, t = download(url, p, True, is_xlsx)
        add(f"D-MX-INEGI-{35 + i:02d}",
            f"Censo de Población y Vivienda 2020. Tabulados del Cuestionario Ampliado. Vivienda (estatal/municipal), entidad {ent}",
            url, p, t)
        print("ampliado", ent, "ok")

    docs.sort(key=lambda d: d["doc_id"])
    MANIFEST.write_text(json.dumps({"docs": docs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("manifest:", MANIFEST, len(docs), "docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
