# Dockerfile
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY . .

# Crear directorio para datos persistentes
RUN mkdir -p /app/data

# Variables de entorno por defecto
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=agent.py
ENV PYTHONPATH=/app

# Exponer puerto
EXPOSE 5000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Comando de inicio
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "10", "--timeout", "120", "agent:app"]