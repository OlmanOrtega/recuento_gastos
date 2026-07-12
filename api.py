"""
API REST de GastoFlow.

Estos endpoints devuelven JSON en vez de HTML, pensados para que
cualquier cliente externo pueda consumir los datos de GastoFlow sin depender de
las paginas renderizadas con Jinja2.

AUTENTICACION: esta version usa JWT (JSON Web Tokens), separado por
completo del sistema de sesiones/cookies que usa el resto de la app
(auth.py, con Flask-Login). Son dos mecanismos distintos a proposito:

- La web (paginas HTML) sigue usando cookies de sesion via Flask-Login,
  porque el navegador las maneja solo.
- La API usa JWT: el cliente manda su token en cada request dentro del
  header "Authorization: Bearer <token>", sin depender de cookies. Esto
  es lo esperado para un consumidor externo (un script, una app movil),
  que no necesariamente vive dentro de un navegador con cookies.

"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

import jwt
from flask import Blueprint, request, jsonify, g, current_app

from models import db, Usuario, Categoria, Transaccion, crear_categorias_default
from dashboard import total_por_tipo, rango_del_mes

api_bp = Blueprint("api", __name__, url_prefix="/api")

DURACION_TOKEN = timedelta(days=7)  # cuanto dura un token antes de vencer

# JWT: generar y validar tokens
def _generar_token(usuario_id):
    """
    Crea un JWT firmado que identifica a un usuario. El token incluye:
    - usuario_id: quien es (lo leemos de vuelta en requiere_token)
    - exp: fecha de expiracion, despues de la cual el token deja de ser valido
    - iat: fecha de emision, util para depurar/auditar
    """
    payload = {
        "usuario_id": usuario_id,
        "exp": datetime.now(timezone.utc) + DURACION_TOKEN,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def requiere_token(vista):
    #Decorador para proteger rutas de la API con JWT
    @wraps(vista)
    def envoltura(*args, **kwargs):
        encabezado = request.headers.get("Authorization", "")
        if not encabezado.startswith("Bearer "):
            return jsonify(error="Falta el token. Envia el header 'Authorization: Bearer <token>'."), 401

        token = encabezado.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify(error="El token expiro. Volve a iniciar sesion con /api/login."), 401
        except jwt.InvalidTokenError:
            return jsonify(error="Token invalido."), 401

        usuario = db.session.get(Usuario, payload.get("usuario_id"))
        if usuario is None:
            return jsonify(error="El usuario de este token ya no existe."), 401

        g.usuario_actual = usuario
        return vista(*args, **kwargs)

    return envoltura


#Helpers de serializacion: convierten los objetos de SQLAlchemy a dicts
#simples listos para jsonify() los centralizamos aqui para que todos
#los endpoints devuelvan las transacciones/categorias con la misma forma
def _transaccion_a_dict(t):
    return {
        "id": t.id,
        "tipo": t.tipo,
        "monto": float(t.monto),
        "categoria_id": t.categoria_id,
        "categoria_nombre": t.categoria.nombre,
        "fecha": t.fecha.isoformat(),
        "nota": t.nota,
        "metodo_pago": t.metodo_pago,
    }


def _usuario_a_dict(usuario):
    return {
        "id": usuario.id,
        "nombre": usuario.nombre,
        "email": usuario.email,
        "es_invitado": usuario.es_invitado,
    }


#POST /api/registro
@api_bp.route("/registro", methods=["POST"])
def registro():
    #Crea un usuario nuevo. Espera JSON: {"nombre": "...", "email": "...", "password": "..."}

    datos = request.get_json(silent=True) or {}
    nombre = (datos.get("nombre") or "").strip()
    email = (datos.get("email") or "").strip().lower()
    password = datos.get("password") or ""

    if not nombre or not email or not password:
        return jsonify(error="Los campos nombre, email y password son obligatorios."), 400

    if Usuario.query.filter_by(email=email).first():
        return jsonify(error="Ya existe una cuenta con ese email."), 409

    usuario = Usuario(nombre=nombre, email=email, es_invitado=False)
    usuario.set_password(password)
    db.session.add(usuario)
    db.session.commit()
    crear_categorias_default(usuario)

    token = _generar_token(usuario.id)
    return jsonify(usuario=_usuario_a_dict(usuario), token=token), 201


#POST /api/login
@api_bp.route("/login", methods=["POST"])
def login():
    """
    Autentica a un usuario espera JSON devuelve un token JWT que el cliente debe guardar y mandar en el
    header Authorization: Bearer <token>' en cada llamada posterior a un endpoint protegido
    El token expira a los 7 dias (DURACION_TOKEN).
    """
    datos = request.get_json(silent=True) or {}
    email = (datos.get("email") or "").strip().lower()
    password = datos.get("password") or ""

    usuario = Usuario.query.filter_by(email=email, es_invitado=False).first()
    if usuario is None or not usuario.check_password(password):
        return jsonify(error="Email o contrasena incorrectos."), 401

    token = _generar_token(usuario.id)
    return jsonify(usuario=_usuario_a_dict(usuario), token=token)


# GET /api/transacciones
# POST /api/transacciones
@api_bp.route("/transacciones", methods=["GET"])
@requiere_token
def listar_transacciones():
    """Lista las transacciones del usuario autenticado con paginación opcional."""
    anio = request.args.get("anio", type=int)
    mes = request.args.get("mes", type=int)
    categoria_id = request.args.get("categoria_id", type=int)
    limit = request.args.get("limit", type=int, default=50)
    offset = request.args.get("offset", type=int, default=0)

    # Máximo 200 por llamada para evitar respuestas masivas
    limit = min(max(limit, 1), 200)

    query = Transaccion.query.filter_by(usuario_id=g.usuario_actual.id)

    if anio and mes and 1 <= mes <= 12:
        inicio, fin = rango_del_mes(anio, mes)
        query = query.filter(Transaccion.fecha >= inicio, Transaccion.fecha <= fin)

    if categoria_id:
        query = query.filter(Transaccion.categoria_id == categoria_id)

    total = query.count()
    transacciones = query.order_by(Transaccion.fecha.desc()).offset(offset).limit(limit).all()

    return jsonify(
        transacciones=[_transaccion_a_dict(t) for t in transacciones],
        total=total,
        limit=limit,
        offset=offset,
    )


@api_bp.route("/transacciones", methods=["POST"])
@requiere_token
def crear_transaccion():
    """
    Crea transaccion nueva. Espera JSON:
    {"tipo": "gasto"|"ingreso", "monto": 1500, "categoria_id": 3,
     "fecha": "2026-07-08" (opcional, default hoy),
     "nota": "..." (opcional), "metodo_pago": "efectivo"|"digital" (opcional)}
    """
    datos = request.get_json(silent=True) or {}

    tipo = datos.get("tipo")
    if tipo not in ("gasto", "ingreso"):
        return jsonify(error="El campo 'tipo' debe ser 'gasto' o 'ingreso'."), 400

    try:
        monto = Decimal(str(datos.get("monto")))
        if monto <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        return jsonify(error="El campo 'monto' tiene que ser un numero mayor a cero."), 400

    categoria_id = datos.get("categoria_id")
    categoria = Categoria.query.filter_by(id=categoria_id, usuario_id=g.usuario_actual.id, tipo=tipo).first()
    if categoria is None:
        return jsonify(error="Categoria invalida para ese tipo de transaccion."), 400

    fecha_texto = datos.get("fecha")
    try:
        fecha = date.fromisoformat(fecha_texto) if fecha_texto else date.today()
    except ValueError:
        return jsonify(error="El campo 'fecha' tiene que tener formato AAAA-MM-DD."), 400

    transaccion = Transaccion(
        usuario_id=g.usuario_actual.id,
        categoria_id=categoria.id,
        tipo=tipo,
        monto=monto,
        fecha=fecha,
        nota=datos.get("nota"),
        metodo_pago=datos.get("metodo_pago"),
    )
    db.session.add(transaccion)
    db.session.commit()

    return jsonify(transaccion=_transaccion_a_dict(transaccion)), 201


# GET /api/balance
@api_bp.route("/balance", methods=["GET"])
@requiere_token
def balance():
    #Resumen de ingresos, gastos y balance de un mes. 
    hoy = date.today()
    anio = request.args.get("anio", type=int, default=hoy.year)
    mes = request.args.get("mes", type=int, default=hoy.month)
    if not (1 <= mes <= 12):
        anio, mes = hoy.year, hoy.month

    total_ingresos = total_por_tipo(g.usuario_actual.id, anio, mes, "ingreso")
    total_gastos = total_por_tipo(g.usuario_actual.id, anio, mes, "gasto")

    return jsonify(
        anio=anio,
        mes=mes,
        total_ingresos=total_ingresos,
        total_gastos=total_gastos,
        balance=total_ingresos - total_gastos,
    )
