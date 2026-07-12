"""
Blueprint de perfil: ver datos de cuenta, cambiar nombre, email, contraseña.
"""

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from models import db, Usuario

perfil_bp = Blueprint("perfil", __name__, url_prefix="/perfil")


@perfil_bp.route("/")
@login_required
def index():
    return render_template("perfil.html")


@perfil_bp.route("/nombre", methods=["POST"])
@login_required
def cambiar_nombre():
    nombre = request.form.get("nombre", "").strip()
    if not nombre:
        flash("El nombre no puede estar vacío.")
        return redirect(url_for("perfil.index"))

    current_user.nombre = nombre
    db.session.commit()
    flash("Nombre actualizado correctamente.")
    return redirect(url_for("perfil.index"))


@perfil_bp.route("/email", methods=["POST"])
@login_required
def cambiar_email():
    if current_user.es_invitado:
        flash("Los usuarios invitados no pueden cambiar su email.")
        return redirect(url_for("perfil.index"))

    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("El email no puede estar vacío.")
        return redirect(url_for("perfil.index"))

    existente = Usuario.query.filter_by(email=email).first()
    if existente and existente.id != current_user.id:
        flash("Ya existe una cuenta con ese email.")
        return redirect(url_for("perfil.index"))

    current_user.email = email
    db.session.commit()
    flash("Email actualizado correctamente.")
    return redirect(url_for("perfil.index"))


@perfil_bp.route("/password", methods=["POST"])
@login_required
def cambiar_password():
    if current_user.es_invitado:
        flash("Los usuarios invitados no pueden cambiar su contraseña.")
        return redirect(url_for("perfil.index"))

    actual = request.form.get("password_actual", "")
    nueva = request.form.get("password_nueva", "")
    confirmar = request.form.get("confirmar", "")

    if not current_user.check_password(actual):
        flash("La contraseña actual es incorrecta.")
        return redirect(url_for("perfil.index"))

    if len(nueva) < 8:
        flash("La nueva contraseña debe tener al menos 8 caracteres.")
        return redirect(url_for("perfil.index"))

    if nueva != confirmar:
        flash("Las contraseñas nuevas no coinciden.")
        return redirect(url_for("perfil.index"))

    current_user.set_password(nueva)
    db.session.commit()
    flash("Contraseña actualizada correctamente.")
    return redirect(url_for("perfil.index"))
