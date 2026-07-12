"""
Rutas de autenticacion: registro, login, invitado, logout, y recuperación de contraseña.
"""

import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message

from models import db, Usuario, TokenRecuperacion, crear_categorias_default, eliminar_datos_invitado
from extensions import limiter, mail

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/registro", methods=["GET", "POST"])
@limiter.limit("20/minute")
def registro():
    if request.method == "GET":
        return render_template("registro.html")

    nombre = request.form.get("nombre", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not nombre or not email or not password:
        flash("Todos los campos son obligatorios.")
        return redirect(url_for("auth.registro"))

    if len(password) < 8:
        flash("La contraseña debe tener al menos 8 caracteres.")
        return redirect(url_for("auth.registro"))

    if Usuario.query.filter_by(email=email).first():
        flash("Ya existe una cuenta con ese email.")
        return redirect(url_for("auth.registro"))

    nuevo_usuario = Usuario(nombre=nombre, email=email, es_invitado=False)
    nuevo_usuario.set_password(password)
    db.session.add(nuevo_usuario)
    db.session.commit()

    crear_categorias_default(nuevo_usuario)
    login_user(nuevo_usuario)
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute")
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    usuario = Usuario.query.filter_by(email=email, es_invitado=False).first()

    if usuario is None or not usuario.check_password(password):
        flash("Email o contraseña incorrectos.")
        return redirect(url_for("auth.login"))

    login_user(usuario)
    return redirect(url_for("dashboard.index"))


@auth_bp.route("/invitado")
def invitado():
    identificador = uuid.uuid4().hex[:8]
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
    if not current_user.es_invitado:
        flash("Esta acción es solo para cuentas de invitado.")
        return redirect(url_for("dashboard.index"))

    usuario_id = current_user.id
    logout_user()
    eliminar_datos_invitado(usuario_id)
    flash("Tus datos de invitado fueron eliminados por completo.")
    return redirect(url_for("landing"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("landing"))


# ─── Recuperación de contraseña ───────────────────────────────────────────────

@auth_bp.route("/recuperar-password", methods=["GET", "POST"])
@limiter.limit("5/minute")
def recuperar_password():
    if request.method == "GET":
        return render_template("recuperar_password.html")

    email = request.form.get("email", "").strip().lower()
    usuario = Usuario.query.filter_by(email=email, es_invitado=False).first()

    # Siempre mostramos el mismo mensaje para no revelar si el email existe
    MENSAJE = "Si ese email está registrado, te enviamos un enlace para restablecer tu contraseña."

    if usuario is None:
        flash(MENSAJE)
        return redirect(url_for("auth.login"))

    token_obj = TokenRecuperacion.generar(usuario.id)
    db.session.commit()

    enlace = url_for("auth.recuperar_password_token", token=token_obj.token, _external=True)

    mail_configurado = bool(os.environ.get("MAIL_SERVER"))

    if mail_configurado:
        try:
            msg = Message(
                subject="Recuperación de contraseña — GastoFlow",
                recipients=[usuario.email],
                html=f"""
                <p>Hola {usuario.nombre},</p>
                <p>Hacé clic en el siguiente enlace para restablecer tu contraseña.
                   El enlace es válido por <strong>1 hora</strong>.</p>
                <p><a href="{enlace}">{enlace}</a></p>
                <p>Si no pediste este cambio, ignorá este email.</p>
                """,
            )
            mail.send(msg)
        except Exception:
            # Si el mail falla, mostrar el enlace igual (dev-friendly)
            flash(f"No se pudo enviar el email. Enlace de recuperación: {enlace}")
            return redirect(url_for("auth.login"))
    else:
        # Modo desarrollo: mostrar el enlace directamente
        flash(f"(Dev) Enlace de recuperación: {enlace}")
        return redirect(url_for("auth.recuperar_password_token", token=token_obj.token))

    flash(MENSAJE)
    return redirect(url_for("auth.login"))


@auth_bp.route("/recuperar-password/<token>", methods=["GET", "POST"])
def recuperar_password_token(token):
    token_obj = TokenRecuperacion.query.filter_by(token=token, usado=False).first()

    if token_obj is None or token_obj.expirado:
        flash("El enlace de recuperación no es válido o ya expiró.")
        return redirect(url_for("auth.recuperar_password"))

    if request.method == "GET":
        return render_template("recuperar_password_token.html", token=token)

    nueva = request.form.get("password", "")
    confirmar = request.form.get("confirmar", "")

    if len(nueva) < 8:
        flash("La nueva contraseña debe tener al menos 8 caracteres.")
        return redirect(url_for("auth.recuperar_password_token", token=token))

    if nueva != confirmar:
        flash("Las contraseñas no coinciden.")
        return redirect(url_for("auth.recuperar_password_token", token=token))

    token_obj.usuario.set_password(nueva)
    token_obj.usado = True
    db.session.commit()

    flash("¡Contraseña actualizada! Podés iniciar sesión ahora.")
    return redirect(url_for("auth.login"))
