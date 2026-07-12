"""
Modelos de datos para GastoFlow.
"""

import secrets
from datetime import datetime, date, timedelta, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ─── Categorías default ───────────────────────────────────────────────────────

CATEGORIAS_DEFAULT_GASTO = [
    "Comida", "Transporte", "Ocio", "Servicios", "Salud", "Otros",
]

CATEGORIAS_DEFAULT_INGRESO = [
    "Salario", "Regalo", "Otro ingreso",
]


# ─── Modelos ──────────────────────────────────────────────────────────────────

class Usuario(UserMixin, db.Model):
    """Usuarios registrados e invitados en la misma tabla."""
    __tablename__ = "usuarios"

    id               = db.Column(db.Integer, primary_key=True)
    nombre           = db.Column(db.String(100), nullable=False)
    email            = db.Column(db.String(150), unique=True, nullable=True)
    password_hash    = db.Column(db.String(255), nullable=True)
    es_invitado      = db.Column(db.Boolean, default=False, nullable=False)
    fecha_creacion   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Última vez que el usuario interactuó con la app.
    # Para invitados se usa para saber si el plazo de vida debe contarse
    # desde la creación (si nunca volvieron) o desde la última actividad.
    ultima_actividad = db.Column(db.DateTime, nullable=True)

    categorias    = db.relationship("Categoria",    backref="usuario", cascade="all, delete-orphan")
    transacciones = db.relationship("Transaccion",  backref="usuario", cascade="all, delete-orphan")
    presupuestos  = db.relationship("Presupuesto",  backref="usuario", cascade="all, delete-orphan")
    tokens        = db.relationship("TokenRecuperacion", backref="usuario", cascade="all, delete-orphan")
    programadas   = db.relationship("TransaccionProgramada", backref="usuario", cascade="all, delete-orphan")

    def set_password(self, password_plano):
        """Genera el hash de la contraseña. Nunca guardamos texto plano."""
        self.password_hash = generate_password_hash(password_plano)

    def check_password(self, password_plano):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password_plano)

    def __repr__(self):
        tipo = "invitado" if self.es_invitado else "registrado"
        return f"<Usuario {self.id} - {self.nombre} ({tipo})>"


class Categoria(db.Model):
    """Cada categoría pertenece a un usuario."""
    __tablename__ = "categorias"

    id         = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    nombre     = db.Column(db.String(50), nullable=False)
    tipo       = db.Column(db.String(10), nullable=False, default="gasto")  # "gasto" o "ingreso"

    transacciones = db.relationship("Transaccion", backref="categoria")

    def __repr__(self):
        return f"<Categoria {self.nombre} ({self.tipo})>"


class Transaccion(db.Model):
    __tablename__ = "transacciones"

    id           = db.Column(db.Integer, primary_key=True)
    usuario_id   = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias.id"), nullable=False)

    tipo         = db.Column(db.String(10), nullable=False)   # "gasto" o "ingreso"
    monto        = db.Column(db.Numeric(10, 2), nullable=False)  # Numeric evita errores de flotante
    fecha        = db.Column(db.Date, default=date.today, nullable=False)
    nota         = db.Column(db.String(255), nullable=True)
    metodo_pago  = db.Column(db.String(20), nullable=True)    # "efectivo" / "digital" / None
    fecha_creacion = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Transaccion {self.tipo} {self.monto} el {self.fecha}>"


class Presupuesto(db.Model):
    """Límite de gasto mensual por categoría para un usuario."""
    __tablename__ = "presupuestos"

    id            = db.Column(db.Integer, primary_key=True)
    usuario_id    = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    categoria_id  = db.Column(db.Integer, db.ForeignKey("categorias.id"), nullable=False)
    monto_limite  = db.Column(db.Numeric(10, 2), nullable=False)

    # Unicidad: solo un presupuesto por categoría por usuario
    __table_args__ = (
        db.UniqueConstraint("usuario_id", "categoria_id", name="uq_presupuesto_usuario_categoria"),
    )

    categoria = db.relationship("Categoria", backref=db.backref("presupuesto_obj", uselist=False))

    def __repr__(self):
        return f"<Presupuesto cat={self.categoria_id} limite={self.monto_limite}>"


class TransaccionProgramada(db.Model):
    """
    Transacción recurrente o futura pendiente de confirmación.

    frecuencia:
      'una_vez'   — ocurre una sola vez en proxima_fecha
      'mensual'   — se repite cada mes en el mismo día
      'quincenal' — se repite cada 15 días desde proxima_fecha

    Flujo:
      1. El usuario crea la transacción con fecha futura (o la programa manualmente).
      2. Cuando proxima_fecha <= hoy, aparece como "pendiente" en el dashboard.
      3. El usuario confirma → se crea una Transaccion real y se avanza proxima_fecha.
         El usuario salta → no se crea transacción, se avanza proxima_fecha igualmente.
      4. Para 'una_vez', confirmar o saltar desactiva el registro (activa=False).
    """
    __tablename__ = "transacciones_programadas"

    id            = db.Column(db.Integer, primary_key=True)
    usuario_id    = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    categoria_id  = db.Column(db.Integer, db.ForeignKey("categorias.id"), nullable=False)

    tipo          = db.Column(db.String(10),  nullable=False)   # "gasto" / "ingreso"
    monto         = db.Column(db.Numeric(10, 2), nullable=False)
    metodo_pago   = db.Column(db.String(20),  nullable=False)   # "efectivo" / "digital"
    nota          = db.Column(db.String(255), nullable=True)

    frecuencia    = db.Column(db.String(20),  nullable=False, default="una_vez")
    proxima_fecha = db.Column(db.Date,        nullable=False)
    activa        = db.Column(db.Boolean,     default=True, nullable=False)
    fecha_creacion = db.Column(db.DateTime,   default=lambda: datetime.now(timezone.utc))

    categoria = db.relationship("Categoria", backref="programadas")

    def avanzar_fecha(self):
        """Calcula y asigna la próxima fecha según la frecuencia."""
        from dateutil.relativedelta import relativedelta
        if self.frecuencia == "mensual":
            self.proxima_fecha = self.proxima_fecha + relativedelta(months=1)
        elif self.frecuencia == "quincenal":
            self.proxima_fecha = self.proxima_fecha + timedelta(days=15)
        else:  # una_vez
            self.activa = False

    def __repr__(self):
        return f"<TransaccionProgramada {self.tipo} {self.monto} próxima={self.proxima_fecha}>"


