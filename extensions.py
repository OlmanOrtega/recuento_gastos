"""
Extensiones Flask inicializadas sin app (patrón Application Factory).
Se importan desde app.py, auth.py, perfil.py, etc.
"""

from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

# CSRF: protege todos los formularios POST automáticamente.
# Los endpoints de la API REST quedan exentos en app.py con csrf.exempt(api_bp).
csrf = CSRFProtect()

# Rate limiter: por defecto usa storage en memoria, que no escala con múltiples
# workers de Gunicorn. Para producción con concurrencia real, configurar
# RATELIMIT_STORAGE_URI=redis://... en las variables de entorno.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],          # Sin límite global; se define por ruta
    storage_uri="memory://",
)

# Mail: solo activo si MAIL_SERVER está definido en las variables de entorno.
# Si no está configurado, el flujo de recuperación de contraseña muestra el
# enlace directamente en pantalla (útil para desarrollo local).
mail = Mail()
