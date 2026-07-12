"""
Main del app
Inicializa Flask + SQLAlchemy + Flask-Login, crea las tablas, y
registra los blueprints de cada seccion de la app.
"""

import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for
from flask_login import LoginManager, current_user
from models import db, Usuario, limpiar_invitados_abandonados
from auth import auth_bp
from dashboard import dashboard_bp
from transacciones import transacciones_bp
from categorias import categorias_bp
from api import api_bp

#Determina cuando dura una sesion de invitado en la bd
DIAS_VIDA_INVITADO = 7


def crear_app():
    app = Flask(__name__)
    #DATABASE_URL: si no esta definida, usa SQLite local. Si esta definida (por ejemplo en Docker), apunta a MySQL.
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///gastoflow.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    #SECRET_KEY que se encuentra definida acá solo por si alguien ejecuta la app localmente
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "clave-de-desarrollo-local-no-se-usa-con-docker-o-render"
    )

    #Duracion de la cookie de sesion cuando se marca session.permanent = True
    #Sin esto, la cookie de sesion depende del comportamiento del navegador al cerrarse, que
    #es inconsistente entre navegadores y configuraciones
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=DIAS_VIDA_INVITADO)

    db.init_app(app)

    #Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"  #donde redirige si alguien intenta entrar sin sesion
    login_manager.init_app(app)

    @login_manager.user_loader
    def cargar_usuario(usuario_id):
        #Flask-Login llama esta funcion para saber quien es el usuario logueado
        return db.session.get(Usuario, int(usuario_id))

    #Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(transacciones_bp)
    app.register_blueprint(categorias_bp)
    app.register_blueprint(api_bp)

    #Landing
    @app.route("/")
    def landing():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return render_template("landing.html")

    with app.app_context():
        db.create_all()  #crea las tablas si no existen todavia

        #Limpieza de invitados abandonados aprovechamos cada arranque
        #del servidor para barrer las cuentas de invitado mas viejas 
        limpiar_invitados_abandonados(dias=DIAS_VIDA_INVITADO)

    return app


#App a nivel de módulo para Gunicorn (producción)
app = crear_app()

if __name__ == "__main__":
    # host="0.0.0.0" hace que el servidor acepte conexiones desde otros
    # dispositivos en la misma red local
    app.run(host="0.0.0.0", port=5000, debug=True)
