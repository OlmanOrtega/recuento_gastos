"""
Rutas del dashboard: totales del mes, datos para el grafico de Chart.js,
y las alertas/consejos automaticos.
"""

import calendar
from datetime import date

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from models import db, Transaccion, Categoria

dashboard_bp = Blueprint("dashboard", __name__)


# ---------------------------------------------------------------------------
# Helpers de fechas
# ---------------------------------------------------------------------------
def rango_del_mes(anio, mes):
    """Devuelve (primer_dia, ultimo_dia) del mes dado, ambos como date."""
    primer_dia = date(anio, mes, 1)
    ultimo_dia_num = calendar.monthrange(anio, mes)[1]
    ultimo_dia = date(anio, mes, ultimo_dia_num)
    return primer_dia, ultimo_dia


def mes_anterior(anio, mes):
    """Devuelve (anio, mes) del mes anterior, manejando el cambio de anio."""
    if mes == 1:
        return anio - 1, 12
    return anio, mes - 1


def primer_mes_con_datos(usuario_id):
    """
    Devuelve (anio, mes) de la transaccion mas antigua del usuario o None si no tiene ninguna
    """
    primera_fecha = (
        db.session.query(db.func.min(Transaccion.fecha))
        .filter(Transaccion.usuario_id == usuario_id)
        .scalar()
    )
    if primera_fecha is None:
        return None
    return primera_fecha.year, primera_fecha.month

# Helpers de calculo
def total_por_tipo(usuario_id, anio, mes, tipo):
    """Suma el monto de todas las transacciones de un tipo ('gasto'/'ingreso')
    para un usuario en un mes dado. Devuelve 0 si no hay ninguna."""
    inicio, fin = rango_del_mes(anio, mes)
    total = (
        db.session.query(db.func.sum(Transaccion.monto))
        .filter(
            Transaccion.usuario_id == usuario_id,
            Transaccion.tipo == tipo,
            Transaccion.fecha >= inicio,
            Transaccion.fecha <= fin,
        )
        .scalar()
    )
    return float(total) if total else 0.0


def gastos_por_categoria(usuario_id, anio, mes):
    """Devuelve una lista de dicts {nombre, total} con el gasto de cada
    categoria en el mes dado. Solo incluye categorias con gasto > 0."""
    inicio, fin = rango_del_mes(anio, mes)
    resultados = (
        db.session.query(Categoria.nombre, db.func.sum(Transaccion.monto))
        .join(Transaccion, Transaccion.categoria_id == Categoria.id)
        .filter(
            Transaccion.usuario_id == usuario_id,
            Transaccion.tipo == "gasto",
            Transaccion.fecha >= inicio,
            Transaccion.fecha <= fin,
        )
        .group_by(Categoria.nombre)
        .all()
    )
    return [{"nombre": nombre, "total": float(total)} for nombre, total in resultados]


def gasto_de_categoria(usuario_id, categoria_nombre, anio, mes):
    #Gasto total de una categoria puntual (por nombre) en un mes dado.
    inicio, fin = rango_del_mes(anio, mes)
    total = (
        db.session.query(db.func.sum(Transaccion.monto))
        .join(Categoria, Categoria.id == Transaccion.categoria_id)
        .filter(
            Transaccion.usuario_id == usuario_id,
            Transaccion.tipo == "gasto",
            Categoria.nombre == categoria_nombre,
            Transaccion.fecha >= inicio,
            Transaccion.fecha <= fin,
        )
        .scalar()
    )
    return float(total) if total else 0.0


# Diccionario de consejos automaticos por categoria (reglas simples, no IA)
CONSEJOS_POR_CATEGORIA = {
    "Transporte": "¿Considerás usar bus en vez de Uber para bajar este gasto?",
    "Comida": "¿Estás pidiendo delivery muy seguido? Cocinar en casa podría ayudarte.",
    "Ocio": "Revisá si hay gastos de ocio que podrías espaciar más en el mes.",
    "Servicios": "Revisá si alguna suscripción quedó activa sin que la uses.",
}


