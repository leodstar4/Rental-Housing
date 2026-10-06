"""Build data/mx/zones.json from the INEGI files already downloaded (NO network).

    python scripts/fetch_mx_inegi.py      # network step, once (writes corpus_mx/manifest_inegi.json)
    python scripts/build_mx_zones.py      # offline; validates and writes data/mx/zones.json

Sources (doc_ids from corpus_mx/manifest_inegi.json):
  D-MX-INEGI-01      ITER 2020 (Censo de Población y Vivienda 2020, principales resultados por
                     localidad). Used through the derived extract corpus_mx/inegi/iter2020_extract.csv
                     (sha256 of the extract is recorded in the manifest; the original zip stays in
                     corpus_mx/inegi/raw/, gitignored). POBTOT, TVIVPARHAB, LATITUD/LONGITUD.
  D-MX-INEGI-02      Catálogo Único de Claves Geoestadísticas, entidades (mgee): cve_ent, nombre,
                     nom_abrev (official INEGI abbreviation, used to derive `abbr`).
  D-MX-INEGI-03..34  Catálogo Único, municipios (mgem) per entidad: cve_mun, nombre, cve_cab.
  D-MX-INEGI-35..66  Censo 2020, Cuestionario Ampliado, tabulados "Vivienda" per entidad:
                     tenencia por municipio/demarcación -> % de viviendas alquiladas (estimador).

`abbr`: INEGI nom_abrev with dots/spaces/accents removed and upper-cased (Ags.->AGS, Q. Roo->QROO,
Mex.->MEX ...). The 8 abbreviations fixed by docs/MX_SPEC.md (CDMX, JAL, NL, MEX, QRO, PUE, YUC,
QROO) are asserted to match that derivation.

`legal_coverage`: "solo_federal" for every state by default. Pass
`--coverage-from-requirements` to mark "estatal_verificada" every state that has a non-empty
data/mx/requirements/<ABBR>.yaml (or call `apply_legal_coverage(zones, abbrs)` from another step).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "corpus_mx" / "manifest_inegi.json"
OUT = ROOT / "data" / "mx" / "zones.json"
REQ_DIR = ROOT / "data" / "mx" / "requirements"
YEAR = 2020
SPEC_ABBR = {"09": "CDMX", "14": "JAL", "19": "NL", "15": "MEX", "22": "QRO", "21": "PUE",
             "31": "YUC", "23": "QROO"}


# ---------------------------------------------------------------- helpers
def load_manifest() -> dict[str, dict]:
    docs = json.loads(MANIFEST.read_text(encoding="utf-8"))["docs"]
    return {d["doc_id"]: d for d in docs}


def official_abbr(nom_abrev: str) -> str:
    s = unicodedata.normalize("NFKD", nom_abrev)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z]", "", s).upper()


_DMS = re.compile(r"""^\s*(\d+)°\s*(\d+)'\s*([\d.]+)"\s*([NSEW])\s*$""")


def dms_to_decimal(s: str) -> float | None:
    m = _DMS.match(s or "")
    if not m:
        return None
    d, mi, se, h = int(m.group(1)), int(m.group(2)), float(m.group(3)), m.group(4)
    v = d + mi / 60 + se / 3600
    return round(-v if h in "SW" else v, 6)


def num(s: str):
    s = (s or "").strip()
    if not s or s == "*":
        return None
    try:
        return int(s)
    except ValueError:
        return float(s)


# minimal stdlib xlsx reader (no openpyxl dependency)
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: Path, only: set[str] | None = None) -> dict[str, list[list]]:
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in wb.find("m:sheets", _NS):
        name = sh.get("name")
        if only is not None and name not in only:
            continue
        tgt = rels[sh.get("{%s}id" % _NS["r"])].lstrip("/")
        tgt = tgt if tgt.startswith("xl/") else "xl/" + tgt
        rows = []
        for row in ET.fromstring(z.read(tgt)).iter("{%s}row" % _NS["m"]):
            vals = {}
            for c in row.findall("m:c", _NS):
                t, v = c.get("t"), c.find("m:v", _NS)
                if t == "s" and v is not None:
                    val = ss[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["m"]))
                else:
                    val = v.text if v is not None else None
                vals[_col(c.get("r"))] = val
            rows.append([vals.get(i) for i in range(max(vals) + 1)] if vals else [])
        out[name] = rows
    return out


