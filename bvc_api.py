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


def download_dat(date_yyyymmdd, dest_path, session=None):
    s = session or _session()
    r = s.get(DAT_URL, params={"type": "dat", "fecha": date_yyyymmdd}, timeout=120)
    r.raise_for_status()
    with open(dest_path, "wb") as fh:
        fh.write(r.content)
    return len(r.content)
