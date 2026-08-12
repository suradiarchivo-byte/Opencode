import re


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


TASA_RE = re.compile(r"\d+(?:\.\d+)?")


def extract_tasa(texto):
    if not texto:
        return None
    m = TASA_RE.search(texto)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_diario(raw_rows):
    out = {
        "indices": {},
        "regulares": [],
        "plazo": [],
        "bonos": [],
        "bonos_divisas": [],
        "compraventa": [],
        "alza_baja_estables": None,
        "tasa_cambio": None,
        "notas": [],
        "totales_regulares": None,
    }

    if not raw_rows or not raw_rows[0]:
        return out

    tot_op = tot_qty = tot_monto = 0.0
    for row in raw_rows:
        code = row[0] if row else ""
        if code == "IG":
            out["indices"]["general"] = {
                "fecha": row[1],
                "valor": _f(row[2]),
                "var_abs": _f(row[3]),
                "var_rel": _f(row[4]),
                "max_12m": _f(row[5]),
                "min_12m": _f(row[6]),
                "var_abs_desde_2019": _f(row[7]),
                "var_rel_desde_2019": _f(row[8]),
            }
        elif code == "IF":
            out["indices"]["financiero"] = {
                "fecha": row[1],
                "valor": _f(row[2]),
                "var_abs": _f(row[3]),
                "var_rel": _f(row[4]),
            }
        elif code == "II":
            out["indices"]["industrial"] = {
                "fecha": row[1],
                "valor": _f(row[2]),
                "var_abs": _f(row[3]),
                "var_rel": _f(row[4]),
            }
        elif code == "R":
            item = {
                "nombre": row[1],
                "simbolo": row[2],
                "anterior": _f(row[3]),
                "hoy": _f(row[4]),
                "var_abs": _f(row[5]),
                "var_rel": _f(row[6]),
                "min": _f(row[7]),
                "max": _f(row[8]),
                "promedio": _f(row[9]),
                "nops": int(_f(row[10]) or 0),
                "cantidad": _f(row[11]),
                "monto": _f(row[12]),
            }
            out["regulares"].append(item)
            tot_op += item["nops"]
            tot_qty += item["cantidad"] or 0
            tot_monto += item["monto"] or 0
        elif code == "P":
            out["plazo"].append(
                {
                    "nombre": row[1],
                    "simbolo": row[2],
                    "hoy": _f(row[4]),
                    "min": _f(row[7]),
                    "max": _f(row[8]),
                    "nops": int(_f(row[10]) or 0),
                    "cantidad": _f(row[11]),
                    "monto": _f(row[12]),
                }
            )
        elif code == "BP":
            out["bonos"].append(
                {
                    "nombre": row[1],
                    "precio_apertura": _f(row[3]),
                    "precio_cierre": _f(row[4]),
                    "var_abs": _f(row[5]),
                    "min": _f(row[7]),
                    "max": _f(row[8]),
                    "nops": int(_f(row[10]) or 0),
                    "nominal": _f(row[11]),
                    "efectivo": _f(row[12]),
                    "var_rel": _f(row[6]),
                }
            )
        elif code == "BY":
            out["bonos_divisas"].append(
                {
                    "nombre": row[1],
                    "simbolo": row[2],
                    "apertura": _f(row[3]),
                    "cierre": _f(row[4]),
                    "var_abs": _f(row[5]),
                    "min": _f(row[6]),
                    "max": _f(row[7]),
                    "nops": int(_f(row[8]) or 0),
                    "promedio": _f(row[9]),
                    "var_rel": _f(row[10]),
                    "monto_bsf": _f(row[11]),
                    "monto_nominal": _f(row[12]),
                }
            )
        elif code == "CC":
            out["compraventa"].append(
                {"accion": row[1], "compra": _f(row[2]), "venta": _f(row[3])}
            )
        elif code == "VT":
            out["alza_baja_estables"] = {
                "alza": int(_f(row[1]) or 0),
                "baja": int(_f(row[2]) or 0),
                "estables": int(_f(row[3]) or 0),
            }
        elif code == "TC":
            out["tasa_cambio"] = row[1] if len(row) > 1 else None
        elif code == "NO":
            out["notas"].append({"titulo": row[1], "texto": row[2]})

    out["totales_regulares"] = {
        "nops": int(tot_op),
        "cantidad": tot_qty,
        "monto": tot_monto,
    }
    return out


def has_results(raw_rows):
    return bool(raw_rows) and bool(raw_rows[0]) and raw_rows[0][0].startswith("I")
