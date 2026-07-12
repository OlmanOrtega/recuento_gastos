"""
Main del app — Application Factory
"""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, session
from flask_login import LoginManager, current_user

from models import db, Usuario, limpiar_invitados_abandonados
from extensions import csrf, limiter, mail
from auth import auth_bp
from dashboard import dashboard_bp
from transacciones import transacciones_bp
from categorias import categorias_bp
from api import api_bp
from perfil import perfil_bp
from presupuestos import presupuestos_bp
from programadas import programadas_bp

load_dotenv()

DIAS_VIDA_INVITADO = 7
# Throttle para actualizar ultima_actividad: solo escribimos a DB si han
# pasado más de 1 hora desde la última vez que lo hicimos en esta sesión.
_INTERVALO_ACTIVIDAD = timedelta(hours=1)


def _migrar_schema(db):
    """
    Migración manual liviana: solo ADD COLUMN para columnas nuevas en tablas existentes.
    Las tablas nuevas las crea db.create_all() antes de llegar aquí.
    Idempotente — si la columna ya existe, falla silenciosamente.
    Compatible con SQLite y PostgreSQL.
    """
    # Solo ALTER TABLE — db.create_all() ya se encargó de crear tablas nuevas.
    alter_columns = [
        "ALTER TABLE usuarios ADD COLUMN ultima_actividad DATETIME",
    ]
    with db.engine.connect() as conn:
        for sql in alter_columns:
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except Exception:
                conn.rollback()


def crear_app():
    app = Flask(__name__)
<<<<<<< Updated upstream
    #DATABASE_URL: si no esta definida, usa SQLite local. Si esta definida (por ejemplo en Docker), apunta a MySQL.
    # Render entrega la cadena de conexion con el prefijo "postgres://",
    # pero las versiones modernas de SQLAlchemy (1.4+) exigen
    # "postgresql://". Sin este ajuste, la app tira un error al conectar
    # a la base de datos en Render, aunque localmente nunca se nota.
    database_url = os.environ.get("DATABASE_URL", "sqlite:///gastoflow.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
=======

    # Render pasa DATABASE_URL con prefijo "postgres://" (viejo),
    # SQLAlchemy 1.4+ requiere "postgresql://". Se corrige automáticamente.
    _db_url = os.environ.get("DATABASE_URL", "sqlite:///gastoflow.db")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
>>>>>>> Stashed changes
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "clave-de-desarrollo-local-no-se-usa-en-produccion"
    )
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=DIAS_VIDA_INVITADO)

    # Flask-Mail (opcional — solo activo si MAIL_SERVER está en el entorno)
    app.config["MAIL_SERVER"]   = os.environ.get("MAIL_SERVER")
    app.config["MAIL_PORT"]     = int(os.environ.get("MAIL_PORT", 587))
    app.config["MAIL_USE_TLS"]  = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
    app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@gastoflow.app")

    # Inicializar extensiones
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    # La API usa JWT, no CSRF
    csrf.exempt(api_bp)

    # Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def cargar_usuario(usuario_id):
        return db.session.get(Usuario, int(usuario_id))

    # Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(transacciones_bp)
    app.register_blueprint(categorias_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(perfil_bp)
    app.register_blueprint(presupuestos_bp)
    app.register_blueprint(programadas_bp)

    # Landing
    @app.route("/")
    def landing():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return render_template("landing.html")

    # Errores personalizados
    @app.errorhandler(404)
    def pagina_no_encontrada(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def error_interno(e):
        return render_template("errors/500.html"), 500

    # Actualizar ultima_actividad para invitados (throttled a 1 vez/hora)
    @app.before_request
    def actualizar_actividad():
        if not current_user.is_authenticated or not current_user.es_invitado:
            return
        ahora = datetime.now(timezone.utc)
        ultima = session.get("_ultima_actividad_ts")
        if ultima is None or (ahora - datetime.fromtimestamp(ultima, tz=timezone.utc)) > _INTERVALO_ACTIVIDAD:
            current_user.ultima_actividad = ahora
            db.session.commit()
            session["_ultima_actividad_ts"] = ahora.timestamp()

    with app.app_context():
        db.create_all()
        _migrar_schema(db)
        limpiar_invitados_abandonados(dias=DIAS_VIDA_INVITADO)

    return app


app = crear_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
