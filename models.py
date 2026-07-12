"""
Modelos de datos para GastoFlow? fatal ese nombre
"""

from datetime import datetime, date, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


#CATEGORIAS DEFAULT
#Estas son las categorias que se crean automaticamente para cada usuario
#nuevo (registrado o invitado) al momento de crear su cuenta/sesion.
CATEGORIAS_DEFAULT_GASTO = [
    "Comida",
    "Transporte",
    "Ocio",
    "Servicios",
    "Salud",
    "Otros",
]

CATEGORIAS_DEFAULT_INGRESO = [
    "Salario",
    "Regalo",
    "Otro ingreso",
]


class Usuario(UserMixin, db.Model):
    #Representa tanto usuarios registrados como usuarios invitados.
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    es_invitado = db.Column(db.Boolean, default=False, nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    #Relaciones: un usuario tiene muchas categorias y muchas transacciones
    categorias = db.relationship(
        "Categoria", backref="usuario", cascade="all, delete-orphan"
    )
    transacciones = db.relationship(
        "Transaccion", backref="usuario", cascade="all, delete-orphan"
    )

    def set_password(self, password_plano):
        """Genera el hash y lo guarda. Nunca guardamos la contrasena en texto plano."""
        self.password_hash = generate_password_hash(password_plano)

    def check_password(self, password_plano):
        """Compara una contrasena en texto plano contra el hash guardado."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password_plano)

    def __repr__(self):
        return f"<Usuario {self.id} - {self.nombre} ({'invitado' if self.es_invitado else 'registrado'})>"


class Categoria(db.Model):
    #Cada categoria pertenece a un usuario especifico
    __tablename__ = "categorias"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    nombre = db.Column(db.String(50), nullable=False)
    tipo = db.Column(db.String(10), nullable=False, default="gasto")  # "gasto" o "ingreso"

    transacciones = db.relationship("Transaccion", backref="categoria")

    def __repr__(self):
        return f"<Categoria {self.nombre} ({self.tipo}, usuario {self.usuario_id})>"


class Transaccion(db.Model):
    __tablename__ = "transacciones"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias.id"), nullable=False)

    tipo = db.Column(db.String(10), nullable=False)  # "gasto" o "ingreso"
    monto = db.Column(db.Numeric(10, 2), nullable=False)  # Numeric, no Float, para evitar errores de redondeo con dinero
    fecha = db.Column(db.Date, default=date.today, nullable=False)  # cuando ocurrio el gasto/ingreso
    nota = db.Column(db.String(255), nullable=True)
    metodo_pago = db.Column(db.String(20), nullable=True)  # "efectivo" / "digital" (universal para gasto e ingreso) / None
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)  # cuando se registro en el sistema

    def __repr__(self):
        return f"<Transaccion {self.tipo} {self.monto} el {self.fecha}>"


# FUNCION AUXILIAR: crear categorias default para un usuario nuevo
def crear_categorias_default(usuario):
    #Se llama justo despues de crear un Usuario nuevo
    for nombre in CATEGORIAS_DEFAULT_GASTO:
        db.session.add(Categoria(usuario_id=usuario.id, nombre=nombre, tipo="gasto"))
    for nombre in CATEGORIAS_DEFAULT_INGRESO:
        db.session.add(Categoria(usuario_id=usuario.id, nombre=nombre, tipo="ingreso"))
    db.session.commit()


#FUNCIONES AUXILIARES: crear y eliminar categorias, compartidas entre
#el flujo de "agregar transaccion" y la pantalla de gestion de categorias
def crear_categoria_usuario(usuario_id, nombre, tipo):

    nombre = nombre.strip()

    if not nombre:
        return None, "El nombre de la categoria no puede estar vacio."

    if tipo not in ("gasto", "ingreso"):
        return None, "Tipo de categoria invalido."

    ya_existe = Categoria.query.filter_by(usuario_id=usuario_id, nombre=nombre, tipo=tipo).first()
    if ya_existe:
        return None, f"Ya tenes una categoria de {tipo} con ese nombre."

    categoria = Categoria(usuario_id=usuario_id, nombre=nombre, tipo=tipo)
    db.session.add(categoria)
    db.session.commit()
    return categoria, None


def eliminar_categoria_usuario(usuario_id, categoria_id):
    #Elimina una categoria de un usuario, si no tiene transacciones asociadas
    categoria = Categoria.query.filter_by(id=categoria_id, usuario_id=usuario_id).first()
    if categoria is None:
        return False, "Esa categoria no existe o no te pertenece."

    cantidad_transacciones = Transaccion.query.filter_by(categoria_id=categoria.id).count()
    if cantidad_transacciones > 0:
        return False, (
            f"No se puede eliminar '{categoria.nombre}' porque tiene "
            f"{cantidad_transacciones} transaccion(es) asociada(s). "
            "Reasigna o elimina esas transacciones primero."
        )

    db.session.delete(categoria)
    db.session.commit()
    return True, None


# FUNCIONES: manejo de cuentas de invitado
def limpiar_invitados_abandonados(dias):
    limite = datetime.utcnow() - timedelta(days=dias)
    invitados_viejos = Usuario.query.filter(
        Usuario.es_invitado == True,  # noqa: E712 (comparacion explicita, mas clara aca que 'is True')
        Usuario.fecha_creacion < limite,
    ).all()

    for invitado in invitados_viejos:
        db.session.delete(invitado)
    db.session.commit()

    return len(invitados_viejos)


def eliminar_datos_invitado(usuario_id):
    usuario = Usuario.query.filter_by(id=usuario_id, es_invitado=True).first()
    if usuario is None:
        return False
    db.session.delete(usuario)
    db.session.commit()
    return True
