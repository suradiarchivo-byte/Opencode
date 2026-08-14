import sqlite3
from datetime import datetime
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "app.db"

# Casas de bolsa autorizadas ante la BCV / SUDEBAN (sociedades de corretaje)
CASAS_DE_BOLSA = [
    "Acciones de Venezuela (Acvensa)",
    "Actinver Casa de Bolsa",
    "Bancaribe Casa de Bolsa",
    "Banesco Casa de Bolsa",
    "BBO Casa de Bolsa",
    "Banex Casa de Bolsa",
    "Caja Caracas Casa de Bolsa",
    "Casa de Bolsa de Caracas",
    "Casa de Bolsa Mercantil",
    "Citimerca Casa de Bolsa",
    "Corp Banca Casa de Bolsa",
    "Fivenca Casa de Bolsa",
    "Global Markets Casa de Bolsa",
    "Humboldt Casa de Bolsa",
    "IBC Securities",
    "Interacciones Casa de Bolsa",
    "Intervalores Casa de Bolsa",
    "Inversur",
    "La Primera Casa de Bolsa",
    "Mercantil Valores",
    "Multinvest Casa de Bolsa",
    "Provincial Casa de Bolsa",
    "R&H Casa de Bolsa",
    "Solid Capital",
    "Valores Santander Casa de Bolsa",
    "Valores Unicasa",
    "Otro / no listado",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL DEFAULT '',
    casa_cambio TEXT NOT NULL DEFAULT '',
    comision_pct REAL NOT NULL DEFAULT 0,
    iva_pct REAL NOT NULL DEFAULT 0,
    der_reg_umbral REAL NOT NULL DEFAULT 0,
    der_reg_fijo REAL NOT NULL DEFAULT 0,
    der_reg_pct REAL NOT NULL DEFAULT 0,
    password_hash TEXT,
    auth_provider TEXT NOT NULL DEFAULT 'password',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ticker TEXT NOT NULL,
    fecha TEXT NOT NULL DEFAULT '',
    cantidad REAL NOT NULL DEFAULT 0,
    precio_bs REAL NOT NULL DEFAULT 0,
    comision_bs REAL NOT NULL DEFAULT 0,
    nota TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    ticker TEXT NOT NULL,
    fecha TEXT NOT NULL DEFAULT '',
    cantidad REAL NOT NULL DEFAULT 0,
    precio_bs REAL NOT NULL DEFAULT 0,
    comision_bs REAL NOT NULL DEFAULT 0,
    nota TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_compras_user ON compras(user_id);
CREATE INDEX IF NOT EXISTS idx_ventas_user ON ventas(user_id);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    for col, ddl in [
        ("casa_cambio", "ALTER TABLE users ADD COLUMN casa_cambio TEXT NOT NULL DEFAULT ''"),
        ("comision_pct", "ALTER TABLE users ADD COLUMN comision_pct REAL NOT NULL DEFAULT 0"),
        ("iva_pct", "ALTER TABLE users ADD COLUMN iva_pct REAL NOT NULL DEFAULT 0"),
        ("der_reg_umbral", "ALTER TABLE users ADD COLUMN der_reg_umbral REAL NOT NULL DEFAULT 0"),
        ("der_reg_fijo", "ALTER TABLE users ADD COLUMN der_reg_fijo REAL NOT NULL DEFAULT 0"),
        ("der_reg_pct", "ALTER TABLE users ADD COLUMN der_reg_pct REAL NOT NULL DEFAULT 0"),
    ]:
        if col not in cols:
            conn.execute(ddl)


def create_user(email, nombre, password=None, auth_provider="password"):
    conn = get_conn()
    try:
        phash = generate_password_hash(password) if password else None
        cur = conn.execute(
            "INSERT INTO users (email, nombre, password_hash, auth_provider, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (email.strip().lower(), nombre.strip(), phash, auth_provider,
             datetime.utcnow().isoformat(timespec="seconds")),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def check_password(user, password):
    if not user or not user.get("password_hash"):
        return False
    return check_password_hash(user["password_hash"], password)


def calcular_comision(user, cantidad, precio_bs):
    """Calcula la comision total segun las tarifas configuradas por el usuario.

    - comision: % del monto de la operacion (ej: 5%)
    - IVA: % sobre la comision (ej: 16%)
    - Derecho de registro: si monto <= umbral, monto fijo; si no, % del monto
    """
    monto = float(cantidad or 0) * float(precio_bs or 0)
    if monto <= 0:
        return 0.0
    comision = monto * (float(user.get("comision_pct") or 0) / 100)
    iva = comision * (float(user.get("iva_pct") or 0) / 100)
    umbral = float(user.get("der_reg_umbral") or 0)
    der_fijo = float(user.get("der_reg_fijo") or 0)
    der_pct = float(user.get("der_reg_pct") or 0)
    if umbral > 0:
        if monto <= umbral:
            derecho = der_fijo
        else:
            derecho = monto * (der_pct / 100)
    else:
        derecho = der_fijo if der_fijo else 0.0
    return round(comision + iva + derecho, 2)


def update_user(user_id, nombre=None, casa_cambio=None,
                comision_pct=None, iva_pct=None,
                der_reg_umbral=None, der_reg_fijo=None, der_reg_pct=None):
    conn = get_conn()
    try:
        sets, vals = [], []
        if nombre is not None:
            sets.append("nombre = ?")
            vals.append(nombre.strip())
        if casa_cambio is not None:
            sets.append("casa_cambio = ?")
            vals.append(casa_cambio.strip())
        for col, val in [
            ("comision_pct", comision_pct),
            ("iva_pct", iva_pct),
            ("der_reg_umbral", der_reg_umbral),
            ("der_reg_fijo", der_reg_fijo),
            ("der_reg_pct", der_reg_pct),
        ]:
            if val is not None:
                sets.append(f"{col} = ?")
                vals.append(float(val))
        if not sets:
            return False
        vals.append(user_id)
        cur = conn.execute(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ?", vals
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_password(user_id, password):
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _row_to_op(row):
    return {
        "id": row["id"],
        "ticker": row["ticker"],
        "fecha": row["fecha"],
        "cantidad": row["cantidad"],
        "precio_bs": row["precio_bs"],
        "comision_bs": row["comision_bs"],
        "nota": row["nota"],
    }


def get_portafolio(user_id):
    conn = get_conn()
    try:
        compras = conn.execute(
            "SELECT * FROM compras WHERE user_id = ? ORDER BY fecha, id", (user_id,)
        ).fetchall()
        ventas = conn.execute(
            "SELECT * FROM ventas WHERE user_id = ? ORDER BY fecha, id", (user_id,)
        ).fetchall()
        return {
            "compras": [_row_to_op(c) for c in compras],
            "ventas": [_row_to_op(v) for v in ventas],
        }
    finally:
        conn.close()


def add_compra(user_id, ticker, fecha, cantidad, precio_bs, comision_bs=0, nota=""):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO compras (user_id, ticker, fecha, cantidad, precio_bs, comision_bs, nota) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, ticker.upper(), str(fecha), float(cantidad), float(precio_bs),
             float(comision_bs), str(nota)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_venta(user_id, ticker, fecha, cantidad, precio_bs, comision_bs=0, nota=""):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO ventas (user_id, ticker, fecha, cantidad, precio_bs, comision_bs, nota) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, ticker.upper(), str(fecha), float(cantidad), float(precio_bs),
             float(comision_bs), str(nota)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def del_compra(user_id, op_id):
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM compras WHERE id = ? AND user_id = ?", (op_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def del_venta(user_id, op_id):
    conn = get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM ventas WHERE id = ? AND user_id = ?", (op_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def migrate_from_json(json_path):
    """Importa una cartera previa (portafolio.json) para un usuario."""
    import json

    path = Path(json_path)
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return False
    compras = data.get("compras", [])
    ventas = data.get("ventas", [])
    if not compras and not ventas:
        return False
    return compras, ventas
