"""
Rutas de transacciones: agregar, listar (historial), y crear categoria
al vuelo desde el formulario.
"""

import csv
import io
from datetime import date, timedelta
import calendar
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, request, flash, Response, jsonify
from math import ceil
from flask_login import login_required, current_user
from sqlalchemy import extract

from models import db, Categoria, Transaccion, crear_categoria_usuario
from sqlalchemy import or_ as sql_or, cast, String
from dashboard import rango_del_mes, MESES_ES

transacciones_bp = Blueprint("transacciones", __name__)


def _es_peticion_fetch():
    """Detecta si el request vino de nuestro fetch() en vez de un form normal."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _validar_datos_transaccion(form, usuario_id):
    #Valida los datos de un formulario de transaccion 
    tipo = form.get("tipo")
    monto_texto = form.get("monto", "").strip()
    categoria_id = form.get("categoria_id")
    fecha_texto = form.get("fecha", "").strip()
    nota = form.get("nota", "").strip() or None
    metodo_pago = form.get("metodo_pago", "").strip() or None

    if tipo not in ("gasto", "ingreso"):
        return None, "Tipo de transaccion invalido."

    if metodo_pago not in ("efectivo", "digital"):
        return None, "Elegí si el movimiento fue en efectivo o digital."

    try:
        monto = Decimal(monto_texto)
        if monto <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return None, "El monto tiene que ser un numero mayor a cero."

    # Validamos que categoria_id sea realmente un numero antes de usarlo en
    # la consulta. Sin esto, si llega vacio o con texto (por ejemplo si el
    # campo no tenia "required" y el usuario nunca eligio nada), la consulta
    # de mas abajo le pasaria un valor invalido a una columna numerica de la
    # base de datos y esto podria terminar en un error 500 en vez de un
    # mensaje de error prolijo.
    try:
        categoria_id = int(categoria_id)
    except (TypeError, ValueError):
        return None, "Elegí una categoria valida."

    categoria = Categoria.query.filter_by(id=categoria_id, usuario_id=usuario_id, tipo=tipo).first()
    if categoria is None:
        return None, "Categoria invalida para ese tipo de transaccion."

    try:
        fecha = date.fromisoformat(fecha_texto) if fecha_texto else date.today()
    except ValueError:
        return None, "Fecha invalida."

    datos = {
        "tipo": tipo,
        "monto": monto,
        "categoria_id": categoria.id,
        "fecha": fecha,
        "nota": nota,
        "metodo_pago": metodo_pago,
    }
    return datos, None


@transacciones_bp.route("/transaccion/nueva", methods=["GET", "POST"])
@login_required
def nueva():
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
            "transaccion_nueva.html",
            categorias_gasto=categorias_gasto,
            categorias_ingreso=categorias_ingreso,
            hoy=date.today().isoformat(),
        )

    # POST: procesar el formulario
    datos, error = _validar_datos_transaccion(request.form, current_user.id)
    if error:
        if _es_peticion_fetch():
            return jsonify(exito=False, mensaje=error), 400
        flash(error)
        return redirect(url_for("transacciones.nueva"))

    # Fecha futura → derivar a transacción programada (no crear Transaccion real)
    if datos["fecha"] > date.today():
        # Redirigimos internamente a programadas.nueva usando los mismos datos del form
        from flask import current_app
        with current_app.test_request_context():
            pass  # solo para indicar que usamos el request actual
        # Delegamos al blueprint de programadas pasando el request original
        from programadas import programadas_bp
        # Creamos la programada directamente aquí para no hacer redirect complejo
        from models import TransaccionProgramada
        from decimal import Decimal
        frecuencia = request.form.get("frecuencia", "una_vez")
        if frecuencia not in ("una_vez", "mensual", "quincenal"):
            frecuencia = "una_vez"
        prog = TransaccionProgramada(
            usuario_id=current_user.id,
            categoria_id=datos["categoria_id"],
            tipo=datos["tipo"],
            monto=datos["monto"],
            metodo_pago=datos["metodo_pago"],
            nota=datos["nota"],
            frecuencia=frecuencia,
            proxima_fecha=datos["fecha"],
        )
        db.session.add(prog)
        db.session.commit()

        etiquetas = {"una_vez": "para el", "mensual": "mensual desde el", "quincenal": "quincenal desde el"}
        mensaje = f"Programado {etiquetas.get(frecuencia, '')} {datos['fecha'].strftime('%d/%m/%Y')}."

        if _es_peticion_fetch():
            return jsonify(exito=True, mensaje=mensaje, programada=True)
        flash(mensaje)
        return redirect(url_for("transacciones.nueva"))

    # Fecha de hoy o pasada → transacción normal
    transaccion = Transaccion(usuario_id=current_user.id, **datos)
    db.session.add(transaccion)
    db.session.commit()

    mensaje = f"{'Gasto' if datos['tipo'] == 'gasto' else 'Ingreso'} de ₡{datos['monto']} guardado."

    if _es_peticion_fetch():
        return jsonify(exito=True, mensaje=mensaje, programada=False)

    flash(mensaje)
    return redirect(url_for("dashboard.index"))


@transacciones_bp.route("/categoria/nueva", methods=["POST"])
@login_required
def nueva_categoria():
    """
    Permite crear una categoria nueva desde el mismo formulario de
    'agregar transaccion', sin salir del flujo
    """
    nombre = request.form.get("nombre_categoria", "").strip()
    tipo = request.form.get("tipo_categoria")

    categoria, error = crear_categoria_usuario(current_user.id, nombre, tipo)
    if error:
        flash(error)
    else:
        flash(f"Categoria '{categoria.nombre}' creada.")

    return redirect(url_for("transacciones.nueva"))


@transacciones_bp.route("/transaccion/<int:transaccion_id>/editar", methods=["GET", "POST"])
@login_required
def editar(transaccion_id):
    transaccion = Transaccion.query.filter_by(id=transaccion_id, usuario_id=current_user.id).first()
    if transaccion is None:
        flash("Esa transaccion no existe o no te pertenece.")
        return redirect(url_for("transacciones.historial"))

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
            "transaccion_editar.html",
            transaccion=transaccion,
            categorias_gasto=categorias_gasto,
            categorias_ingreso=categorias_ingreso,
        )

    # POST: procesar los cambios
    datos, error = _validar_datos_transaccion(request.form, current_user.id)
    if error:
        flash(error)
        return redirect(url_for("transacciones.editar", transaccion_id=transaccion_id))

    transaccion.tipo = datos["tipo"]
    transaccion.monto = datos["monto"]
    transaccion.categoria_id = datos["categoria_id"]
    transaccion.fecha = datos["fecha"]
    transaccion.nota = datos["nota"]
    transaccion.metodo_pago = datos["metodo_pago"]
    db.session.commit()

    flash("Transaccion actualizada correctamente.")
    return redirect(url_for("transacciones.historial"))


@transacciones_bp.route("/transaccion/<int:transaccion_id>/eliminar", methods=["POST"])
@login_required
def eliminar(transaccion_id):

    transaccion = Transaccion.query.filter_by(id=transaccion_id, usuario_id=current_user.id).first()
    if transaccion is None:
        if _es_peticion_fetch():
            return jsonify(exito=False, mensaje="Esa transaccion no existe o no te pertenece."), 404
        flash("Esa transaccion no existe o no te pertenece.")
        return redirect(url_for("transacciones.historial"))

    db.session.delete(transaccion)
    db.session.commit()

    if _es_peticion_fetch():
        return jsonify(exito=True, mensaje="Transaccion eliminada.")

    flash("Transaccion eliminada.")
    return redirect(url_for("transacciones.historial"))


@transacciones_bp.route("/historial")
@login_required
def historial():
    """
    Lista las transacciones del usuario, filtrables por mes (anio+mes),
    semana y categoria via query params: 
    /historial?anio=2026&mes=7&semana=2&categoria_id=3
    """
    anio, mes, categoria_id, semana, metodo_pago, q = _leer_filtros_de_query()
    pagina = request.args.get("pagina", 1, type=int)
    por_pagina = 10

    transacciones, total, total_gastos_filtro, total_ingresos_filtro = _transacciones_paginadas(
        current_user.id, anio, mes, categoria_id, semana, metodo_pago, pagina, por_pagina, q
    )

    total_paginas = ceil(total / por_pagina) if total > 0 else 1

    categorias = Categoria.query.filter_by(usuario_id=current_user.id).order_by(Categoria.nombre).all()

    meses_con_datos = (
        db.session.query(
            extract("year", Transaccion.fecha),
            extract("month", Transaccion.fecha),
        )
        .filter(Transaccion.usuario_id == current_user.id)
        .distinct()
        .order_by(extract("year", Transaccion.fecha).desc(), extract("month", Transaccion.fecha).desc())
        .all()
    )
    meses_disponibles = [
        {"anio": int(a), "mes": int(m), "etiqueta": f"{MESES_ES[int(m)]} {int(a)}"}
        for a, m in meses_con_datos
    ]

    semanas_disponibles = []
    if anio and mes:
        semanas_disponibles = _calcular_semanas_del_mes(anio, mes)

    return render_template(
        "historial.html",
        transacciones=transacciones,
        categorias=categorias,
        meses_disponibles=meses_disponibles,
        anio_seleccionado=anio,
        mes_seleccionado=mes,
        categoria_seleccionada=categoria_id,
        semana_seleccionada=semana,
        metodo_pago_seleccionado=metodo_pago,
        semanas_disponibles=semanas_disponibles,
        q=q,
        pagina_actual=pagina,
        total_paginas=total_paginas,
        por_pagina=por_pagina,
        total_transacciones=total,
        mostrando=len(transacciones),
        total_gastos_filtro=total_gastos_filtro,
        total_ingresos_filtro=total_ingresos_filtro,
    )
    
def _transacciones_paginadas(usuario_id, anio, mes, categoria_id, semana=None,
                              metodo_pago=None, pagina=1, por_pagina=10, q=""):
    """Retorna transacciones paginadas, el total y subtotales por tipo del filtro activo."""
    from sqlalchemy import case
    query = Transaccion.query.filter_by(usuario_id=usuario_id)

    if anio and mes and semana:
        inicio, fin = _obtener_rango_semana(anio, mes, semana)
        query = query.filter(Transaccion.fecha >= inicio, Transaccion.fecha <= fin)
    elif anio and mes:
        query = query.filter(
            extract("year", Transaccion.fecha) == anio,
            extract("month", Transaccion.fecha) == mes
        )

    if categoria_id:
        query = query.filter_by(categoria_id=categoria_id)

    if metodo_pago in ("efectivo", "digital"):
        query = query.filter(Transaccion.metodo_pago == metodo_pago)

    if q:
        query = query.filter(
            sql_or(
                Transaccion.nota.ilike(f"%{q}%"),
                cast(Transaccion.monto, String).contains(q),
            )
        )

    # Calcular subtotales ANTES de paginar reutilizando la misma query base
    subtotales_q = db.session.query(
        db.func.sum(case((Transaccion.tipo == "gasto",   Transaccion.monto), else_=0)),
        db.func.sum(case((Transaccion.tipo == "ingreso", Transaccion.monto), else_=0)),
    )
    if query.whereclause is not None:
        subtotales_q = subtotales_q.filter(query.whereclause)
    subtotales = subtotales_q.one()
    total_gastos_filtro   = float(subtotales[0] or 0)
    total_ingresos_filtro = float(subtotales[1] or 0)

    total = query.count()
    offset = (pagina - 1) * por_pagina
    transacciones = query.order_by(Transaccion.fecha.desc()).offset(offset).limit(por_pagina).all()

    return transacciones, total, total_gastos_filtro, total_ingresos_filtro

@transacciones_bp.route("/historial/data")
@login_required
def historial_data():
    anio, mes, categoria_id, semana, metodo_pago, q = _leer_filtros_de_query()
    pagina = request.args.get("pagina", 1, type=int)
    por_pagina = 10

    transacciones, total, total_gastos_filtro, total_ingresos_filtro = _transacciones_paginadas(
        current_user.id, anio, mes, categoria_id, semana, metodo_pago, pagina, por_pagina, q
    )

    total_paginas = ceil(total / por_pagina) if total > 0 else 1

    categorias = Categoria.query.filter_by(usuario_id=current_user.id).order_by(Categoria.nombre).all()

    meses_con_datos = (
        db.session.query(
            extract("year", Transaccion.fecha),
            extract("month", Transaccion.fecha),
        )
        .filter(Transaccion.usuario_id == current_user.id)
        .distinct()
        .order_by(extract("year", Transaccion.fecha).desc(), extract("month", Transaccion.fecha).desc())
        .all()
    )
    meses_disponibles = [
        {"anio": int(a), "mes": int(m), "etiqueta": f"{MESES_ES[int(m)]} {int(a)}"}
        for a, m in meses_con_datos
    ]

    semanas_disponibles = []
    if anio and mes:
        semanas_disponibles = _calcular_semanas_del_mes(anio, mes)

    return render_template(
        "_contenido_historial.html",
        transacciones=transacciones,
        categorias=categorias,
        meses_disponibles=meses_disponibles,
        anio_seleccionado=anio,
        mes_seleccionado=mes,
        categoria_seleccionada=categoria_id,
        semana_seleccionada=semana,
        metodo_pago_seleccionado=metodo_pago,
        semanas_disponibles=semanas_disponibles,
        q=q,
        pagina_actual=pagina,
        total_paginas=total_paginas,
        por_pagina=por_pagina,
        total_transacciones=total,
        mostrando=len(transacciones),
        total_gastos_filtro=total_gastos_filtro,
        total_ingresos_filtro=total_ingresos_filtro,
    )

def _leer_filtros_de_query():
    """Lee los filtros de la query string. Defaultea al mes actual."""
    hoy = date.today()
    anio = request.args.get("anio", type=int, default=hoy.year)
    mes  = request.args.get("mes",  type=int, default=hoy.month)
    categoria_id = request.args.get("categoria_id", type=int)
    semana = request.args.get("semana", type=int)
    metodo_pago = request.args.get("metodo_pago", "").strip() or None
    if metodo_pago not in (None, "efectivo", "digital"):
        metodo_pago = None
    q = request.args.get("q", "").strip()
    return anio, mes, categoria_id, semana, metodo_pago, q

def _transacciones_filtradas(usuario_id, anio, mes, categoria_id, semana=None, metodo_pago=None):
    """Retorna las transacciones filtradas por usuario, mes, categoria, semana y método."""
    query = Transaccion.query.filter_by(usuario_id=usuario_id)

    if anio and mes and semana:
        inicio, fin = _obtener_rango_semana(anio, mes, semana)
        query = query.filter(Transaccion.fecha >= inicio, Transaccion.fecha <= fin)
    elif anio and mes:
        query = query.filter(
            extract("year", Transaccion.fecha) == anio,
            extract("month", Transaccion.fecha) == mes
        )

    if categoria_id:
        query = query.filter_by(categoria_id=categoria_id)

    if metodo_pago in ("efectivo", "digital"):
        query = query.filter(Transaccion.metodo_pago == metodo_pago)

    return query.order_by(Transaccion.fecha.desc()).all()

def _obtener_rango_semana(anio, mes, numero_semana):
    """Devuelve el primer y último día de la semana N del mes"""
    import calendar
    from datetime import datetime, timedelta
    
    primer_dia = datetime(anio, mes, 1)
    ultimo_dia = datetime(anio, mes, calendar.monthrange(anio, mes)[1])
    
    #Encontrar el lunes de la PRIMERA semana que cae en este mes
    #Si el mes empieza en martes (weekday=1), el lunes es 1 día antes (29 del mes anterior)
    dias_para_lunes = (0 - primer_dia.weekday()) % 7
    inicio_semana_1 = primer_dia + timedelta(days=dias_para_lunes)
    
    #Si la primera semana del mes empieza en el mes anterior, ajustar
    if inicio_semana_1 < primer_dia:
        inicio_semana_1 = primer_dia
    
    #Calcular la semana seleccionada
    inicio = inicio_semana_1 + timedelta(weeks=numero_semana - 1)
    fin = inicio + timedelta(days=6)
    
    #Asegurar que no nos salimos del mes
    if inicio < primer_dia:
        inicio = primer_dia
    if fin > ultimo_dia:
        fin = ultimo_dia
    
    return inicio.date(), fin.date()

def _calcular_semanas_del_mes(anio, mes):
    #Calcula cuántas semanas tiene el mes y sus rangos para mostrar en los botones
    semanas = []
    primer_dia = date(anio, mes, 1)
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
    
    #Encontrar el lunes de la primera semana
    dias_para_lunes = (0 - primer_dia.weekday()) % 7
    inicio_semana = primer_dia + timedelta(days=dias_para_lunes)
    
    semana_num = 1
    while inicio_semana <= ultimo_dia:
        fin_semana = inicio_semana + timedelta(days=6)
        if fin_semana > ultimo_dia:
            fin_semana = ultimo_dia
        
        #Solo agregar si la semana tiene al menos 1 día en el mes
        if inicio_semana.month == mes or fin_semana.month == mes:
            #Ajustar inicio si es antes del mes
            inicio_mostrar = inicio_semana if inicio_semana.month == mes else primer_dia
            #Ajustar fin si es después del mes
            fin_mostrar = fin_semana if fin_semana.month == mes else ultimo_dia
            
            semanas.append({
                'numero': semana_num,
                'inicio': inicio_mostrar.strftime('%d/%m'),
                'fin': fin_mostrar.strftime('%d/%m')
            })
            semana_num += 1
        
        inicio_semana += timedelta(days=7)
    
    return semanas


@transacciones_bp.route("/exportar-csv")
@login_required
def exportar_csv():
    #Genera un CSV con las transacciones del usuario
    anio, mes, categoria_id, semana, metodo_pago, q = _leer_filtros_de_query()

    transacciones = _transacciones_filtradas(current_user.id, anio, mes, categoria_id, semana, metodo_pago)

    #Armamos el CSV en memoria (io.StringIO) en vez de escribir un
    #archivo real en disco }
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Fecha", "Tipo", "Categoria", "Monto", "Metodo de pago", "Nota"])

    for t in transacciones:
        writer.writerow([
            t.fecha.isoformat(),
            t.tipo,
            t.categoria.nombre,
            t.monto,
            t.metodo_pago or "",
            t.nota or "",
        ])

    nombre_archivo = "gastoflow_transacciones.csv"
    if anio and mes:
        nombre_archivo = f"gastoflow_{MESES_ES[mes].lower()}_{anio}.csv"

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )
