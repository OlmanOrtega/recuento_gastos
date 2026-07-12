# Documentación técnica

Explicación de cómo funciona internamente GastoFlow: su arquitectura, modelo de datos, cuentas de invitado, sistema de alertas y la API JWT.

## 1. Arquitectura general

La app está organizada en **blueprints de Flask**, cada uno responsable de una sección:

- `auth` — registro, login, invitados, logout.
- `dashboard` — resumen mensual y alertas.
- `transacciones` — alta, edición, historial, exportación CSV.
- `categorias` — gestión de categorías.
- `api` — API REST con JWT.

`app.py` los registra todos sobre una misma instancia de Flask, inicializa la base de datos con **Flask-SQLAlchemy**, y configura **Flask-Login** para manejar la sesión del usuario en las páginas web (no en la API, que usa su propio mecanismo).

La base de datos se determina por la variable de entorno `DATABASE_URL`: si no está definida, se usa SQLite local; si está definida (como ocurre en Docker), apunta a MySQL vía el driver PyMySQL.

## 2. Modelo de datos

Tres modelos principales, relacionados entre sí:

- **`Usuario`**: representa tanto cuentas registradas como invitados (`es_invitado`). Guarda el hash de la contraseña (nunca la contraseña en texto plano), usando las utilidades de hashing de Werkzeug.
- **`Categoria`**: pertenece a un usuario específico y tiene un `tipo` (`"gasto"` o `"ingreso"`). Cada usuario nuevo recibe un set de categorías por defecto (Comida, Transporte, Ocio, Servicios, Salud, Otros / Salario, Regalo, Otro ingreso) al crear su cuenta.
- **`Transaccion`**: un movimiento puntual de dinero, con `monto` (usando el tipo `Numeric`, no `Float`, para evitar errores de redondeo típicos de la aritmética de punto flotante al trabajar con dinero), `fecha`, `nota` y `metodo_pago` opcionales.

Una categoría no puede eliminarse si ya tiene transacciones asociadas — hay que reasignarlas o borrarlas primero, para no dejar transacciones "huérfanas" apuntando a una categoría inexistente.

## 3. Cuentas de invitado

La opción "Probar sin registrarme" no es un modo especial sin base de datos: crea un `Usuario` real marcado como `es_invitado=True`, sin email ni contraseña, con un nombre generado (`Invitado-xxxxxxxx`). Esto simplifica el resto del código, porque un invitado se comporta exactamente igual que un usuario registrado en todas las demás rutas — no hay que duplicar lógica.

Dos mecanismos de limpieza:

- **Automática**: en cada arranque del servidor, se eliminan los invitados cuya cuenta se creó hace más de `DIAS_VIDA_INVITADO` (7 días por defecto), sin importar si tuvieron actividad.
- **Manual**: el propio invitado puede pedir borrar sus datos en cualquier momento desde una acción explícita, lo que elimina inmediatamente su usuario y, en cascada, todas sus categorías y transacciones asociadas.

## 4. Sistema de alertas automáticas

Las alertas del dashboard son **reglas simples, no un modelo de machine learning**. Se calculan en `generar_alertas()` con dos criterios:

1. **Porcentaje gastado sobre los ingresos del mes**: si superás el 50%, 80% o 100% de tus ingresos en gastos, aparece una alerta con el umbral correspondiente.
2. **Aumento de gasto por categoría respecto al mes anterior**: si una categoría aumentó 20% o más respecto al mes anterior (y hubo gasto en esa categoría el mes anterior, para tener una base de comparación válida), se genera una alerta, mostrando como máximo las dos categorías con mayor aumento para no saturar al usuario. Algunas categorías (Transporte, Comida, Ocio, Servicios) tienen además un consejo asociado predefinido.

## 5. Historial: filtros y paginación

El historial de transacciones soporta filtrado combinado por año/mes, semana específica del mes, y categoría, todo vía query params (`/historial?anio=2026&mes=7&semana=2&categoria_id=3`). El cálculo de "semanas del mes" (`_calcular_semanas_del_mes`) determina los rangos de fecha de cada semana calendario (lunes a domingo) que caen dentro del mes, recortando la primera y última semana si empiezan o terminan en un mes distinto.

Existe también una ruta `/historial/data` que devuelve solo el fragmento HTML de la tabla de resultados (no la página completa), pensada para actualizarse dinámicamente vía JavaScript sin recargar toda la página al cambiar un filtro.

## 6. Exportación a CSV

`/exportar-csv` arma el archivo completamente **en memoria** (`io.StringIO`), sin escribir ningún archivo temporal en disco, y lo devuelve como respuesta HTTP con el header `Content-Disposition` para que el navegador lo descargue directamente.

## 7. API REST con JWT

La API (`api.py`) es un sistema de autenticación **separado y paralelo** al de la web:

- La web usa **cookies de sesión** vía Flask-Login (el navegador las maneja automáticamente).
- La API usa **JWT** (JSON Web Tokens): el cliente hace login o registro contra `/api/login` o `/api/registro`, recibe un token firmado, y debe enviarlo en cada request posterior en el header `Authorization: Bearer <token>`.

El token incluye el `usuario_id`, fecha de emisión (`iat`) y fecha de expiración (`exp`, 7 días por defecto), firmado con la misma `SECRET_KEY` de la aplicación usando el algoritmo HS256. El decorador `requiere_token` valida el token en cada request protegido, y si es válido, deja disponible al usuario autenticado en `g.usuario_actual` para el resto de la función de la vista.

Este diseño permite que un cliente externo (un script, una app móvil) consuma los datos de GastoFlow sin depender de un navegador con cookies.

## 8. Despliegue con Docker

`docker-compose.yml` levanta dos servicios:

- **`db`**: MySQL 8.0 oficial, con sus datos persistidos en un volumen de Docker (`db_data`) para que sobrevivan aunque el contenedor se borre o reconstruya.
- **`web`**: la app Flask, construida desde el `Dockerfile` de la carpeta, corriendo con **Gunicorn** (un servidor WSGI apto para producción, a diferencia del servidor de desarrollo que usa `python app.py` localmente).

El servicio `web` espera a que `db` esté realmente listo para aceptar conexiones (`condition: service_healthy`), no solo a que el contenedor haya arrancado — esto evita que Flask intente conectarse a una base de datos que todavía se está inicializando, algo que puede tardar varios minutos la primera vez que se crea el volumen de MySQL.
