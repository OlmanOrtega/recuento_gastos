"""
Blueprint de transacciones programadas.
Gestiona la creación, confirmación, salto y eliminación de transacciones recurrentes/futuras.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from dateutil.relativedelta import relativedelta

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user

from models import db, Categoria, Transaccion, TransaccionProgramada

programadas_bp = Blueprint("programadas", __name__, url_prefix="/programadas")


def _ocurrencias_atrasadas(prog, hoy):
    """
    Estima cuántas ocurrencias han pasado sin confirmar desde proxima_fecha hasta hoy.
    Para 'una_vez' siempre es 1 si está vencida.
    """
    if prog.proxima_fecha > hoy:
        return 0
    if prog.frecuencia == "una_vez":
        return 1
    if prog.frecuencia == "mensual":
        delta = relativedelta(hoy, prog.proxima_fecha)
        return max(1, delta.years * 12 + delta.months + 1)
    if prog.frecuencia == "quincenal":
        dias = (hoy - prog.proxima_fecha).days
        return max(1, dias // 15 + 1)
    return 1


def pendientes_de_hoy(usuario_id):
    """
    Retorna las TransaccionProgramada activas cuya proxima_fecha ya llegó.
    Ordenadas por fecha (más antiguas primero).
    """
    return (
        TransaccionProgramada.query
        .filter(
            TransaccionProgramada.usuario_id == usuario_id,
            TransaccionProgramada.activa == True,          # noqa: E712
            TransaccionProgramada.proxima_fecha <= date.today(),
        )
        .order_by(TransaccionProgramada.proxima_fecha.asc())
        .all()
    )


@programadas_bp.route("/")
@login_required
def index():
    """Lista todas las transacciones programadas del usuario."""
    hoy = date.today()
    proximas = (
        TransaccionProgramada.query
        .filter_by(usuario_id=current_user.id, activa=True)
        .order_by(TransaccionProgramada.proxima_fecha.asc())
        .all()
    )
    # Anotar cuántas ocurrencias lleva atrasada cada programada
    for p in proximas:
        p._ocurrencias_atrasadas = _ocurrencias_atrasadas(p, hoy)
    return render_template("programadas.html", proximas=proximas, hoy=hoy)


@programadas_bp.route("/nueva", methods=["POST"])
@login_required
def nueva():
    """
    Crea una transacción programada directamente (desde el formulario dedicado).
    También es llamada internamente desde transacciones.nueva() cuando la fecha es futura.
    """
    tipo          = request.form.get("tipo")
    monto_texto   = request.form.get("monto", "").strip()
    categoria_id  = request.form.get("categoria_id")
    fecha_texto   = request.form.get("fecha", "").strip()
    metodo_pago   = request.form.get("metodo_pago", "").strip()
    nota          = request.form.get("nota", "").strip() or None
    frecuencia    = request.form.get("frecuencia", "una_vez")

    # Validaciones
    if tipo not in ("gasto", "ingreso"):
        flash("Tipo inválido.")
        return redirect(url_for("transacciones.nueva"))

    try:
        monto = Decimal(monto_texto)
        if monto <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        flash("El monto debe ser un número mayor a cero.")
        return redirect(url_for("transacciones.nueva"))

    categoria = Categoria.query.filter_by(
        id=categoria_id, usuario_id=current_user.id, tipo=tipo
    ).first()
    if categoria is None:
        flash("Categoría inválida.")
        return redirect(url_for("transacciones.nueva"))

    try:
        fecha = date.fromisoformat(fecha_texto)
    except (ValueError, TypeError):
        flash("Fecha inválida.")
        return redirect(url_for("transacciones.nueva"))

    if metodo_pago not in ("efectivo", "digital"):
        flash("Elegí un método de pago.")
        return redirect(url_for("transacciones.nueva"))

    if frecuencia not in ("una_vez", "mensual", "quincenal"):
        frecuencia = "una_vez"

    prog = TransaccionProgramada(
        usuario_id=current_user.id,
        categoria_id=categoria.id,
        tipo=tipo,
        monto=monto,
        metodo_pago=metodo_pago,
        nota=nota,
        frecuencia=frecuencia,
        proxima_fecha=fecha,
    )
    db.session.add(prog)
    db.session.commit()

    etiqueta = {"una_vez": "para el", "mensual": "mensual desde el", "quincenal": "quincenal desde el"}
    flash(f"Transacción programada {etiqueta.get(frecuencia, '')} {fecha.strftime('%d/%m/%Y')}.")
    return redirect(url_for("transacciones.nueva"))


@programadas_bp.route("/<int:prog_id>/confirmar", methods=["POST"])
@login_required
def confirmar(prog_id):
    """Confirma una transacción programada: crea la Transaccion real y avanza la fecha."""
    prog = TransaccionProgramada.query.filter_by(
        id=prog_id, usuario_id=current_user.id, activa=True
    ).first()

    if prog is None:
        if _es_fetch():
            return jsonify(exito=False, mensaje="No encontrada."), 404
        flash("Transacción no encontrada.")
        return redirect(url_for("dashboard.index"))

    transaccion = Transaccion(
        usuario_id=current_user.id,
        categoria_id=prog.categoria_id,
        tipo=prog.tipo,
        monto=prog.monto,
        fecha=prog.proxima_fecha,
        nota=prog.nota,
        metodo_pago=prog.metodo_pago,
    )
    db.session.add(transaccion)
    prog.avanzar_fecha()
    db.session.commit()

    if _es_fetch():
        return jsonify(exito=True, mensaje="Confirmada.")
    flash(f"✓ Transacción de ₡{prog.monto} confirmada y registrada.")
    return redirect(url_for("dashboard.index"))


@programadas_bp.route("/<int:prog_id>/saltar", methods=["POST"])
@login_required
def saltar(prog_id):
    """Salta esta ocurrencia sin crear transacción, avanzando la fecha igualmente."""
    prog = TransaccionProgramada.query.filter_by(
        id=prog_id, usuario_id=current_user.id, activa=True
    ).first()

    if prog is None:
        if _es_fetch():
            return jsonify(exito=False, mensaje="No encontrada."), 404
        flash("Transacción no encontrada.")
        return redirect(url_for("dashboard.index"))

    prog.avanzar_fecha()
    db.session.commit()

    if _es_fetch():
        return jsonify(exito=True, mensaje="Saltada.")
    flash("Ocurrencia saltada.")
    return redirect(url_for("dashboard.index"))


@programadas_bp.route("/<int:prog_id>/editar", methods=["GET", "POST"])
@login_required
def editar(prog_id):
    """Edita una transacción programada activa."""
    prog = TransaccionProgramada.query.filter_by(
        id=prog_id, usuario_id=current_user.id, activa=True
    ).first()
    if prog is None:
        flash("Transacción programada no encontrada.")
        return redirect(url_for("programadas.index"))

    categorias_gasto = (
        Categoria.query.filter_by(usuario_id=current_user.id, tipo="gasto")
        .order_by(Categoria.nombre).all()
    )
    categorias_ingreso = (
        Categoria.query.filter_by(usuario_id=current_user.id, tipo="ingreso")
        .order_by(Categoria.nombre).all()
    )

    if request.method == "GET":
        return render_template(
            "programadas_editar.html",
            prog=prog,
            categorias_gasto=categorias_gasto,
            categorias_ingreso=categorias_ingreso,
        )

    # POST: aplicar cambios
    tipo         = request.form.get("tipo")
    monto_texto  = request.form.get("monto", "").strip()
    categoria_id = request.form.get("categoria_id")
    fecha_texto  = request.form.get("fecha", "").strip()
    metodo_pago  = request.form.get("metodo_pago", "").strip()
    nota         = request.form.get("nota", "").strip() or None
    frecuencia   = request.form.get("frecuencia", "una_vez")

    if tipo not in ("gasto", "ingreso"):
        flash("Tipo inválido.")
        return redirect(url_for("programadas.editar", prog_id=prog_id))

    try:
        monto = Decimal(monto_texto)
        if monto <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        flash("El monto debe ser mayor a cero.")
        return redirect(url_for("programadas.editar", prog_id=prog_id))

    categoria = Categoria.query.filter_by(
        id=categoria_id, usuario_id=current_user.id, tipo=tipo
    ).first()
    if categoria is None:
        flash("Categoría inválida.")
        return redirect(url_for("programadas.editar", prog_id=prog_id))

    try:
        fecha = date.fromisoformat(fecha_texto)
    except (ValueError, TypeError):
        flash("Fecha inválida.")
        return redirect(url_for("programadas.editar", prog_id=prog_id))

    if metodo_pago not in ("efectivo", "digital"):
        flash("Elegí un método de pago.")
        return redirect(url_for("programadas.editar", prog_id=prog_id))

    if frecuencia not in ("una_vez", "mensual", "quincenal"):
        frecuencia = "una_vez"

    prog.tipo          = tipo
    prog.monto         = monto
    prog.categoria_id  = categoria.id
    prog.proxima_fecha = fecha
    prog.metodo_pago   = metodo_pago
    prog.nota          = nota
    prog.frecuencia    = frecuencia
    db.session.commit()

    flash("Transacción programada actualizada.")
    return redirect(url_for("programadas.index"))


@programadas_bp.route("/<int:prog_id>/eliminar", methods=["POST"])
@login_required
def eliminar(prog_id):
    """Desactiva permanentemente una transacción programada."""
    prog = TransaccionProgramada.query.filter_by(
        id=prog_id, usuario_id=current_user.id
    ).first()

    if prog is None:
        flash("No encontrada.")
        return redirect(url_for("programadas.index"))

    prog.activa = False
    db.session.commit()
    flash("Transacción programada eliminada.")
    return redirect(url_for("programadas.index"))


def _es_fetch():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"
