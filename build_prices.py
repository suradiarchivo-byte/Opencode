import csv
import json
from pathlib import Path

from bvc_parse import extract_tasa, parse_diario
from downloader import DATA_DIR, DIARIOS_DIR

PRICES_CSV = DATA_DIR / "prices.csv"
PRICES_FIELDS = [
    "simbolo",
    "fecha",
    "precio_bs",
    "precio_usd",
    "var_rel",
    "nops",
    "cantidad",
    "monto",
    "tasa_bcv",
]


def build_prices():
    rows = []
    paths = sorted(DIARIOS_DIR.glob("*.json"))
    for path in paths:
        fecha = path.stem
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        parsed = parse_diario(raw)
        tasa = extract_tasa(parsed.get("tasa_cambio"))
        for r in parsed["regulares"]:
            pb = r.get("hoy")
            pu = None
            if pb is not None and tasa:
                pu = round(pb / tasa, 6)
            rows.append(
                {
                    "simbolo": r["simbolo"],
                    "fecha": fecha,
                    "precio_bs": pb,
                    "precio_usd": pu,
                    "var_rel": r.get("var_rel"),
                    "nops": r.get("nops"),
                    "cantidad": r.get("cantidad"),
                    "monto": r.get("monto"),
                    "tasa_bcv": tasa,
                }
            )
    with open(PRICES_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PRICES_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    n = build_prices()
    print(f"Registros de precios construidos: {n}")
