import csv
import sys

import bvc_api
import bvc_parse
from downloader import DATA_DIR, DIARIOS_DIR, download_date, load_dates_csv

INDICES_CSV = DATA_DIR / "indices.csv"


def _print_summary(parsed, fecha):
    ig = parsed["indices"].get("general") or {}
    fi = parsed["indices"].get("financiero") or {}
    ii = parsed["indices"].get("industrial") or {}
    vbe = parsed["alza_baja_estables"] or {}
    tot = parsed["totales_regulares"] or {}

    print("=" * 60)
    print(f"DIARIO DE LA BOLSA - {fecha}")
    print("=" * 60)
    print(f"Indice General     : {ig.get('valor'):>12,.2f}  ({ig.get('var_abs'):+.2f} / {ig.get('var_rel'):+.2f}%)")
    print(f"Indice Financiero  : {fi.get('valor'):>12,.2f}  ({fi.get('var_abs'):+.2f} / {fi.get('var_rel'):+.2f}%)")
    print(f"Indice Industrial  : {ii.get('valor'):>12,.2f}  ({ii.get('var_abs'):+.2f} / {ii.get('var_rel'):+.2f}%)")
    print(f"Tasa de cambio     : {parsed.get('tasa_cambio') or '-'}")
    if vbe:
        print(f"En alza / baja / estables: {vbe.get('alza')} / {vbe.get('baja')} / {vbe.get('estables')}")
    if tot:
        print(f"Operaciones regulares: {tot.get('nops')} ops | monto Bs: {tot.get('monto'):,.2f}")
    print("-" * 60)

    mov = sorted(parsed["regulares"], key=lambda x: (x["var_rel"] or 0), reverse=True)
    print("TOP 5 SUBIDAS")
    for it in mov[:5]:
        print(f"  {it['simbolo']:<8} {it['hoy']:>12,.2f}  {it['var_rel']:+.2f}%")
    print("TOP 5 BAJADAS")
    for it in mov[-5:][::-1]:
        print(f"  {it['simbolo']:<8} {it['hoy']:>12,.2f}  {it['var_rel']:+.2f}%")
    print("MÁS NEGOCIADAS")
    for it in sorted(parsed["regulares"], key=lambda x: x["monto"] or 0, reverse=True)[:5]:
        print(f"  {it['simbolo']:<8} {it['nops']:>5} ops  Bs {it['monto']:,.2f}")
    print("=" * 60)


def run():
    dates = bvc_api.get_dates()
    if not dates:
        print("No se obtuvieron fechas disponibles.")
        return 1
    latest = dates[-1]
    yyyymmdd = latest.replace("-", "")
    parsed = download_date(yyyymmdd)
    if parsed is None:
        print(f"Sin datos para la fecha mas reciente {latest}.")
        return 1
    try:
        from build_prices import build_prices
        build_prices()
    except Exception:
        pass
    try:
        from downloader import rebuild_indices
        rebuild_indices()
    except Exception:
        pass
    _print_summary(parsed, latest)
    return 0


if __name__ == "__main__":
    sys.exit(run())
