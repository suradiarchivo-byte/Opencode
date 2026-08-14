import json
import time

import requests

AJAX_URL = "https://www.bolsadecaracas.com/wp-admin/admin-ajax.php"
BASE_URL = "https://www.bolsadecaracas.com"
DAT_URL = BASE_URL + "/descargar-diario-bolsa/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) bvc-monitor/1.0"
RETRY = 3
RETRY_DELAY = 2.0


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def get_dates(session=None):
    s = session or _session()
    r = s.get(AJAX_URL, params={"action": "getUltimosDiarios"}, timeout=60)
    r.raise_for_status()
    return sorted(json.loads(r.text))


def get_diario(date_yyyymmdd, session=None):
    s = session or _session()
    for attempt in range(RETRY):
        try:
            r = s.get(
                AJAX_URL,
                params={"action": "getDiarioBolsa", "data": date_yyyymmdd},
                timeout=60,
            )
            r.raise_for_status()
            return json.loads(r.text)
        except (requests.RequestException, ValueError):
            if attempt == RETRY - 1:
                raise
            time.sleep(RETRY_DELAY * (attempt + 1))


def get_simbolo_detalle(simbolo, session=None):
    """Info de un simbolo desde la BVC: acciones en circulacion, capitalizacion, beneficios/ajustes."""
    s = session or _session()
    for attempt in range(RETRY):
        try:
            r = s.post(
                AJAX_URL,
                data={"action": "getSimbolosDetalle", "simbolo": simbolo, "tipo": "rv"},
                timeout=60,
            )
            r.raise_for_status()
            payload = r.json()
            resp = payload.get("response") or {}
            enc = (resp.get("cur_encab_simb_rv") or [{}])[0]
            cap = (resp.get("cur_cap_simb_rv") or [{}])[0]
            pre = (resp.get("cur_precio_var_rv") or [{}])[0]
            vtr = (resp.get("cur_vol_trx_rv") or [{}])[0]
            vax = (resp.get("cur_vol_x_ano_rv") or [{}])[0]
            lib = (resp.get("cur_con_lib_ord_rv") or [{}])[0]
            sesion = resp.get("cur_grf_sesion_rv") or []
            hist_p = resp.get("cur_grf_anual_pre_rv") or []
            hist_v = resp.get("cur_grf_anual_vol_rv") or []
            return {
                "simbolo": simbolo,
                "descripcion": enc.get("DESC_EMP") or enc.get("DESC_SIMB"),
                "isin": enc.get("COD_ISIN"),
                "estado": enc.get("ESTATUS"),
                "moneda": enc.get("MONEDA"),
                "acc_circ": enc.get("ACC_CIRC"),
                "capitali_bs": cap.get("CAPITALI_BS"),
                "capitali_us": cap.get("CAPITALI_US"),
                "precio": pre.get("PRECIO_ULT"),
                "apertura": pre.get("PRECIO_APERT"),
                "precio_max": pre.get("PRECIO_MAX"),
                "precio_med": pre.get("PRECIO_MED"),
                "precio_min": pre.get("PRECIO_MIN"),
                "var_abs": pre.get("ULT_VAR_ABS"),
                "var_rel": pre.get("ULT_VAR_REL"),
                "max_ano": pre.get("PRECIO_MAX_ANO"),
                "min_ano": pre.get("PRECIO_MIN_ANO"),
                "volumen_dia": vtr.get("VOLUMEN"),
                "nops_dia": vtr.get("TOT_OP_NEGOC"),
                "monto_dia": vtr.get("MONTO_EFECTIVO"),
                "volumen_ano": vax.get("TOT_ACC_NEGOC"),
                "nops_ano": vax.get("TOT_OP_NEGOC"),
                "monto_ano": vax.get("TOT_MONTO_NEGOC"),
                "libro_ordenes": lib,
                "grf_sesion": sesion,
                "grf_anual_pre": hist_p,
                "grf_anual_vol": hist_v,
                "beneficios": resp.get("cur_ult_benef_otr_rv") or [],
                "suscripciones": resp.get("cur_ult_beneficios_rv") or [],
            }
        except (requests.RequestException, ValueError):
            if attempt == RETRY - 1:
                raise
            time.sleep(RETRY_DELAY * (attempt + 1))


def download_dat(date_yyyymmdd, dest_path, session=None):
    s = session or _session()
    r = s.get(DAT_URL, params={"type": "dat", "fecha": date_yyyymmdd}, timeout=120)
    r.raise_for_status()
    with open(dest_path, "wb") as fh:
        fh.write(r.content)
    return len(r.content)
