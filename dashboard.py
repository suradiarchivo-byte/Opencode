import argparse
import csv
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import bvc_api
import bvc_parse
from build_prices import PRICES_FIELDS
from downloader import DATA_DIR, DIARIOS_DIR

ROOT = Path(__file__).resolve().parent
INDICES_CSV = DATA_DIR / "indices.csv"
PRICES_CSV = DATA_DIR / "prices.csv"
PORTAFOLIO_JSON = DATA_DIR / "portafolio.json"
HTML = ROOT / "dashboard.html"
HTML_NOTICIAS = ROOT / "noticias.html"
HTML_PORTAFOLIO = ROOT / "portafolio.html"
HTML_REGISTROS = ROOT / "registros.html"

_cache = {}


def _read_prices():
    if not PRICES_CSV.exists():
        return []
    stamp = PRICES_CSV.stat().st_mtime_ns
    if _cache.get("prices") and _cache.get("prices_stamp") == stamp:
        return _cache["prices"]
    with open(PRICES_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    _cache["prices"] = rows
    _cache["prices_stamp"] = stamp
    _cache["prices_flat"] = None
    return rows


def _prices_flat():
    rows = _read_prices()
    if _cache.get("prices_flat"):
        return _cache["prices_flat"]
    last = {}
    by_sym = {}
    for r in rows:
        sim = r["simbolo"]
        by_sym.setdefault(sim, {})[r["fecha"]] = r
        if sim not in last or r["fecha"] > last[sim]["fecha"]:
            last[sim] = r
    _cache["prices_flat"] = (last, by_sym)
    return _cache["prices_flat"]


def _read_indices():
    if not INDICES_CSV.exists():
        return []
    with open(INDICES_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _simbolo_nombres():
    """Mapa simbolo -> nombre de empresa tomado del diario mas reciente que lo mencione."""
    if _cache.get("nombres"):
        return _cache["nombres"]
    nombres = {}
    for path in sorted(_diario_paths(), reverse=True):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        for r in bvc_parse.parse_diario(raw)["regulares"]:
            if r["simbolo"] not in nombres and r.get("nombre"):
                nombres[r["simbolo"]] = r["nombre"]
    _cache["nombres"] = nombres
    return nombres


def _read_diario(fecha):
    path = DIARIOS_DIR / f"{fecha}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return bvc_parse.parse_diario(raw)


def _diario_paths():
    return sorted(DIARIOS_DIR.glob("*.json"))


SIMBOLOS_INFO_JSON = DATA_DIR / "simbolos_info.json"
SIMBOLOS_INFO_TTL = 3600 * 24  # 24 horas
SECTORES_JSON = DATA_DIR / "sectores.json"


def _read_sectores():
    """Mapa manual simbolo -> sector desde data/sectores.json."""
    if not SECTORES_JSON.exists():
        return {}
    stamp = SECTORES_JSON.stat().st_mtime
    if _cache.get("sectores_stamp") == stamp:
        return _cache["sectores"]
    with open(SECTORES_JSON, encoding="utf-8") as fh:
        raw = json.load(fh)
    inv = {}
    for sector, sims in raw.items():
        for s in sims:
            inv[s] = sector
    _cache["sectores"] = inv
    _cache["sectores_stamp"] = stamp
    return inv


def _read_simbolos_info():
    if not SIMBOLOS_INFO_JSON.exists():
        return {}
    stamp = SIMBOLOS_INFO_JSON.stat().st_mtime
    if _cache.get("simbolos_info_stamp") == stamp:
        return _cache["simbolos_info"]
    with open(SIMBOLOS_INFO_JSON, encoding="utf-8") as fh:
        data = json.load(fh)
    _cache["simbolos_info"] = data
    _cache["simbolos_info_stamp"] = stamp
    return data


def _simbolo_info(simbolo, force=False):
    """Info de un simbolo con cache en disco (TTL). Descarga desde la BVC si hace falta."""
    cache = _read_simbolos_info()
    now = time.time()
    entry = cache.get(simbolo)
    if not force and entry and (now - entry.get("ts", 0)) < SIMBOLOS_INFO_TTL:
        return entry.get("data")
    try:
        info = bvc_api.get_simbolo_detalle(simbolo)
    except Exception:
        if entry:
            return entry.get("data")
        return None
    cache[simbolo] = {"ts": now, "data": info}
    try:
        with open(SIMBOLOS_INFO_JSON, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False)
        _cache["simbolos_info"] = cache
        _cache["simbolos_info_stamp"] = SIMBOLOS_INFO_JSON.stat().st_mtime
    except OSError:
        pass
    return info


def _capitalizacion():
    """Capitalizacion bursatil por simbolo (Bs y USD) + cotizacion del ultimo dia.
    Combina la info de la BVC (getSimbolosDetalle, cache 24h) con la ultima fila de prices.csv."""
    sectores = _read_sectores()
    last, _ = _prices_flat()
    nombres = _simbolo_nombres()
    out = []
    for sim in sorted(last):
        fila = last[sim]
        info = _simbolo_info(sim) or {}
        cap_bs = _fnum(info.get("capitali_bs"))
        cap_us = _fnum(info.get("capitali_us"))
        if cap_bs is None and cap_us is None:
            continue
        var_rel = _fnum(info.get("var_rel"))
        if var_rel is None:
            var_rel = _fnum(fila.get("var_rel"))
        precio = _fnum(info.get("precio"))
        if precio is None:
            precio = _fnum(fila.get("precio_bs"))
        out.append(
            {
                "simbolo": sim,
                "nombre": nombres.get(sim, info.get("descripcion") or sim),
                "sector": sectores.get(sim, "Otros"),
                "capitali_bs": cap_bs,
                "capitali_us": cap_us,
                "precio": precio,
                "var_rel": var_rel,
                "fecha": fila.get("fecha"),
            }
        )
    return out


def _noticias():
    paths = _diario_paths()
    fingerprint = (len(paths), max((p.stat().st_mtime_ns for p in paths), default=0))
    if _cache.get("noticias_fp") == fingerprint:
        return _cache["noticias"]
    out = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not bvc_parse.has_results(raw):
            continue
        parsed = bvc_parse.parse_diario(raw)
        for n in parsed["notas"]:
            out.append({"fecha": path.stem, "titulo": n["titulo"], "texto": n["texto"]})
    out.sort(key=lambda n: n["fecha"], reverse=True)
    _cache["noticias_fp"] = fingerprint
    _cache["noticias"] = out
    return out


def _read_portafolio():
    if not PORTAFOLIO_JSON.exists():
        return {"compras": [], "ventas": []}
    with open(PORTAFOLIO_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def _write_portafolio(data):
    with open(PORTAFOLIO_JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _fnum(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _enrich_op(op, by_sym, last):
    sim = op["ticker"]
    fecha = str(op.get("fecha", ""))
    p = _fnum(op.get("precio_bs"))
    com = _fnum(op.get("comision_bs")) or 0
    q = float(op.get("cantidad", 0) or 0)
    fila = by_sym.get(sim, {}).get(fecha) if fecha else None
    tasa = _fnum(fila.get("tasa_bcv")) if fila else None
    if not tasa and last.get(sim):
        tasa = _fnum(last[sim].get("tasa_bcv"))
    res = dict(op)
    res["precio_usd"] = round(p / tasa, 6) if (p is not None and tasa) else None
    res["monto_bs"] = round(p * q, 2) if p is not None else None
    res["monto_usd"] = round(p * q / tasa, 6) if (p is not None and q and tasa) else None
    res["comision_usd"] = round(com / tasa, 6) if (com and tasa) else None
    return res


def _valoracion(pf=None):
    last, by_sym = _prices_flat()
    if pf is None:
        pf = _read_portafolio()
    compras = pf.get("compras", [])
    ventas = pf.get("ventas", [])
    tickers = sorted(set([c["ticker"] for c in compras] + [v["ticker"] for v in ventas]))
    filas = []
    for sim in tickers:
        compras_sym = [c for c in compras if c["ticker"] == sim]
        ventas_sym = [v for v in ventas if v["ticker"] == sim]
        costo_bs = 0.0
        costo_usd = 0.0
        cant_comprada = 0.0
        ult = last.get(sim)
        for c in compras_sym:
            q = float(c.get("cantidad", 0) or 0)
            p = _fnum(c.get("precio_bs"))
            com = _fnum(c.get("comision_bs")) or 0
            if p is None:
                continue
            costo_bs += q * p + com
            cant_comprada += q
            fila_p = by_sym.get(sim, {}).get(str(c.get("fecha", ""))) or ult
            tasa = _fnum(fila_p.get("tasa_bcv")) if fila_p else None
            if tasa and tasa > 0:
                costo_usd += (q * p + com) / tasa
            else:
                precio_usd = _fnum(fila_p.get("precio_usd")) if fila_p else None
                costo_usd += q * (precio_usd or 0)
        cant_vendida = sum(float(v.get("cantidad", 0) or 0) for v in ventas_sym)
        cantidad = max(0.0, cant_comprada - cant_vendida)
        precio_bs = _fnum(ult.get("precio_bs")) if ult else None
        precio_usd = _fnum(ult.get("precio_usd")) if ult else None
        tasa = _fnum(ult.get("tasa_bcv")) if ult else None
        costo_prom = (costo_bs / cant_comprada) if cant_comprada else None
        costo_bs_tenido = costo_prom * cantidad if (costo_prom and cantidad) else 0.0
        costo_usd_tenido = costo_prom_usd = None
        if cant_comprada and costo_usd:
            costo_prom_usd = costo_usd / cant_comprada
            costo_usd_tenido = costo_prom_usd * cantidad
        ganancia_realizada_bs = 0.0
        ganancia_realizada_usd = 0.0
        if ventas_sym and cant_comprada:
            costo_prom_bs_v = costo_bs / cant_comprada
            costo_prom_usd_v = (costo_usd / cant_comprada) if costo_usd else 0.0
            for v in ventas_sym:
                q = float(v.get("cantidad", 0) or 0)
                p = _fnum(v.get("precio_bs"))
                com = _fnum(v.get("comision_bs")) or 0
                if p is None:
                    continue
                ing_bs = q * p - com
                ganancia_realizada_bs += ing_bs - q * costo_prom_bs_v
                fila_v = by_sym.get(sim, {}).get(str(v.get("fecha", ""))) or ult
                tasa_v = _fnum(fila_v.get("tasa_bcv")) if fila_v else None
                if tasa_v and tasa_v > 0:
                    ganancia_realizada_usd += ing_bs / tasa_v - q * costo_prom_usd_v
                else:
                    precio_usd_v = _fnum(fila_v.get("precio_usd")) if fila_v else None
                    ganancia_realizada_usd += q * (precio_usd_v or 0) - q * costo_prom_usd_v
        valor_bs = cantidad * precio_bs if (cantidad and precio_bs is not None) else None
        valor_usd = cantidad * precio_usd if (cantidad and precio_usd is not None) else None
        ganancia_bs = (valor_bs - costo_bs_tenido) if (valor_bs is not None and cantidad) else None
        if valor_usd is not None and cantidad:
            ganancia_usd = valor_usd - (costo_usd_tenido or 0.0)
        else:
            ganancia_usd = None
        ganancia_pct = (ganancia_bs / costo_bs_tenido * 100) if (ganancia_bs is not None and costo_bs_tenido) else None
        filas.append(
            {
                "ticker": sim,
                "cantidad": cantidad,
                "costo_total_bs": round(costo_bs_tenido, 2),
                "costo_prom_bs": round(costo_prom, 4) if costo_prom is not None else None,
                "costo_prom_usd": round(costo_prom_usd, 6) if costo_prom_usd is not None else None,
                "costo_total_usd": round(costo_usd_tenido, 4) if costo_usd_tenido is not None else None,
                "precio_bs": precio_bs,
                "precio_usd": precio_usd,
                "tasa_bcv": tasa,
                "ultima_fecha": ult.get("fecha") if ult else None,
                "valor_bs": round(valor_bs, 2) if valor_bs is not None else None,
                "valor_usd": round(valor_usd, 4) if valor_usd is not None else None,
                "ganancia_bs": round(ganancia_bs, 2) if ganancia_bs is not None else None,
                "ganancia_usd": round(ganancia_usd, 4) if ganancia_usd is not None else None,
                "ganancia_pct": round(ganancia_pct, 2) if ganancia_pct is not None else None,
                "realizada_bs": round(ganancia_realizada_bs, 2),
                "realizada_usd": round(ganancia_realizada_usd, 4),
                "n_compras": len(compras_sym),
                "n_ventas": len(ventas_sym),
            }
        )
    totales = {
        "costo_bs": round(sum(f["costo_total_bs"] for f in filas), 2),
        "costo_usd": round(sum(f["costo_total_usd"] for f in filas if f["costo_total_usd"]), 4),
        "valor_bs": round(sum(f["valor_bs"] for f in filas if f["valor_bs"]), 2),
        "valor_usd": round(sum(f["valor_usd"] for f in filas if f["valor_usd"]), 4),
        "ganancia_bs": round(sum(f["ganancia_bs"] for f in filas if f["ganancia_bs"]), 2),
        "ganancia_usd": round(sum(f["ganancia_usd"] for f in filas if f["ganancia_usd"]), 4),
        "realizada_bs": round(sum(f["realizada_bs"] for f in filas), 2),
        "realizada_usd": round(sum(f["realizada_usd"] for f in filas), 4),
    }
    return {
        "filas": filas,
        "totales": totales,
        "compras": [_enrich_op(c, by_sym, last) for c in compras],
        "ventas": [_enrich_op(v, by_sym, last) for v in ventas],
    }


def _evolucion(pf=None):
    if pf is None:
        pf = _read_portafolio()
    compras = pf.get("compras", [])
    ventas = pf.get("ventas", [])
    if not compras and not ventas:
        return []
    rows = _read_prices()
    fechas = sorted({r["fecha"] for r in rows})
    by_sym = {}
    for r in rows:
        by_sym.setdefault(r["simbolo"], {})[r["fecha"]] = r
    ops = {}
    for c in compras:
        ops.setdefault(c["ticker"], []).append((str(c.get("fecha", "")), float(c.get("cantidad", 0) or 0)))
    for v in ventas:
        ops.setdefault(v["ticker"], []).append((str(v.get("fecha", "")), -float(v.get("cantidad", 0) or 0)))
    tickers = sorted(ops)
    for t in tickers:
        ops[t].sort()
    idx = {t: 0 for t in tickers}
    qty = {t: 0.0 for t in tickers}
    last_px = {}
    out = []
    for fecha in fechas:
        for t in tickers:
            while idx[t] < len(ops[t]) and ops[t][idx[t]][0] <= fecha:
                qty[t] += ops[t][idx[t]][1]
                idx[t] += 1
            pr = by_sym.get(t, {}).get(fecha)
            if pr:
                last_px[t] = pr
        valor_bs = 0.0
        valor_usd = 0.0
        for t in tickers:
            q = qty[t]
            if q <= 0:
                continue
            pr = last_px.get(t)
            if not pr:
                continue
            pb = _fnum(pr.get("precio_bs"))
            pu = _fnum(pr.get("precio_usd"))
            if pb:
                valor_bs += q * pb
            if pu:
                valor_usd += q * pu
        if valor_bs or valor_usd:
            out.append({"fecha": fecha, "valor_bs": round(valor_bs, 2), "valor_usd": round(valor_usd, 4)})
    return out


def _run_update():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "monitor.py")],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    return proc


class Handler(BaseHTTPRequestHandler):
    server_version = "bvc-dashboard/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _send_html(self, name, status=200):
        path = ROOT / name
        if path.exists():
            body = path.read_bytes()
            self._send(status, "text/html; charset=utf-8", body)
        else:
            self._send(404, "text/plain", f"{name} no encontrado".encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send_html("dashboard.html")
        elif path == "/noticias":
            self._send_html("noticias.html")
        elif path == "/portafolio":
            self._send_html("portafolio.html")
        elif path == "/registros":
            self._send_html("registros.html")
        elif path == "/api/indices":
            self._send_json({"series": _read_indices()})
        elif path == "/api/dias":
            dias = sorted(p.stem for p in _diario_paths())
            self._send_json({"dias": dias})
        elif path == "/api/diario":
            fecha = query.get("fecha", [""])[0]
            data = _read_diario(fecha)
            if data is None:
                self._send_json({"error": "no hay datos"}, 404)
            else:
                self._send_json(data)
        elif path == "/api/simbolos":
            rows = _read_prices()
            simbolos = []
            seen = set()
            for r in rows:
                if r["simbolo"] not in seen:
                    seen.add(r["simbolo"])
                    simbolos.append(r["simbolo"])
            self._send_json({"simbolos": sorted(simbolos)})
        elif path == "/api/precios":
            simbolo = query.get("simbolo", [""])[0].upper()
            rows = [r for r in _read_prices() if r["simbolo"] == simbolo]
            if not rows:
                self._send_json({"error": "simbolo no encontrado"}, 404)
            else:
                self._send_json({"simbolo": simbolo, "serie": rows})
        elif path == "/api/simbolo_detalle":
            simbolo = query.get("simbolo", [""])[0].upper()
            force = query.get("force", [""])[0] == "1"
            info = _simbolo_info(simbolo, force=force)
            if info is None:
                self._send_json({"error": "sin datos"}, 404)
            else:
                self._send_json(info)
        elif path == "/api/capitalizacion":
            self._send_json({"simbolos": _capitalizacion()})
        elif path == "/api/noticias":
            self._send_json({"noticias": _noticias()})
        elif path == "/api/portafolio":
            self._send_json(_valoracion())
        elif path == "/api/evolucion":
            self._send_json({"serie": _evolucion()})
        elif path == "/api/estado":
            last, _ = _prices_flat()
            fecha = ""
            if PRICES_CSV.exists():
                with open(PRICES_CSV, newline="", encoding="utf-8") as fh:
                    fecha = list(csv.DictReader(fh))[-1]["fecha"]
            self._send_json(
                {
                    "ultima_fecha": fecha,
                    "dias": len(_diario_paths()),
                    "simbolos": len(last),
                    "noticias": len(_noticias()),
                    "precios_mtime": PRICES_CSV.stat().st_mtime if PRICES_CSV.exists() else 0,
                }
            )
        elif path == "/api/resumen":
            dias = sorted(p.stem for p in _diario_paths())
            fecha = dias[-1] if dias else None
            if not fecha:
                self._send_json({"error": "sin datos"}, 404)
            else:
                self._send_json({"fecha": fecha, "diario": _read_diario(fecha)})
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        from urllib.parse import urlparse

        path = urlparse(self.path).path
        if path == "/api/actualizar":
            try:
                proc = _run_update()
                out = (proc.stdout or "")[-2000:]
                err = (proc.stderr or "")[-2000:]
                ok = proc.returncode == 0
                self._send_json({"ok": ok, "output": out, "error": err})
            except subprocess.TimeoutExpired:
                self._send_json({"ok": False, "error": "La actualizacion tardo demasiado (300s)"}, 500)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
        elif path == "/api/portafolio":
            body = self._read_body()
            action = body.get("action")
            pf = _read_portafolio()
            if action == "add_compra":
                ticker = str(body.get("ticker", "")).upper()
                cantidad = float(body.get("cantidad", 0) or 0)
                precio = float(body.get("precio_bs", 0) or 0)
                if not ticker or cantidad <= 0 or precio <= 0:
                    self._send_json({"error": "datos invalidos"}, 400)
                    return
                compras = pf.setdefault("compras", [])
                nid = max((c.get("id", 0) for c in compras), default=0) + 1
                compras.append(
                    {
                        "id": nid,
                        "ticker": ticker,
                        "fecha": str(body.get("fecha", "")),
                        "cantidad": cantidad,
                        "precio_bs": precio,
                        "comision_bs": float(body.get("comision_bs", 0) or 0),
                        "nota": str(body.get("nota", "")),
                    }
                )
                _write_portafolio(pf)
                self._send_json({"ok": True, **{k: v for k, v in _valoracion().items()}})
            elif action == "del_compra":
                cid = int(body.get("id", 0))
                compras = pf.setdefault("compras", [])
                pf["compras"] = [c for c in compras if c.get("id") != cid]
                _write_portafolio(pf)
                self._send_json({"ok": True, **{k: v for k, v in _valoracion().items()}})
            elif action == "add_venta":
                ticker = str(body.get("ticker", "")).upper()
                cantidad = float(body.get("cantidad", 0) or 0)
                precio = float(body.get("precio_bs", 0) or 0)
                if not ticker or cantidad <= 0 or precio <= 0:
                    self._send_json({"error": "datos invalidos"}, 400)
                    return
                ventas = pf.setdefault("ventas", [])
                nid = max((v.get("id", 0) for v in ventas), default=0) + 1
                ventas.append(
                    {
                        "id": nid,
                        "ticker": ticker,
                        "fecha": str(body.get("fecha", "")),
                        "cantidad": cantidad,
                        "precio_bs": precio,
                        "comision_bs": float(body.get("comision_bs", 0) or 0),
                        "nota": str(body.get("nota", "")),
                    }
                )
                _write_portafolio(pf)
                self._send_json({"ok": True, **{k: v for k, v in _valoracion().items()}})
            elif action == "del_venta":
                vid = int(body.get("id", 0))
                ventas = pf.setdefault("ventas", [])
                pf["ventas"] = [v for v in ventas if v.get("id") != vid]
                _write_portafolio(pf)
                self._send_json({"ok": True, **{k: v for k, v in _valoracion().items()}})
            else:
                self._send_json({"error": "accion desconocida"}, 400)
        else:
            self._send(404, "text/plain", b"not found")


def main(port=8000):
    if not INDICES_CSV.exists() and not any(DIARIOS_DIR.glob("*.json")):
        print("No hay datos descargados todavia. Ejecuta primero: python downloader.py")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Dashboard disponible en http://127.0.0.1:{port}")
    print(f"  /           - Inicio (indices, ticker, cotizaciones)")
    print(f"  /noticias   - Notas de los diarios")
    print(f"  /portafolio - Resumen del portafolio (evolucion)")
    print(f"  /registros  - Registro de compras/ventas")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dashboard local del Diario de la Bolsa")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    sys.exit(main(port=args.port))
