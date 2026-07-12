# GastoFlow

Aplicación web para registrar y controlar gastos e ingresos personales, construida con **Flask**, **SQLAlchemy** y **Flask-Login**. Permite crear cuenta, o probar la app sin registrarse mediante una cuenta de invitado temporal.

## Captura

![Landing de GastoFlow mostrando un resumen de gastos e ingresos del mes](assets/landing.png)

## Descripción general

GastoFlow permite:

- Registrar transacciones de **gasto** o **ingreso**, cada una con categoría, fecha, monto, nota y método de pago.
- Ver un **dashboard mensual** con el total de ingresos, gastos, balance, y un desglose de gastos por categoría.
- Recibir **alertas automáticas** cuando el gasto del mes supera cierto porcentaje de los ingresos, o cuando una categoría aumentó notablemente respecto al mes anterior.
- Ver un **historial** de transacciones filtrable por mes, semana y categoría, con paginación.
- **Exportar** las transacciones a CSV.
- Gestionar **categorías** propias (crear, renombrar, eliminar).
- Entrar como **invitado**, sin necesidad de registrarse, con una cuenta temporal que se elimina automáticamente después de unos días de inactividad (o a pedido del propio usuario).
- Consumir los mismos datos vía una **API REST** autenticada con JWT, pensada para clientes externos (scripts, apps móviles, etc.), independiente del sistema de sesiones de la web.

[Documentación técnica detallada](DETALLES_TECNICOS.md)

## Requisitos

- Python 3.12
- Docker y Docker Compose (recomendado para correr con MySQL, igual que en producción)

### Dependencias de Python

```
Flask
Flask-SQLAlchemy
Flask-Login
PyJWT
PyMySQL
python-dotenv
gunicorn
```

## Instalación y uso

Hay dos formas de correr el proyecto: con Docker (recomendado, usa MySQL) o localmente (usa SQLite, más simple para desarrollo rápido).

### Opción 1: Con Docker (recomendado)

```bash
# Clonar el repositorio
git clone https://github.com/OlmanOrtega/recuento_gastos.git
cd recuento_gastos

# Levantar la base de datos MySQL y la app
docker compose up --build
```

La app queda disponible en [http://localhost:5000](http://localhost:5000). La primera vez, la inicialización de MySQL puede tardar unos minutos.

> Las credenciales de MySQL y la `SECRET_KEY` se toman de variables de entorno (`MYSQL_ROOT_PASSWORD`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `SECRET_KEY`), con valores por defecto pensados solo para desarrollo. Para un despliegue real, definí estas variables en un archivo `.env` con valores propios en vez de usar los valores por defecto.

### Opción 2: Localmente con SQLite

```bash
# Clonar el repositorio
git clone https://github.com/OlmanOrtega/recuento_gastos.git
cd recuento_gastos

# Crear un entorno virtual
python3.12 -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# Instalar dependencias
pip install -r requirements.txt

# Correr la app
python app.py
```

Sin la variable de entorno `DATABASE_URL` definida, la app usa automáticamente una base de datos SQLite local (`gastoflow.db`), sin necesidad de instalar ni configurar MySQL. La app queda disponible en [http://localhost:5000](http://localhost:5000).

## Estructura del proyecto

| Archivo | Responsabilidad |
|---|---|
| `app.py` | Punto de entrada: inicializa Flask, la base de datos y Flask-Login, y registra los blueprints. |
| `models.py` | Modelos de datos (`Usuario`, `Categoria`, `Transaccion`) y funciones auxiliares de creación/eliminación. |
| `auth.py` | Registro, login, cuentas de invitado y logout. |
| `dashboard.py` | Cálculo de totales del mes, datos para el gráfico y generación de alertas automáticas. |
| `transacciones.py` | Alta, edición, eliminación, historial filtrable/paginado y exportación a CSV de transacciones. |
| `categorias.py` | Gestión de categorías propias de cada usuario. |
| `api.py` | API REST con autenticación JWT, independiente del sistema de sesiones de la web. |
| `Dockerfile` / `docker-compose.yml` | Empaquetado de la app con Gunicorn y orquestación junto a MySQL. |

## Limitaciones conocidas

- Las alertas automáticas son reglas fijas (umbrales de porcentaje), no un modelo predictivo.
- Las cuentas de invitado se eliminan automáticamente después de un número fijo de días de creadas, sin importar si tuvieron actividad reciente.
- La API (JWT) y la web (cookies de sesión) son sistemas de autenticación completamente separados; un token de la API no sirve para autenticarse en las páginas HTML y viceversa.
