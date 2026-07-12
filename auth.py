"""
Rutas de autenticacion: registro, login, invitado y logout.
"""

import uuid
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user

from models import db, Usuario, crear_categorias_default, eliminar_datos_invitado

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return render_template("registro.html")

    # POST: procesar el formulario
    nombre = request.form.get("nombre", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    # Validaciones basicas
    if not nombre or not email or not password:
        flash("Todos los campos son obligatorios.")
        return redirect(url_for("auth.registro"))

    if Usuario.query.filter_by(email=email).first():
        flash("Ya existe una cuenta con ese email.")
        return redirect(url_for("auth.registro"))

    nuevo_usuario = Usuario(nombre=nombre, email=email, es_invitado=False)
    nuevo_usuario.set_password(password)
    db.session.add(nuevo_usuario)
    db.session.commit()

    # Le creamos sus categorias default apenas se registra
    crear_categorias_default(nuevo_usuario)

    login_user(nuevo_usuario)
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    usuario = Usuario.query.filter_by(email=email, es_invitado=False).first()

    if usuario is None or not usuario.check_password(password):
        flash("Email o contrasena incorrectos.")
        return redirect(url_for("auth.login"))

    login_user(usuario)
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/invitado")
def invitado():
    """
    Crea un usuario temporal de tipo invitado y lo loguea directo,
    sin pasar por formulario. Sus datos se guardan en la base de datos
    igual que un usuario normal pero quedan marcados como es_invitado=True
    """
    identificador = uuid.uuid4().hex[:8]  # ej: "a3f9c1b2", solo para diferenciarlos en el nombre
    invitado = Usuario(
        nombre=f"Invitado-{identificador}",
        email=None,
        es_invitado=True,
    )
    db.session.add(invitado)
    db.session.commit()

    crear_categorias_default(invitado)

    session.permanent = True
    login_user(invitado)
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/invitado/eliminar-datos", methods=["POST"])
@login_required
def eliminar_datos_invitado_ruta():
    """
    Le permite a un invitado borrar sus propios datos una accion
    explicita del usuario disponible solo mientras esta logueado 
    """
    if not current_user.es_invitado:
        flash("Esta accion es solo para cuentas de invitado.")
        return redirect(url_for("dashboard.index"))

    usuario_id = current_user.id
    logout_user()  # primero cerramos la sesion, porque el usuario esta por dejar de existir
    eliminar_datos_invitado(usuario_id)

    flash("Tus datos de invitado fueron eliminados por completo.")
    return redirect(url_for("landing"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("landing"))
