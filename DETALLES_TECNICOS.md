# Documentación técnica

Explicación de cómo funciona internamente GastoFlow: arquitectura, modelo de datos, seguridad, sistema de alertas, transacciones programadas, presupuestos, API y despliegue.

## 1. Arquitectura general

La app usa el patrón **Application Factory** (`crear_app()` en `app.py`): la instancia de Flask se crea dentro de una función, no a nivel de módulo. Esto facilita la configuración por entorno (producción vs. tests vs. desarrollo) sin importar código al nivel de módulo.

Los blueprints organizan el código por dominio:

- `auth` — registro, login, invitados, logout, recuperación de contraseña.
- `dashboard` — resumen mensual, gráfico por método de pago, alertas de gasto y presupuesto.
- `transacciones` — alta, edición, historial filtrado/paginado, totales, exportación CSV.
- `programadas` — transacciones futuras y recurrentes.
- `presupuestos` — límites de gasto por categoría.
- `perfil` — cambiar nombre, email y contraseña.
- `categorias` — gestión de categorías propias.
- `api` — API REST con JWT (autenticación separada de la web).

Las extensiones (`CSRFProtect`, `Limiter`, `Mail`) se instancian en `extensions.py` sin atar a ninguna app, y se inicializan con `init_app(app)` dentro de `crear_app()`. Esto evita el problema de importaciones circulares entre blueprints que necesitan esas extensiones.

La base de datos se determina por la variable de entorno `DATABASE_URL`:
- Sin definir → SQLite local (`gastoflow.db`), para desarrollo.
- Definida (Render la inyecta automáticamente) → PostgreSQL. La app corrige el prefijo `postgres://` → `postgresql://` porque Render usa el formato viejo que SQLAlchemy 1.4+ ya no acepta.

## 2. Modelo de datos

Seis modelos principales:

**`Usuario`** — representa tanto cuentas registradas como invitados (`es_invitado`). Nunca guarda la contraseña en texto plano: usa `generate_password_hash` / `check_password_hash` de Werkzeug. El campo `ultima_actividad` registra la última vez que un invitado interactuó con la app, para extender su plazo de vida desde la actividad (no solo desde la creación de la cuenta).

**`Categoria`** — pertenece a un usuario, tiene `tipo` (`"gasto"` o `"ingreso"`). Cada usuario nuevo recibe categorías por defecto al registrarse. No puede eliminarse si tiene transacciones o programadas activas asociadas — la restricción se enforcea en `eliminar_categoria_usuario()` antes de tocar la base de datos.

**`Transaccion`** — un movimiento puntual con `monto` de tipo `Numeric(10,2)` (no `Float`) para evitar errores de redondeo en aritmética de punto flotante. Incluye `metodo_pago` (`"efectivo"` / `"digital"`), que es obligatorio al crear una transacción nueva pero puede ser `NULL` en datos pre-existentes.

**`TransaccionProgramada`** — una transacción futura o recurrente. Tiene `frecuencia` (`"una_vez"`, `"mensual"`, `"quincenal"`), `proxima_fecha` y un flag `activa`. El método `avanzar_fecha()` calcula la siguiente ocurrencia usando `relativedelta` (para meses, maneja correctamente los fin de mes) o `timedelta(days=15)` para quincenal. Al confirmar una programada, se crea una `Transaccion` real y se avanza la fecha. Al saltar, solo se avanza la fecha.

**`Presupuesto`** — un límite de gasto mensual para una categoría de un usuario. Restricción `UNIQUE(usuario_id, categoria_id)` en la base de datos: solo un presupuesto por categoría. El progreso se calcula dinámicamente al mostrar la vista (suma de `Transaccion` del mes para esa categoría), no se persiste.

**`TokenRecuperacion`** — token de 64 hex chars (32 bytes) para recuperación de contraseña. Expira en 1 hora. Al generar uno nuevo, se invalidan los tokens anteriores del mismo usuario para evitar tokens múltiples activos.

## 3. Seguridad

**CSRF**: `Flask-WTF` protege todos los formularios HTML con tokens CSRF. La API (`api_bp`) está exenta explícitamente (`csrf.exempt(api_bp)`) porque usa JWT en vez de cookies. Las peticiones AJAX del frontend usan un `fetch()` parcheado globalmente en `base.html` que inyecta el header `X-CSRFToken` automáticamente en todos los métodos no-GET, leyendo el token de un `<meta name="csrf-token">` en el `<head>`.