class TokenRecuperacion(db.Model):
    """Token para recuperación de contraseña. Expira en 1 hora."""
    __tablename__ = "tokens_recuperacion"

    id             = db.Column(db.Integer, primary_key=True)
    usuario_id     = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    token          = db.Column(db.String(64), unique=True, nullable=False)
    expiracion     = db.Column(db.DateTime, nullable=False)
    usado          = db.Column(db.Boolean, default=False, nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @staticmethod
    def generar(usuario_id):
        """Crea un token nuevo de 32 bytes (64 hex) con 1 hora de vida."""
        # Invalida tokens anteriores del mismo usuario
        TokenRecuperacion.query.filter_by(usuario_id=usuario_id, usado=False).update({"usado": True})
        db.session.flush()

        token = TokenRecuperacion(
            usuario_id=usuario_id,
            token=secrets.token_hex(32),
            expiracion=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.session.add(token)
        db.session.flush()
        return token

    @property
    def expirado(self):
        return datetime.now(timezone.utc) > self.expiracion.replace(tzinfo=timezone.utc)

    def __repr__(self):
        return f"<TokenRecuperacion usuario={self.usuario_id} expirado={self.expirado}>"


# ─── Funciones auxiliares ─────────────────────────────────────────────────────

def crear_categorias_default(usuario):
    """Se llama justo después de crear un Usuario nuevo."""
    for nombre in CATEGORIAS_DEFAULT_GASTO:
        db.session.add(Categoria(usuario_id=usuario.id, nombre=nombre, tipo="gasto"))
    for nombre in CATEGORIAS_DEFAULT_INGRESO:
        db.session.add(Categoria(usuario_id=usuario.id, nombre=nombre, tipo="ingreso"))
    db.session.commit()


def crear_categoria_usuario(usuario_id, nombre, tipo):
    nombre = nombre.strip()
    if not nombre:
        return None, "El nombre de la categoria no puede estar vacio."
    if tipo not in ("gasto", "ingreso"):
        return None, "Tipo de categoria invalido."
    if Categoria.query.filter_by(usuario_id=usuario_id, nombre=nombre, tipo=tipo).first():
        return None, f"Ya tenes una categoria de {tipo} con ese nombre."
    categoria = Categoria(usuario_id=usuario_id, nombre=nombre, tipo=tipo)
    db.session.add(categoria)
    db.session.commit()
    return categoria, None


def eliminar_categoria_usuario(usuario_id, categoria_id):
    categoria = Categoria.query.filter_by(id=categoria_id, usuario_id=usuario_id).first()
    if categoria is None:
        return False, "Esa categoria no existe o no te pertenece."
    cantidad = Transaccion.query.filter_by(categoria_id=categoria.id).count()
    if cantidad > 0:
        return False, (
            f"No se puede eliminar '{categoria.nombre}' porque tiene "
            f"{cantidad} transaccion(es) asociada(s). "
            "Reasigna o eliminá esas transacciones primero."
        )
    programadas = TransaccionProgramada.query.filter_by(
        categoria_id=categoria.id, activa=True
    ).count()
    if programadas > 0:
        return False, (
            f"No se puede eliminar '{categoria.nombre}' porque tiene "
            f"{programadas} transaccion(es) programada(s) activa(s). "
            "Eliminá esas programadas primero."
        )
    db.session.delete(categoria)
    db.session.commit()
    return True, None


def limpiar_invitados_abandonados(dias):
    """
    Elimina cuentas de invitado que llevan más de `dias` días sin actividad.
    Usa ultima_actividad si está seteada, sino fecha_creacion.
    """
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    invitados = Usuario.query.filter(Usuario.es_invitado == True).all()  # noqa: E712

    eliminados = 0
    for inv in invitados:
        referencia = inv.ultima_actividad or inv.fecha_creacion
        # Normalizar a timezone-aware
        if referencia.tzinfo is None:
            referencia = referencia.replace(tzinfo=timezone.utc)
        if referencia < limite:
            db.session.delete(inv)
            eliminados += 1

    db.session.commit()
    return eliminados


def eliminar_datos_invitado(usuario_id):
    usuario = Usuario.query.filter_by(id=usuario_id, es_invitado=True).first()
    if usuario is None:
        return False
    db.session.delete(usuario)
    db.session.commit()
    return True
