import os
import secrets
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import db
import dashboard as core

ROOT = Path(__file__).resolve().parent


def _secret_key():
    """Clave de sesion persistente en data/.secret_key para no invalidar sesiones al reiniciar."""
    path = ROOT / "data" / ".secret_key"
    try:
        if path.exists():
            return path.read_text().strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        path.write_text(key)
        return key
    except OSError:
        return secrets.token_hex(32)


app = Flask(__name__)
app.config["SECRET_KEY"] = _secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True

# --- Config Google OAuth (se habilita cuando la app este en un VPS con dominio) ---
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")
GOOGLE_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "no autorizado"}), 401
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def _current_user():
    uid = session.get("user_id")
    return db.get_user_by_id(uid) if uid else None


# ============================ AUTH ============================

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if "user_id" in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nombre = request.form.get("nombre", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        error = None
        if not email or "@" not in email:
            error = "Correo invalido."
        elif len(password) < 6:
            error = "La contrasena debe tener al menos 6 caracteres."
        elif password != confirm:
            error = "Las contrasenas no coinciden."
        elif db.get_user_by_email(email):
            error = "Ya existe un usuario con ese correo. Inicia sesion."
        else:
            user_id = db.create_user(email, nombre or email.split("@")[0], password)
            if user_id is None:
                error = "No se pudo crear el usuario."
            else:
                session["user_id"] = user_id
                return redirect(url_for("index"))
        return render_template("registro.html", error=error,
                               email=email, nombre=nombre,
                               google_enabled=GOOGLE_ENABLED)
    return render_template("registro.html", google_enabled=GOOGLE_ENABLED)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    next_path = request.args.get("next") or request.form.get("next") or url_for("index")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.get_user_by_email(email)
        if user and db.check_password(user, password):
            session["user_id"] = user["id"]
            session["nombre"] = user["nombre"]
            return redirect(next_path)
        return render_template("login.html", error="Correo o contrasena incorrectos.",
                               email=email, next=next_path, google_enabled=GOOGLE_ENABLED)
    return render_template("login.html", next=next_path, google_enabled=GOOGLE_ENABLED)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================ PAGINAS ============================

@app.route("/")
@login_required
def index():
    return _send_html("dashboard.html")


@app.route("/noticias")
@login_required
def noticias():
    return _send_html("noticias.html")


@app.route("/portafolio")
@login_required
def portafolio():
    return _send_html("portafolio.html")


@app.route("/registros")
@login_required
def registros():
    return _send_html("registros.html")


@app.route("/cuenta", methods=["GET", "POST"])
@login_required
def cuenta():
    uid = session["user_id"]
    user = db.get_user_by_id(uid)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "perfil":
            db.update_user(
                uid,
                nombre=request.form.get("nombre", ""),
                casa_cambio=request.form.get("casa_cambio", ""),
                comision_pct=request.form.get("comision_pct"),
                iva_pct=request.form.get("iva_pct"),
                der_reg_umbral=request.form.get("der_reg_umbral"),
                der_reg_fijo=request.form.get("der_reg_fijo"),
                der_reg_pct=request.form.get("der_reg_pct"),
            )
            session["nombre"] = request.form.get("nombre", "").strip()
            user = db.get_user_by_id(uid)
            return render_template("cuenta.html", u=user, ok="Perfil actualizado.",
                                   casas=db.CASAS_DE_BOLSA)
        if action == "password":
            actual = request.form.get("pw_actual", "")
            nueva = request.form.get("pw_nueva", "")
            confirm = request.form.get("pw_confirm", "")
            if not db.check_password(user, actual):
                return render_template("cuenta.html", u=user, casas=db.CASAS_DE_BOLSA,
                                       error_pw="La contrasena actual no es correcta.")
            if len(nueva) < 6:
                return render_template("cuenta.html", u=user, casas=db.CASAS_DE_BOLSA,
                                       error_pw="La nueva contrasena debe tener al menos 6 caracteres.")
            if nueva != confirm:
                return render_template("cuenta.html", u=user, casas=db.CASAS_DE_BOLSA,
                                       error_pw="Las contrasenas nuevas no coinciden.")
            db.update_password(uid, nueva)
            return render_template("cuenta.html", u=user, casas=db.CASAS_DE_BOLSA,
                                   ok_pw="Contrasena actualizada.")
    return render_template("cuenta.html", u=user, casas=db.CASAS_DE_BOLSA)


def _send_html(name):
    path = ROOT / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "no encontrado", 404


# ============================ APIS PUBLICAS (mercado) ============================

@app.route("/api/estado")
@login_required
def api_estado():
    last, _ = core._prices_flat()
    fecha = ""
    if core.PRICES_CSV.exists():
        import csv

        with open(core.PRICES_CSV, newline="", encoding="utf-8") as fh:
            fecha = list(csv.DictReader(fh))[-1]["fecha"]
    return jsonify({
        "ultima_fecha": fecha,
        "dias": len(core._diario_paths()),
        "simbolos": len(last),
        "noticias": len(core._noticias()),
        "precios_mtime": core.PRICES_CSV.stat().st_mtime if core.PRICES_CSV.exists() else 0,
        "usuario": session.get("nombre"),
    })


@app.route("/api/indices")
@login_required
def api_indices():
    return jsonify({"series": core._read_indices()})


@app.route("/api/dias")
@login_required
def api_dias():
    dias = sorted(p.stem for p in core._diario_paths())
    return jsonify({"dias": dias})


@app.route("/api/diario")
@login_required
def api_diario():
    fecha = request.args.get("fecha", "")
    data = core._read_diario(fecha)
    if data is None:
        return jsonify({"error": "no hay datos"}), 404
    return jsonify(data)


@app.route("/api/simbolos")
@login_required
def api_simbolos():
    rows = core._read_prices()
    seen = set()
    simbolos = []
    for r in rows:
        if r["simbolo"] not in seen:
            seen.add(r["simbolo"])
            simbolos.append(r["simbolo"])
    nombres = core._simbolo_nombres()
    return jsonify({
        "simbolos": sorted(
            [{"simbolo": s, "nombre": nombres.get(s, "")} for s in simbolos],
            key=lambda x: x["simbolo"],
        )
    })


@app.route("/api/precios")
@login_required
def api_precios():
    simbolo = request.args.get("simbolo", "").upper()
    rows = [r for r in core._read_prices() if r["simbolo"] == simbolo]
    if not rows:
        return jsonify({"error": "simbolo no encontrado"}), 404
    return jsonify({"simbolo": simbolo, "serie": rows})


@app.route("/api/simbolo_detalle")
@login_required
def api_simbolo_detalle():
    simbolo = request.args.get("simbolo", "").upper()
    force = request.args.get("force", "") == "1"
    info = core._simbolo_info(simbolo, force=force)
    if info is None:
        return jsonify({"error": "sin datos"}), 404
    return jsonify(info)


@app.route("/api/capitalizacion")
@login_required
def api_capitalizacion():
    return jsonify({"simbolos": core._capitalizacion()})


@app.route("/api/noticias")
@login_required
def api_noticias():
    return jsonify({"noticias": core._noticias()})


@app.route("/api/resumen")
@login_required
def api_resumen():
    dias = sorted(p.stem for p in core._diario_paths())
    fecha = dias[-1] if dias else None
    if not fecha:
        return jsonify({"error": "sin datos"}), 404
    return jsonify({"fecha": fecha, "diario": core._read_diario(fecha)})


@app.route("/api/actualizar", methods=["POST"])
@login_required
def api_actualizar():
    try:
        proc = core._run_update()
        out = (proc.stdout or "")[-2000:]
        err = (proc.stderr or "")[-2000:]
        ok = proc.returncode == 0
        return jsonify({"ok": ok, "output": out, "error": err})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ============================ APIS DE CARTERA (por usuario) ============================

@app.route("/api/perfil")
@login_required
def api_perfil():
    uid = session["user_id"]
    user = db.get_user_by_id(uid)
    campos = ["casa_cambio", "comision_pct", "iva_pct",
              "der_reg_umbral", "der_reg_fijo", "der_reg_pct"]
    return jsonify({k: user.get(k) for k in campos})


@app.route("/api/portafolio")
@login_required
def api_mi_portafolio():
    pf = db.get_portafolio(session["user_id"])
    return jsonify(core._valoracion(pf))


@app.route("/api/evolucion")
@login_required
def api_mi_evolucion():
    pf = db.get_portafolio(session["user_id"])
    return jsonify({"serie": core._evolucion(pf)})


@app.route("/api/portafolio", methods=["POST"])
@login_required
def api_portafolio_post():
    uid = session["user_id"]
    body = request.get_json(silent=True) or {}
    action = body.get("action")

    def _monto_op(cant, precio, comision):
        if not cant or cant <= 0 or not precio or precio <= 0:
            return None
        cant_f = float(cant)
        precio_f = float(precio)
        if comision in (None, "", 0, "0"):
            comision_f = db.calcular_comision(db.get_user_by_id(uid), cant_f, precio_f)
        else:
            comision_f = float(comision or 0)
        return cant_f, precio_f, comision_f

    if action == "add_compra":
        m = _monto_op(body.get("cantidad"), body.get("precio_bs"), body.get("comision_bs"))
        if not m:
            return jsonify({"error": "datos invalidos"}), 400
        ticker = str(body.get("ticker", "")).upper()
        if not ticker:
            return jsonify({"error": "datos invalidos"}), 400
        db.add_compra(uid, ticker, body.get("fecha", ""), m[0], m[1], m[2], str(body.get("nota", "")))
        return jsonify({"ok": True, **core._valoracion(db.get_portafolio(uid))})

    if action == "del_compra":
        db.del_compra(uid, int(body.get("id", 0)))
        return jsonify({"ok": True, **core._valoracion(db.get_portafolio(uid))})

    if action == "add_venta":
        m = _monto_op(body.get("cantidad"), body.get("precio_bs"), body.get("comision_bs"))
        if not m:
            return jsonify({"error": "datos invalidos"}), 400
        ticker = str(body.get("ticker", "")).upper()
        if not ticker:
            return jsonify({"error": "datos invalidos"}), 400
        db.add_venta(uid, ticker, body.get("fecha", ""), m[0], m[1], m[2], str(body.get("nota", "")))
        return jsonify({"ok": True, **core._valoracion(db.get_portafolio(uid))})

    if action == "del_venta":
        db.del_venta(uid, int(body.get("id", 0)))
        return jsonify({"ok": True, **core._valoracion(db.get_portafolio(uid))})

    return jsonify({"error": "accion desconocida"}), 400


if __name__ == "__main__":
    db.init_db()
    print("App BVC Monitor multiusuario")
    print("  registro: http://127.0.0.1:8000/registro")
    print("  login:    http://127.0.0.1:8000/login")
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=True)
