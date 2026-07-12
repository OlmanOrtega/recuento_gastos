"""
Blueprint de presupuestos: definir límites de gasto por categoría.
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user

from models import db, Categoria, Presupuesto, Transaccion
from dashboard import total_por_tipo, rango_del_mes

presupuestos_bp = Blueprint("presupuestos", __name__, url_prefix="/presupuestos")


def _presupuestos_con_progreso(usuario_id, anio, mes):
    """
    Devuelve lista de dicts con el presupuesto de cada categoría de gasto
    y cuánto se lleva gastado en el mes indicado.
    """
    presupuestos = (
        Presupuesto.query
        .join(Categoria, Categoria.id == Presupuesto.categoria_id)
        .filter(
            Presupuesto.usuario_id == usuario_id,
            Categoria.tipo == "gasto",
        )
        .all()
    )

    inicio, fin = rango_del_mes(anio, mes)
    resultado = []
    for p in presupuestos:
        gastado_raw = (
            db.session.query(db.func.sum(Transaccion.monto))
            .filter(
                Transaccion.usuario_id == usuario_id,
                Transaccion.categoria_id == p.categoria_id,
                Transaccion.tipo == "gasto",
                Transaccion.fecha >= inicio,
                Transaccion.fecha <= fin,
            )
            .scalar()
        )
        gastado = float(gastado_raw) if gastado_raw else 0.0
        limite = float(p.monto_limite)
        porcentaje = min((gastado / limite) * 100, 100) if limite > 0 else 0
        resultado.append({
            "presupuesto": p,
            "gastado": gastado,
            "limite": limite,
            "porcentaje": porcentaje,
            "excedido": gastado > limite,
        })

    return sorted(resultado, key=lambda x: x["porcentaje"], reverse=True)


@presupuestos_bp.route("/")
@login_required
def index():
    from datetime import date
    hoy = date.today()
    anio = request.args.get("anio", type=int, default=hoy.year)
    mes = request.args.get("mes", type=int, default=hoy.month)

    categorias_gasto = (
        Categoria.query
        .filter_by(usuario_id=current_user.id, tipo="gasto")
        .order_by(Categoria.nombre)
        .all()
    )
    progreso = _presupuestos_con_progreso(current_user.id, anio, mes)

    # IDs que ya tienen presupuesto (para ocultarlos del formulario de añadir)
    ids_con_presupuesto = {p["presupuesto"].categoria_id for p in progreso}
    categorias_sin_presupuesto = [c for c in categorias_gasto if c.id not in ids_con_presupuesto]

    return render_template(
        "presupuestos.html",
        progreso=progreso,
        categorias_sin_presupuesto=categorias_sin_presupuesto,
        anio=anio,
        mes=mes,
    )


@presupuestos_bp.route("/nuevo", methods=["POST"])
@login_required
def nuevo():
    categoria_id = request.form.get("categoria_id", type=int)
    monto_texto = request.form.get("monto_limite", "").strip()

    categoria = Categoria.query.filter_by(
        id=categoria_id, usuario_id=current_user.id, tipo="gasto"
    ).first()
    if categoria is None:
        flash("Categoría inválida.")
        return redirect(url_for("presupuestos.index"))

    try:
        monto = Decimal(monto_texto)
        if monto <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        flash("El monto debe ser un número mayor a cero.")
        return redirect(url_for("presupuestos.index"))

    existente = Presupuesto.query.filter_by(
        usuario_id=current_user.id, categoria_id=categoria_id
    ).first()
    if existente:
        existente.monto_limite = monto
        flash(f"Presupuesto de '{categoria.nombre}' actualizado.")
    else:
        db.session.add(Presupuesto(
            usuario_id=current_user.id,
            categoria_id=categoria_id,
            monto_limite=monto,
        ))
        flash(f"Presupuesto de '{categoria.nombre}' creado.")

    db.session.commit()
    return redirect(url_for("presupuestos.index"))


@presupuestos_bp.route("/<int:presupuesto_id>/eliminar", methods=["POST"])
@login_required
def eliminar(presupuesto_id):
    p = Presupuesto.query.filter_by(id=presupuesto_id, usuario_id=current_user.id).first()
    if p is None:
        flash("Ese presupuesto no existe o no te pertenece.")
        return redirect(url_for("presupuestos.index"))

    db.session.delete(p)
    db.session.commit()
    flash("Presupuesto eliminado.")
    return redirect(url_for("presupuestos.index"))