**Rate limiting**: `Flask-Limiter` limita los intentos en las rutas de autenticación (10 intentos/minuto en login, 20 en registro). El almacenamiento es en memoria (`memory://`), suficiente para una instancia única.

**Contraseñas**: mínimo 8 caracteres, hasheadas con `pbkdf2:sha256` de Werkzeug. Nunca se almacena texto plano.

## 4. Cuentas de invitado

"Probar sin registrarme" crea un `Usuario` real con `es_invitado=True`, sin email ni contraseña. Esto simplifica el resto del código: un invitado se comporta igual que un registrado en todas las demás rutas, no hay lógica duplicada.

La limpieza automática (`limpiar_invitados_abandonados()`) se ejecuta en cada arranque de la app. Usa `ultima_actividad` si está seteada, sino `fecha_creacion`, para que los invitados que volvieron a usar la app cuenten el plazo desde su última visita. El campo `ultima_actividad` se actualiza máximo una vez por hora por sesión (throttle via `session["_ultima_actividad_ts"]`) para no escribir a la base de datos en cada request.

## 5. Sistema de alertas

Las alertas del dashboard se generan en `dashboard.py` concatenando dos funciones:

**`alertas_presupuesto()`** — revisa cada presupuesto definido y avisa cuando el gasto del mes supera el 80% o el 100% del límite. Se ejecuta primero, aparecen al inicio de la lista de alertas.

**`generar_alertas()`** — dos reglas adicionales:
1. Porcentaje de ingresos gastados (avisa en 50%, 80% y 100%).
2. Categorías que aumentaron 20%+ respecto al mes anterior. Muestra máximo 2 para no saturar. Algunas categorías tienen además un consejo predefinido asociado.

## 6. Transacciones programadas

El flujo parte del formulario de agregar transacción: si la fecha elegida es futura, el JS client-side revela la sección de frecuencia y cambia el texto del botón a "Programar". En el servidor, `transacciones.nueva()` verifica si `fecha > date.today()` y crea una `TransaccionProgramada` en vez de una `Transaccion`.

Las programadas pendientes (cuya `proxima_fecha <= hoy`) aparecen en el dashboard con botones Confirmar / Saltar que se manejan vía AJAX. Al desaparecer todas, el panel se elimina del DOM sin recargar la página.

Si una programada lleva varias ocurrencias atrasadas, el badge de "Pendiente" muestra el número estimado de ocurrencias acumuladas (calculado en Python con `_ocurrencias_atrasadas()`).

## 7. Historial: filtros y paginación

El historial soporta filtrado combinado por año/mes, semana, categoría y método de pago. Todos los filtros se comunican vía query params y se actualizan dinámicamente vía `fetch()` sin recargar la página — la ruta `/historial/data` devuelve solo el fragmento HTML del contenido, no la página completa.

Antes de paginar, la query calcula subtotales de gastos e ingresos del filtro activo (usando `SUM` con `CASE WHEN`) para mostrar el resumen encima de la lista.

El cálculo de semanas del mes (`_calcular_semanas_del_mes`) determina rangos lunes-domingo que caen dentro del mes, recortando la primera y última si cruzan a otro mes.

## 8. Exportación a CSV

`/exportar-csv` construye el archivo completamente en memoria con `io.StringIO`, sin escribir a disco. Respeta todos los filtros activos incluyendo método de pago. Lo devuelve como respuesta HTTP con `Content-Disposition: attachment` para descarga directa.

## 9. API REST con JWT

La API es un sistema de autenticación paralelo e independiente de la web:

- La web usa **cookies de sesión** vía Flask-Login.
- La API usa **JWT**: el cliente hace login contra `/api/login`, recibe un token firmado con `SECRET_KEY` (algoritmo HS256, expiración 7 días), y lo envía en `Authorization: Bearer <token>` en cada request protegido.

El decorador `requiere_token` valida el token y deja al usuario disponible en `g.usuario_actual`. La API está exenta de CSRF porque no usa cookies.

## 10. Despliegue en Render

