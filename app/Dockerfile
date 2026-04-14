FROM python:3.13.2-slim

# Setăm variabile de mediu pentru a preveni scrierea fișierelor .pyc 
# și pentru a vedea log-urile în timp real (fără buffering)
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Instalăm dependențele de sistem necesare pentru:
# 1. psycopg2 (libpq-dev, gcc)
# 2. pg_dump (postgresql-client)
RUN apt-get update && apt-get install -y postgresql-client && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiem fișierul de cerințe
COPY requirements.txt .

# Instalăm librăriile Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiem tot codul din folderul 'app' în container
COPY . .

# Expunem portul FastAPI
EXPOSE 8000

# Comanda de start - Asigură-te că main.py este în rădăcina folderului app
# Dacă main.py este în interior, calea trebuie să fie "app.main:app"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]