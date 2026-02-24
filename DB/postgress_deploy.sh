#!/bin/bash

# Script de instalación y configuración de PostgreSQL para sisagent
# chmod +x DB/postgress_deploy.sh
# sudo -E ./DB/postgress_deploy.sh 2>&1 | tee /tmp/postgres_install.log
# ===================================================================

# Cambiar al directorio del proyecto (donde está .env)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1

echo "🚀 Configurando PostgreSQL..."
echo "📁 Directorio de trabajo: $(pwd)"

# 1. Actualizar paquetes
echo "📦 Actualizando lista de paquetes..."
sudo apt-get update -qq

# 2. Instalar PostgreSQL (Ubuntu/Debian) si no está instalado
if ! command -v psql &> /dev/null; then
    echo "🔧 Instalando PostgreSQL..."
    sudo apt-get install -y postgresql postgresql-contrib
else
    echo "✅ PostgreSQL ya está instalado."
fi

# 3. Verificar que PostgreSQL esté corriendo
echo "✅ Verificando servicio PostgreSQL..."
sudo systemctl status postgresql --no-pager | head -5

# Asegurarse de que el servicio esté activo
sudo systemctl enable postgresql
sudo systemctl start postgresql

# 4. Instalar driver Python (opcional, si el script necesita verificar la conexión)
echo "📦 Instalando psycopg2-binary para verificación..."
if [ -d ".venv" ]; then
    .venv/bin/pip install psycopg2-binary -q
else
    python3 -m pip install psycopg2-binary -q
fi

# 5. Crear base de datos y usuario
echo "🗄️  Configurando base de datos..."

# 1. Cargar variables de entorno desde .env
# Esto lee el archivo .env e ignora comentarios (#)
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo "✅ Variables de entorno cargadas."
else
    echo "❌ Error: No se encontró el archivo .env"
    exit 1
fi

# 2. Configurar variables de conexión (usando las de agente.py)
# Si no están en el .env, usa valores por defecto
HOST="${DB_HOST:-localhost}"
# Para PostgreSQL local nativo, siempre usar puerto 5432 (no el del .env que es para Docker)
PORT="5432"
POSTGRES_USER="postgres"  # Usuario administrador de PostgreSQL
APP_USER="${DB_USER:-sisbot_user}"
APP_PASS="${DB_PASSWORD:-postgres_password}"
DBNAME="${DB_NAME_AGENT:-checkpointer_db}"

echo "🔄 Conectando a PostgreSQL local nativo ($HOST:$PORT)..."

# 3. Verificar si psql está disponible
if ! command -v psql &> /dev/null; then
    echo "❌ Error: No se encontró el comando 'psql' en este sistema."
    echo "   Asegúrate de que PostgreSQL esté instalado correctamente."
    exit 1
fi

# 4. Crear usuario si no existe
echo "👤 Creando usuario $APP_USER..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = '$APP_USER'" | grep -q 1 || \
sudo -u postgres psql -c "CREATE USER $APP_USER WITH PASSWORD '$APP_PASS';"

if [ $? -eq 0 ]; then
    echo "✅ Usuario $APP_USER creado o ya existe."
else
    echo "❌ Error creando usuario."
    exit 1
fi

# 5. Crear base de datos si no existe
echo "🗄️  Creando base de datos $DBNAME..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '$DBNAME'" | grep -q 1 || \
sudo -u postgres psql -c "CREATE DATABASE $DBNAME OWNER $APP_USER;"

if [ $? -eq 0 ]; then
    echo "✅ Base de datos $DBNAME creada o ya existe."
else
    echo "❌ Error creando base de datos."
    exit 1
fi

# 6. Otorgar permisos al usuario
echo "🔐 Otorgando permisos a $APP_USER..."
sudo -u postgres psql -d "$DBNAME" -c "
GRANT ALL PRIVILEGES ON DATABASE $DBNAME TO $APP_USER;
GRANT ALL PRIVILEGES ON SCHEMA public TO $APP_USER;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $APP_USER;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $APP_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $APP_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $APP_USER;
"

if [ $? -eq 0 ]; then
    echo "✅ Permisos otorgados exitosamente."
else
    echo "❌ Error otorgando permisos."
    exit 1
fi

# 6a. Configurar pg_hba.conf para permitir conexiones con password
echo "🔧 Configurando autenticación PostgreSQL..."
PG_VERSION=$(psql --version | awk '{print $3}' | cut -d. -f1)
PG_HBA_FILE="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"

if [ -f "$PG_HBA_FILE" ]; then
    # Backup del archivo original
    sudo cp "$PG_HBA_FILE" "$PG_HBA_FILE.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Agregar regla para conexiones localhost con password (si no existe)
    if ! sudo grep -q "host.*all.*all.*127.0.0.1/32.*scram-sha-256" "$PG_HBA_FILE"; then
        echo "Agregando regla de autenticación para conexiones locales..."
        sudo sed -i "/^# IPv4 local connections:/a host    all             all             127.0.0.1/32            scram-sha-256" "$PG_HBA_FILE"
    fi
    
    # Recargar configuración
    sudo systemctl reload postgresql
    echo "✅ Configuración de autenticación actualizada."
else
    echo "⚠️  Advertencia: No se encontró pg_hba.conf en $PG_HBA_FILE"
fi


# 7. Verificar conexión
echo "🔍 Verificando conexión..."
if [ -d ".venv" ]; then
    PYTHON_BIN=".venv/bin/python3"
else
    PYTHON_BIN="python3"
fi

$PYTHON_BIN -c "import psycopg2; conn = psycopg2.connect(host='$HOST', port=$PORT, database='$DBNAME', user='$APP_USER', password='$APP_PASS', connect_timeout=5); print('✅ Conexión a PostgreSQL exitosa'); conn.close()" 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Conexión verificada exitosamente"
else
    echo "❌ Error en la conexión - verifica las credenciales"
fi

echo ""
echo "✅ PostgreSQL instalado y configurado correctamente"
echo ""
echo "📋 Credenciales:"
echo "   Host: $HOST"
echo "   Puerto: $PORT (PostgreSQL local nativo)"
echo "   Base de datos: $DBNAME"
echo "   Usuario: $APP_USER"
echo "   Password: $APP_PASS"
echo ""
echo "💡 Para conectarte manualmente: psql -h $HOST -p $PORT -U $APP_USER -d $DBNAME"
echo ""
echo "⚠️  IMPORTANTE: Para usar PostgreSQL local en lugar de Docker:"
echo "   1. Actualiza el archivo .env:"
echo "      DB_PORT=5432   (cambiar de 5433 a 5432)"
echo "   2. Detén el contenedor Docker de PostgreSQL si está corriendo"
echo "   3. Reinicia tu aplicación"