# ---------------------------------------------------------------- sources
def read_tenure(path: Path) -> dict[str, dict]:
    """cve_mun -> {pct_alquilada, cv, li, ls, sheet, title} from the ampliado 'Vivienda' workbook."""
    idx = read_xlsx(path, {"Índice"})["Índice"]
    sheet = title = None
    for r in idx:
        cells = [str(x).strip() for x in r if x not in (None, "")]
        # Índice columns: Tabulado | Subtema | Desglose | Título
        if len(cells) >= 4 and cells[1] == "Tenencia de la vivienda" \
                and cells[2] != "Tamaño de localidad" and re.fullmatch(r"\d{2}", cells[0]):
            sheet, title = cells[0], cells[3]
    if not sheet:
        raise RuntimeError(f"{path.name}: no 'Tenencia de la vivienda' por municipio sheet in Índice")
    rows = read_xlsx(path, {sheet})[sheet]
    hdr = next(r for r in rows if r and "Alquilada" in [str(x).strip() if x else "" for x in r])
    col = [str(x).strip() if x else "" for x in hdr].index("Alquilada")
    res: dict[str, dict] = {}
    for r in rows:
        if len(r) <= col or not r[1] or r[2] != "Viviendas":
            continue
        m = re.match(r"^(\d{3}) ", r[1])
        if not m:
            continue
        d = res.setdefault(m.group(1), {"sheet": sheet, "title": title, "name": r[1][4:].strip()})
        key = {"Valor": "value", "Coeficiente de variación": "cv",
               "Límite inferior de confianza": "li", "Límite superior de confianza": "ls"}.get(r[3])
        if key:
            d[key] = float(r[col]) if r[col] not in (None, "") else None
    return res


def stat(value, source, field, **extra):
    d = {"value": value, "source": source, "year": YEAR, "field": field}
    d.update(extra)
    return d


# ---------------------------------------------------------------- build
def apply_legal_coverage(zones: dict, verified_abbrs: set[str]) -> None:
    for s in zones["states"]:
        s["legal_coverage"] = "estatal_verificada" if s["abbr"] in verified_abbrs else "solo_federal"


def verified_from_requirements() -> set[str]:
    out = set()
    if REQ_DIR.is_dir():
        for p in REQ_DIR.glob("*.yaml"):
            if p.stem != "FED" and p.read_text(encoding="utf-8").strip().startswith("-"):
                out.add(p.stem)
    return out


