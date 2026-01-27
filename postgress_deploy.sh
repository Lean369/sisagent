#!/bin/bash

# Script de instalación y configuración de PostgreSQL para sisagent

# cd /home/leanusr/sisagent && ./postgress_deploy.sh
# ===================================================================

echo "🚀 Instalando PostgreSQL..."

# 1. Actualizar paquetes
sudo apt-get update

# 2. Instalar PostgreSQL (Ubuntu/Debian)
sudo apt-get install -y postgresql postgresql-contrib

# 3. Verificar que PostgreSQL esté corriendo
echo "✅ Verificando servicio PostgreSQL..."
sudo systemctl status postgresql --no-pager

# 4. Instalar driver Python
echo "📦 Instalando psycopg2-binary..."
python3 -m pip install psycopg2-binary

# 5. Crear base de datos y usuario
echo "🗄️  Configurando base de datos..."

sudo -u postgres psql -c "CREATE DATABASE metrics_db;" 2>&1 || echo "⚠️  Base de datos ya existe"
sudo -u postgres psql -c "CREATE USER sisbot_user WITH PASSWORD 'postgres_password';" 2>&1 || echo "⚠️  Usuario ya existe"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE metrics_db TO sisbot_user;" 2>&1

sudo -u postgres psql -c "CREATE DATABASE checkpointer_db OWNER sisbot_user;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE checkpointer_db TO sisbot_user;"

# 6. Otorgar permisos en schema public (necesario para crear tablas)
echo "🔐 Otorgando permisos en schema public..."
sudo -u postgres psql -d metrics_db -c "GRANT ALL ON SCHEMA public TO sisbot_user;" 2>&1
sudo -u postgres psql -d checkpointer_db -c "GRANT ALL ON SCHEMA public TO sisbot_user;" 2>&1

 7. Verificar conexión
echo "🔍 Verificando conexión..."
python3 -c "import psycopg2; conn = psycopg2.connect(host='localhost', database='metrics_db', user='sisbot_user', password='postgres_password'); print('✅ Conexión a PostgreSQL exitosa'); conn.close()" || echo "❌ Error en la conexión"
echo ""
echo "✅ PostgreSQL instalado y configurado correctamente"
echo ""
echo "📋 Credenciales:"
echo "   Host: localhost"
echo "   Puerto: 5432"
echo "   Base de datos: metrics_db"
echo "   Usuario: sisbot_user"
echo "   Password: postgres_password"
echo ""
echo "💡 Para conectarte manualmente: psql -h localhost -U sisbot_user -d metrics_db"