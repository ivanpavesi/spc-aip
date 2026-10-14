# Immagine ufficiale Python 3.12 Slim (Linux / Debian)
FROM python:3.12-slim

# Evita la scrittura di file .pyc e abilita log non bufferizzati
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Installazione dipendenze di sistema necessarie per psycopg2 e compilatori
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Directory di lavoro
WORKDIR /app

# Copia del file delle dipendenze
COPY requirements.txt .

# Installazione dipendenze Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia del codice sorgente dell'applicazione
COPY . .

# Porta esposta
EXPOSE 8000

# Script di avvio: esegue uvicorn sulla porta dinamica di produzione
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