def build() -> tuple[dict, dict]:
    man = load_manifest()
    iter_doc = man["D-MX-INEGI-01"]
    extract = ROOT / iter_doc["derived_files"][0]["file_path"]
    mgee = json.loads((ROOT / man["D-MX-INEGI-02"]["file_path"]).read_text(encoding="utf-8"))["datos"]
    assert len(mgee) == 32, f"expected 32 entidades, got {len(mgee)}"

    totals, coords = {}, {}
    with open(extract, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            k = (r["ENTIDAD"], r["MUN"])
            if r["SELECCION"] == "total":
                totals[k] = r
            else:
                coords[k] = r

    report = {"entidades": 0, "municipios": 0, "catalog_numReg_sum": 0, "errors": [], "warnings": [],
              "missing_coords": [], "missing_census": [], "missing_tenure": [], "name_diffs_iter": []}
    states, source_docs = [], {"D-MX-INEGI-01", "D-MX-INEGI-02"}
    for i, e in enumerate(sorted(mgee, key=lambda x: x["cve_ent"])):
        ent = e["cve_ent"]
        abbr = official_abbr(e["nom_abrev"])
        if ent in SPEC_ABBR and SPEC_ABBR[ent] != abbr:
            report["errors"].append(f"abbr {ent}: derived {abbr} != spec {SPEC_ABBR[ent]}")
        mgem_id = f"D-MX-INEGI-{3 + i:02d}"
        amp_id = f"D-MX-INEGI-{35 + i:02d}"
        assert man[mgem_id]["file_path"].endswith(f"mgem_{ent}.json"), mgem_id
        assert f"/{ent}_" in man[amp_id]["file_path"], amp_id
        mg = json.loads((ROOT / man[mgem_id]["file_path"]).read_text(encoding="utf-8"))
        report["catalog_numReg_sum"] += int(mg["numReg"])
        tenure = read_tenure(ROOT / man[amp_id]["file_path"])
        source_docs |= {mgem_id}
        used_amp = False

        munis = []
        for m in sorted(mg["datos"], key=lambda x: x["cve_mun"]):
            mun = m["cve_mun"]
            name = (m.get("nomgeo") or "").strip()
            if not name or not re.fullmatch(r"\d{3}", mun):
                report["errors"].append(f"bad municipio record {ent}/{mun!r}: {name!r}")
            z = {"cve_mun": mun, "name": name, "name_source": mgem_id}
            c = coords.get((ent, mun))
            if c:
                lat, lon = dms_to_decimal(c["LATITUD"]), dms_to_decimal(c["LONGITUD"])
                if lat is not None and lon is not None:
                    z["lat"], z["lon"] = lat, lon
                    z["coord"] = {
                        "represents": c["SELECCION"],  # cabecera_municipal | localidad_mas_poblada
                        "cve_loc": c["LOC"], "nom_loc": c["NOM_LOC"],
                        "latitud_dms": c["LATITUD"], "longitud_dms": c["LONGITUD"],
                        "source": "D-MX-INEGI-01", "year": YEAR,
                        "cabecera_source": mgem_id if c["SELECCION"] == "cabecera_municipal" else None,
                    }
            if "lat" not in z:
                report["missing_coords"].append(f"{ent}{mun} {name}")
            stats = {}
            t = totals.get((ent, mun))
            if t:
                if t["NOM_MUN"] != name:
                    z["name_censo_2020"] = t["NOM_MUN"]
                    report["name_diffs_iter"].append(f"{ent}{mun}: catalog={name!r} iter={t['NOM_MUN']!r}")
                for key, fld in (("poblacion_total", "POBTOT"),
                                 ("viviendas_particulares_habitadas", "TVIVPARHAB")):
                    v = num(t[fld])
                    if v is not None:
                        stats[key] = stat(v, "D-MX-INEGI-01", fld)
            else:
                report["missing_census"].append(f"{ent}{mun} {name}")
            tn = tenure.get(mun)
            if tn and tn.get("value") is not None:
                stats["pct_viviendas_alquiladas"] = stat(
                    tn["value"], amp_id,
                    f"Tenencia: Alquilada (% de viviendas particulares habitadas; renglón Viviendas/Valor; hoja {tn['sheet']})",
                    estimator="cuestionario_ampliado (muestra)", unit="percent",
                    cv=tn.get("cv"), ci90=[tn.get("li"), tn.get("ls")])
                used_amp = True
            else:
                report["missing_tenure"].append(f"{ent}{mun} {name}")
            if stats:
                z["stats"] = stats
            munis.append(z)
        if used_amp:
            source_docs.add(amp_id)

        # state totals + sum validation
        st = totals.get((ent, "000"))
        state_stats = {}
        if not st:
            report["errors"].append(f"no ITER state total for {ent}")
        else:
            for key, fld in (("poblacion_total", "POBTOT"), ("viviendas_particulares_habitadas", "TVIVPARHAB")):
                tot = num(st[fld])
                s = sum(z["stats"][key]["value"] for z in munis if key in z.get("stats", {}))
                if tot != s:
                    report["errors"].append(f"{ent} {fld}: sum municipios {s} != total entidad {tot}")
                state_stats[key] = stat(tot, "D-MX-INEGI-01", fld)
        states.append({"cve_ent": ent, "name": e["nomgeo"].strip(), "abbr": abbr,
                       "nom_abrev_inegi": e["nom_abrev"], "legal_coverage": "solo_federal",
                       "stats": state_stats, "municipios": munis})
        report["entidades"] += 1
        report["municipios"] += len(munis)

    if report["entidades"] != 32:
        report["errors"].append(f"entidades {report['entidades']} != 32")
    if report["municipios"] != report["catalog_numReg_sum"]:
        report["errors"].append(f"municipios {report['municipios']} != catalog numReg {report['catalog_numReg_sum']}")
    iter_munis = sum(1 for (e, m) in totals if e != "00" and m != "000")
    report["iter_2020_municipios"] = iter_munis
    nat = totals.get(("00", "000"))
    if nat:
        s = sum(s_["stats"]["poblacion_total"]["value"] for s_ in states)
        if int(nat["POBTOT"]) != s:
            report["errors"].append(f"national POBTOT {nat['POBTOT']} != sum states {s}")
        report["national_pobtot"] = int(nat["POBTOT"])

    zones = {
        "generated_by": "scripts/build_mx_zones.py",
        "source_docs": sorted(source_docs),
        "notes": {
            "lat_lon": "Decimal conversion of ITER 2020 LATITUD/LONGITUD (DMS) of the locality named in coord.represents: the cabecera municipal per the INEGI catalog (cve_cab), or, when the catalog gives no cabecera (CDMX alcaldías), the most populated locality of the municipio.",
            "pct_viviendas_alquiladas": "Estimador del Cuestionario Ampliado (muestra). Incluye cv (%) e intervalo de confianza al 90%. Precisión INEGI: alta CV<15, moderada 15-30, baja >=30.",
            "municipios": "Catálogo Único vigente (mgem) a la fecha de descarga; incluye municipios creados después del Censo 2020, que no tienen stats ni coordenadas (su población 2020 está contada en el municipio de origen). Las stats de 2020 corresponden a los límites municipales de 2020. name_censo_2020 aparece cuando el nombre en ITER 2020 difiere del catálogo vigente.",
            "legal_coverage": "solo_federal por defecto; ver --coverage-from-requirements.",
        },
        "states": states,
    }
    return zones, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage-from-requirements", action="store_true",
                    help="mark estatal_verificada for states with data/mx/requirements/<ABBR>.yaml")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    zones, report = build()
    if args.coverage_from_requirements:
        apply_legal_coverage(zones, verified_from_requirements())
    for k in ("missing_coords", "missing_census", "missing_tenure", "name_diffs_iter"):
        print(f"{k}: {len(report[k])}", *report[k][:15], sep="\n  ")
    print(f"entidades={report['entidades']} municipios={report['municipios']} "
          f"catalog_numReg={report['catalog_numReg_sum']} iter2020_municipios={report['iter_2020_municipios']}")
    if report["errors"]:
        print("ERRORS:", *report["errors"], sep="\n  ")
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(zones, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