def generar_alertas(usuario_id, anio, mes):
    #Calcula todas las alertas/consejos para el mes dado y devuelve una lista de strings
    alertas = []

    #Regla 1: % gastado sobre ingresos
    total_ingresos = total_por_tipo(usuario_id, anio, mes, "ingreso")
    total_gastos = total_por_tipo(usuario_id, anio, mes, "gasto")

    if total_ingresos > 0:
        porcentaje = (total_gastos / total_ingresos) * 100
        if porcentaje >= 100:
            alertas.append(f"Ya gastaste más de lo que ganaste este mes ({porcentaje:.0f}% de tus ingresos).")
        elif porcentaje >= 80:
            alertas.append(f"Llevás gastado el {porcentaje:.0f}% de tus ingresos este mes.")
        elif porcentaje >= 50:
            alertas.append(f"Vas por la mitad: llevás gastado el {porcentaje:.0f}% de tus ingresos este mes.")

    #Regla 2: categoria vs mes anterior (+ Regla 3: consejo asociado)
    anio_ant, mes_ant = mes_anterior(anio, mes)
    categorias_actuales = gastos_por_categoria(usuario_id, anio, mes)

    aumentos = []  #lista de (nombre_categoria, porcentaje_aumento)
    for cat in categorias_actuales:
        total_anterior = gasto_de_categoria(usuario_id, cat["nombre"], anio_ant, mes_ant)
        if total_anterior <= 0:
            continue  #sin base de comparacion valida, no se evalua esta categoria
        aumento_pct = ((cat["total"] - total_anterior) / total_anterior) * 100
        if aumento_pct >= 20:
            aumentos.append((cat["nombre"], aumento_pct))

    #Ordenamos de mayor a menor aumento, y mostramos maximo 2 para no saturar
    aumentos.sort(key=lambda x: x[1], reverse=True)
    for nombre_categoria, aumento_pct in aumentos[:2]:
        alertas.append(f"Gastaste {aumento_pct:.0f}% más en {nombre_categoria} que el mes pasado.")
        if nombre_categoria in CONSEJOS_POR_CATEGORIA:
            alertas.append(CONSEJOS_POR_CATEGORIA[nombre_categoria])

    return alertas


MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Ruta principal del dashboard
@dashboard_bp.route("/dashboard")
@login_required
def index():
    hoy = date.today()
    #Permite navegar a otros meses via ?anio=2026&mes=6
    anio = request.args.get("anio", type=int, default=hoy.year)
    mes = request.args.get("mes", type=int, default=hoy.month)
    if not (1 <= mes <= 12):
        anio, mes = hoy.year, hoy.month

    total_ingresos = total_por_tipo(current_user.id, anio, mes, "ingreso")
    total_gastos = total_por_tipo(current_user.id, anio, mes, "gasto")
    balance = total_ingresos - total_gastos

    categorias = gastos_por_categoria(current_user.id, anio, mes)
    alertas = generar_alertas(current_user.id, anio, mes)

    nombre_mes = MESES_ES[mes]

    anio_prev, mes_prev = mes_anterior(anio, mes)
    anio_sig, mes_sig = (anio + 1, 1) if mes == 12 else (anio, mes + 1)

    #Limites de navegacion: no tiene sentido dejar ir hacia atras antes de la primera transaccion registrada
    primer_mes = primer_mes_con_datos(current_user.id)
    if primer_mes is None:
        puede_ir_anterior = False
    else:
        puede_ir_anterior = (anio_prev, mes_prev) >= primer_mes

    puede_ir_siguiente = (anio_sig, mes_sig) <= (hoy.year, hoy.month)

    return render_template(
        "dashboard.html",
        usuario=current_user,
        anio=anio,
        mes=mes,
        nombre_mes=nombre_mes,
        anio_prev=anio_prev,
        mes_prev=mes_prev,
        anio_sig=anio_sig,
        mes_sig=mes_sig,
        puede_ir_anterior=puede_ir_anterior,
        puede_ir_siguiente=puede_ir_siguiente,
        total_ingresos=total_ingresos,
        total_gastos=total_gastos,
        balance=balance,
        categorias=categorias,
        alertas=alertas,
    )
