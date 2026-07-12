"""
Rutas de gestion de categorias: ver todas, crear, editar y eliminar.
"""

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user

from models import db, Categoria, crear_categoria_usuario, eliminar_categoria_usuario

categorias_bp = Blueprint("categorias", __name__)


@categorias_bp.route("/categorias")
@login_required
def index():
    categorias_gasto = (
        Categoria.query.filter_by(usuario_id=current_user.id, tipo="gasto")
        .order_by(Categoria.nombre).all()
    )
    categorias_ingreso = (
        Categoria.query.filter_by(usuario_id=current_user.id, tipo="ingreso")
        .order_by(Categoria.nombre).all()
    )
    return render_template(
        "categorias.html",
        categorias_gasto=categorias_gasto,
        categorias_ingreso=categorias_ingreso,
    )


@categorias_bp.route("/categorias/nueva", methods=["POST"])
@login_required
def nueva():
    nombre = request.form.get("nombre_categoria", "")
    tipo = request.form.get("tipo_categoria")

    categoria, error = crear_categoria_usuario(current_user.id, nombre, tipo)
    if error:
        flash(error)
    else:
        flash(f"Categoria '{categoria.nombre}' creada.")

    return redirect(url_for("categorias.index"))


@categorias_bp.route("/categorias/<int:categoria_id>/editar", methods=["POST"])
@login_required
def editar(categoria_id):
    """
    Renombrar una categoria existente
    """
    categoria = Categoria.query.filter_by(id=categoria_id, usuario_id=current_user.id).first()
    if categoria is None:
        flash("Esa categoria no existe o no te pertenece.")
        return redirect(url_for("categorias.index"))

    nuevo_nombre = request.form.get("nuevo_nombre", "").strip()
    if not nuevo_nombre:
        flash("El nombre no puede estar vacio.")
        return redirect(url_for("categorias.index"))

    ya_existe = Categoria.query.filter_by(
        usuario_id=current_user.id, nombre=nuevo_nombre, tipo=categoria.tipo
    ).first()
    if ya_existe and ya_existe.id != categoria.id:
        flash(f"Ya tenes otra categoria de {categoria.tipo} con ese nombre.")
        return redirect(url_for("categorias.index"))

    categoria.nombre = nuevo_nombre
    db.session.commit()
    flash("Categoria actualizada.")
    return redirect(url_for("categorias.index"))


@categorias_bp.route("/categorias/<int:categoria_id>/eliminar", methods=["POST"])
@login_required
def eliminar(categoria_id):
    exito, error = eliminar_categoria_usuario(current_user.id, categoria_id)
    if error:
        flash(error)
    else:
        flash("Categoria eliminada.")
    return redirect(url_for("categorias.index"))
