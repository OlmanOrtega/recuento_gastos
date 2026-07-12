# Imagen base: Python 3.12 en su version "slim" 
FROM python:3.12-slim

WORKDIR /app

#Copiamos primero solo requirements.txt (no todo el codigo todavia) para
#aprovechar el cache de capas de Docker: si despues cambias tu codigo
#pero no tus dependencias, Docker reusa esta capa en vez de reinstalar
#todo de cero en cada build - builds mucho mas rapidos durante desarrollo.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Ahora si copiamos el resto del codigo de la app.
COPY . .

EXPOSE 5000

#Gunicorn es un servidor WSGI pensado para produccion - mas robusto que
#el servidor de desarrollo de Flask (app.run()) que usamos al correr
#localmente con "python app.py". "app:app" le dice a Gunicorn: abri el
#archivo app.py e importa la variable de modulo llamada "app" (la
#definimos a nivel de modulo en app.py especificamente para esto).
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
