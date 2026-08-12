import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import bvc_api
import bvc_parse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DIARIOS_DIR = DATA_DIR / "diarios"
INDICES_CSV = DATA_DIR / "indices.csv"
INDICES_FIELDS = [
    "fecha",
    "general",
    "general_var_abs",
    "general_var_rel",
    "financiero",
    "financiero_var_abs",
    "financiero_var_rel",
    "industrial",
    "industrial_var_abs",
    "industrial_var_rel",
    "tasa",
    "general_usd",
    "financiero_usd",
    "industrial_usd",
    "tasa_cambio",
    "alza",
    "baja",
    "estables",
    "nops",
    "monto",
]


def _existing_dates():
    if not DIARIOS_DIR.exists():
        return set()
    return {p.stem for p in DIARIOS_DIR.iterdir() if p.suffix == ".json"}


def load_dates_csv():
    if not INDICES_CSV.exists():
        return set()
    with open(INDICES_CSV, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return {row["fecha"] for row in reader}


SCALE_SPLIT_DATE = "20250725"
SCALE_FACTOR = 1000.0


def _escala(value, fecha):
    if value is None or fecha > SCALE_SPLIT_DATE:
        return value
    return value / SCALE_FACTOR


def _row_for_date(date_yyymmdd, parsed):
    ig = parsed["indices"].get("general") or {}
    fi = parsed["indices"].get("financiero") or {}
    ii = parsed["indices"].get("industrial") or {}
    vbe = parsed["alza_baja_estables"] or {}
    tot = parsed["totales_regulares"] or {}
    tasa = bvc_parse.extract_tasa(parsed.get("tasa_cambio"))

    def _usd(value):
        if value is None or tasa is None or tasa <= 0:
            return None
        return round(value / tasa, 6)

    g = _escala(ig.get("valor"), date_yyymmdd)
    f = _escala(fi.get("valor"), date_yyymmdd)
    i = _escala(ii.get("valor"), date_yyymmdd)

    return {
        "fecha": date_yyymmdd,
        "general": g,
        "general_var_abs": _escala(ig.get("var_abs"), date_yyymmdd),
        "general_var_rel": ig.get("var_rel"),
        "financiero": f,
        "financiero_var_abs": _escala(fi.get("var_abs"), date_yyymmdd),
        "financiero_var_rel": fi.get("var_rel"),
        "industrial": i,
        "industrial_var_abs": _escala(ii.get("var_abs"), date_yyymmdd),
        "industrial_var_rel": ii.get("var_rel"),
        "tasa": tasa,
        "general_usd": _usd(g),
        "financiero_usd": _usd(f),
        "industrial_usd": _usd(i),
        "tasa_cambio": parsed.get("tasa_cambio"),
        "alza": vbe.get("alza"),
        "baja": vbe.get("baja"),
        "estables": vbe.get("estables"),
        "nops": tot.get("nops"),
        "monto": tot.get("monto"),
    }


def rebuild_indices():
    rows = []
    for path in sorted(DIARIOS_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not bvc_parse.has_results(raw):
            continue
        parsed = bvc_parse.parse_diario(raw)
        rows.append(_row_for_date(path.stem, parsed))
    rows.sort(key=lambda r: r["fecha"])
    with open(INDICES_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=INDICES_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def append_indices_row(row):
    new = not INDICES_CSV.exists()
    with open(INDICES_CSV, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=INDICES_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def download_date(date_yyyymmdd, session=None, save_dat=False):
    raw = bvc_api.get_diario(date_yyyymmdd, session=session)
    if not bvc_parse.has_results(raw):
        return None
    json_path = DIARIOS_DIR / f"{date_yyyymmdd}.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False)
    if save_dat:
        dat_path = DIARIOS_DIR / f"{date_yyyymmdd}.dat"
        bvc_api.download_dat(date_yyyymmdd, dat_path, session=session)
    parsed = bvc_parse.parse_diario(raw)
    append_indices_row(_row_for_date(date_yyyymmdd, parsed))
    return parsed


def download_all(save_dat=False, limit=None, sleep=0.0):
    DIARIOS_DIR.mkdir(parents=True, exist_ok=True)
    existing = _existing_dates()
    dates = bvc_api.get_dates()
    missing = [d for d in dates if d.replace("-", "") not in existing]
    if limit:
        missing = missing[:limit]

    session = bvc_api._session()
    ok = skipped = failed = 0
    for i, date in enumerate(missing, 1):
        yyyymmdd = date.replace("-", "")
        try:
            parsed = download_date(yyyymmdd, session=session, save_dat=save_dat)
            if parsed is None:
                skipped += 1
            else:
                ok += 1
            print(f"[{i}/{len(missing)}] {date} OK")
        except Exception as exc:
            failed += 1
            print(f"[{i}/{len(missing)}] {date} ERROR: {exc}", file=sys.stderr)
        if sleep:
            time.sleep(sleep)
    try:
        from build_prices import build_prices
        n = build_prices()
        print(f"Precios actualizados (Bs/USD): {n} registros")
    except Exception as exc:
        print(f"No se pudo construir prices.csv: {exc}", file=sys.stderr)
    try:
        n = rebuild_indices()
        print(f"Indices actualizados (Bs/USD): {n} registros")
    except Exception as exc:
        print(f"No se pudo reconstruir indices.csv: {exc}", file=sys.stderr)
    print(f"Descargados: {ok} | Sin datos: {skipped} | Errores: {failed} | Ya tenidos: {len(existing)}")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Descarga el historico del Diario de la Bolsa de Caracas")
    parser.add_argument("--dat", action="store_true", help="Ademas de JSON, guarda el archivo DAT oficial")
    parser.add_argument("--limit", type=int, default=None, help="Limitar a N fechas (pruebas)")
    parser.add_argument("--sleep", type=float, default=0.0, help="Pausa en segundos entre descargas")
    args = parser.parse_args()
    sys.exit(download_all(save_dat=args.dat, limit=args.limit, sleep=args.sleep))
