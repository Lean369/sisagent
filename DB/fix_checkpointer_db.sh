#!/bin/bash
# chmod +x fix_checkpointer_db.sh
# ./fix_checkpointer_db.sh

# ==========================================
# Script de Inicialización de Métricas DB
# ==========================================

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
PORT="${DB_PORT:-5432}"
USER="${DB_USER:-postgres}"
DBNAME="${DB_NAME_AGENT:-checkpointer_db}"

# Nota: PGPASSWORD es la variable de entorno que psql busca para la contraseña
export PGPASSWORD="${DB_PASSWORD}"

echo "🔄 Conectando a PostgreSQL ($HOST:$PORT/$DBNAME)..."

# 3. Definir el comando SQL
SQL_COMMANDS="
ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
CREATE INDEX IF NOT EXISTS idx_checkpoints_created_at ON checkpoints (created_at);
"
# 4. Ejecutar comando en Docker o Localmente
# Detectamos si tenemos el comando psql instalado
if command -v psql &> /dev/null; then
    psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DBNAME" -c "$SQL_COMMANDS"
    
    if [ $? -eq 0 ]; then
        echo "✅ Tabla 'checkpoints' fixeada exitosamente."
    else
        echo "🔴 Error ejecutando SQL."
        exit 1
    fi
else
    echo "⚠️  No se encontró el comando 'psql' en este sistema."
    echo "   Si estás usando Docker, ejecuta este script DENTRO del contenedor de postgres o usa:"
    echo "   docker exec -it <nombre_container_db> psql -U $USER -d $DBNAME -c \"$SQL_COMMANDS\""
fi