`render.yaml` describe toda la infraestructura como código:

```
services:
  web (Docker, plan free, port 5000)
    envVars:
      SECRET_KEY: generada automáticamente por Render
      DATABASE_URL: inyectada desde la base de datos definida abajo

databases:
  gastoflow-db (PostgreSQL, plan free)
```

El flujo de deploy:
1. Render lee `render.yaml` y crea el servicio web + la base de datos PostgreSQL.
2. Construye la imagen Docker desde el `Dockerfile` (Python 3.12 slim + Gunicorn).
3. Inyecta `DATABASE_URL` y `SECRET_KEY` automáticamente como variables de entorno.
4. Al arrancar, `crear_app()` corre `db.create_all()` (crea tablas nuevas) seguido de `_migrar_schema()` (agrega columnas nuevas a tablas existentes, idempotente).

> El plan gratuito de PostgreSQL en Render expira a los 90 días. Hay que recrear la base o migrar a un plan pago antes de esa fecha.

El `Dockerfile` es el mismo que el prototipo Docker — Render lo reutiliza directamente para construir la imagen de producción.

---

## 11. Diferencias con el prototipo Docker

El branch `docker-prototype` es el primer prototipo funcional. Esta versión (`main`) lo supera en todas las dimensiones. Las diferencias principales:

### Infraestructura y base de datos

| | Prototipo Docker | Versión Render (main) |
|---|---|---|
| **Orquestación** | `docker-compose.yml` (local) | `render.yaml` (Render cloud) |
| **Base de datos prod** | MySQL 8.0 (contenedor local) | PostgreSQL (Render managed) |
| **Base de datos dev** | MySQL (vía Docker) | SQLite (sin configuración extra) |
| **Driver Python** | PyMySQL | psycopg2-binary |
| **Persistencia** | Volumen Docker local | Render PostgreSQL (cloud) |
| **Deploy** | Manual, solo local | `git push` → auto-deploy en Render |

En el prototipo, correr localmente requería Docker instalado y esperar a que MySQL inicializara (~2 min la primera vez). En la versión actual, `python app.py` arranca en segundos con SQLite.

### Modelos de datos nuevos

| Modelo | Prototipo | Main |
|---|---|---|
| `Usuario` | ✓ (sin `ultima_actividad`) | ✓ (con `ultima_actividad`) |
| `Categoria` | ✓ | ✓ |
| `Transaccion` | ✓ (sin `metodo_pago`) | ✓ (con `metodo_pago`) |
| `TransaccionProgramada` | ✗ | ✓ |
| `Presupuesto` | ✗ | ✓ |
| `TokenRecuperacion` | ✗ | ✓ |

### Funcionalidades nuevas

Ninguna de estas existe en el prototipo:

- Transacciones programadas (futuras y recurrentes mensual/quincenal)
- Presupuestos por categoría con progreso mensual y alertas en dashboard
- Método de pago obligatorio (efectivo/digital) en cada transacción
- Filtro por método de pago en historial y gráfico del dashboard
- Totales de gastos/ingresos del filtro activo en historial
- Recuperación de contraseña por email (con token de 1 hora)
- Gestión de perfil (nombre, email, contraseña)
- Modo claro/oscuro con paleta violeta/verde, persistido en localStorage
- UI glassmorphism con Phosphor Icons y fuente Outfit
- Protección CSRF en todos los formularios (Flask-WTF)
- Rate limiting en rutas de autenticación (Flask-Limiter)
- Migración de schema automática e idempotente al iniciar

### Seguridad

El prototipo no tenía CSRF, rate limiting ni recuperación de contraseña. En la versión actual:
- `Flask-WTF` protege todos los formularios HTML
- `Flask-Limiter` limita intentos de login y registro
- Los tokens de recuperación expiran en 1 hora y se invalidan al generar uno nuevo
- Las contraseñas tienen mínimo 8 caracteres

### Lo que se mantuvo igual

- Application Factory pattern (`crear_app()`)
- Sistema de blueprints
- Cuentas de invitado con limpieza automática
- API REST con JWT
- `Numeric(10,2)` para montos (evita errores de float)
- Gunicorn como servidor WSGI
- El `Dockerfile` es prácticamente idéntico
