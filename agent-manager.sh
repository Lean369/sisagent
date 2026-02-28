#!/bin/bash
# Script para gestionar el agente de Python
# cd /home/leanusr/sisagent && ./agent-manager.sh restart
# sleep 3 && cd /home/leanusr/sisagent && ./agent-manager.sh status

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="./.venv/bin/python"
#AGENT_SCRIPT="agent.py"
AGENT_SCRIPT="app.py"
LOG_FILE="logs/sisagent_verbose.log"
PID_FILE="agent.pid"

# Cargar variables de entorno desde .env
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Obtener APP_PORT del .env o usar default
APP_PORT=${APP_PORT:-5000}

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función para obtener PID del agente
get_agent_pid() {
    pgrep -f "python.*$AGENT_SCRIPT" | head -1
}

# Función para verificar si el agente está corriendo
is_running() {
    local pid=$(get_agent_pid)
    if [ -n "$pid" ]; then
        return 0
    else
        return 1
    fi
}

# Función para iniciar el agente
start() {
    echo "🚀 Iniciando agente..."
    
    if is_running; then
        echo -e "${YELLOW}⚠️  El agente ya está corriendo (PID: $(get_agent_pid))${NC}"
        return 1
    fi
    
    # Verificar que existe el virtualenv
    if [ ! -f "$PYTHON_BIN" ]; then
        echo -e "${RED}❌ Error: No se encontró $PYTHON_BIN${NC}"
        echo "   Ejecuta: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
        return 1
    fi
    
    # Verificar que existe .env
    if [ ! -f ".env" ]; then
        echo -e "${YELLOW}⚠️  Advertencia: No se encontró .env${NC}"
        echo "   Copia .env.example y configura las variables"
    fi
    
    # Iniciar el agente en modo
    nohup $PYTHON_BIN $AGENT_SCRIPT > /dev/null 2>&1 &
    #nohup $PYTHON_BIN $AGENT_SCRIPT >> $LOG_FILE 2>&1 &
    local pid=$!
    
    # Esperar un momento para verificar que se inició
    sleep 5
    
    if is_running; then
        echo $pid > $PID_FILE
        echo -e "${GREEN}✅ Agente iniciado correctamente (PID: $pid)${NC}"
        
        # Verificar health endpoint
        if curl -s http://localhost:${APP_PORT}/health >/dev/null 2>&1; then
            echo -e "${GREEN}✅ Health check OK (puerto ${APP_PORT})${NC}"
        else
            echo -e "${YELLOW}⚠️  El agente está corriendo pero no responde en puerto ${APP_PORT}${NC}"
            echo "   Revisa: tail -f $LOG_FILE"
        fi
        return 0
    else
        echo -e "${RED}❌ Error al iniciar el agente${NC}"
        echo "   Revisa: tail -20 $LOG_FILE"
        return 1
    fi
}

# Función para detener el agente
stop() {
    echo "🛑 Deteniendo agente..."
    
    if ! is_running; then
        echo -e "${YELLOW}⚠️  El agente no está corriendo${NC}"
        return 1
    fi
    
    local pid=$(get_agent_pid)
    echo "   Terminando proceso PID: $pid"
    
    # Intentar detener gracefully
    kill $pid 2>/dev/null
    
    # Esperar hasta 5 segundos
    for i in {1..5}; do
        if ! is_running; then
            echo -e "${GREEN}✅ Agente detenido correctamente${NC}"
            rm -f $PID_FILE
            return 0
        fi
        sleep 1
    done
    
    # Si no se detuvo, forzar
    echo "   Forzando terminación..."
    kill -9 $pid 2>/dev/null
    sleep 1
    
    if ! is_running; then
        echo -e "${GREEN}✅ Agente detenido (forzado)${NC}"
        rm -f $PID_FILE
        return 0
    else
        echo -e "${RED}❌ No se pudo detener el agente${NC}"
        return 1
    fi
}

# Función para reiniciar el agente
restart() {
    echo "🔄 Reiniciando agente..."
    stop
    sleep 2
    start
}

# Función para mostrar el estado
status() {
    if is_running; then
        local pid=$(get_agent_pid)
        echo -e "${GREEN}✅ Agente corriendo${NC}"
        echo "   PID: $pid"
        echo "   Puerto: $APP_PORT (Flask)"
        
        # Mostrar uso de memoria
        local mem=$(ps -p $pid -o rss= 2>/dev/null)
        if [ -n "$mem" ]; then
            local mem_mb=$((mem / 1024))
            echo "   Memoria: ${mem_mb} MB"
        fi
        
        # Verificar health
        if curl -s http://localhost:${APP_PORT}/health >/dev/null 2>&1; then
            echo -e "   Health: ${GREEN}OK${NC}"
        else
            echo -e "   Health: ${RED}NO RESPONDE${NC}"
        fi
        
        # Mostrar últimas líneas del log
        echo ""
        echo "📋 Últimas líneas del log:"
        tail -5 $LOG_FILE
        
    else
        echo -e "${RED}❌ Agente no está corriendo${NC}"
        
        # Verificar si hay un log reciente con errores
        if [ -f "$LOG_FILE" ]; then
            echo ""
            echo "📋 Últimos logs:"
            tail -10 $LOG_FILE
        fi
        return 1
    fi
}

# Función para mostrar logs en tiempo real
logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo -e "${RED}❌ No se encontró el archivo de log${NC}"
        return 1
    fi
    
    echo "📋 Mostrando logs en tiempo real (Ctrl+C para salir)..."
    tail -f $LOG_FILE
}

# Función para mostrar ayuda
help() {
    cat << EOF
🤖 Gestor del Agente Python - WhatsApp Bot

Uso: $0 {start|stop|restart|status|logs|help}

Comandos:
  start      Inicia el agente en background
  stop       Detiene el agente
  restart    Reinicia el agente (stop + start)
  status     Muestra el estado actual del agente
  logs       Muestra los logs en tiempo real
  help       Muestra esta ayuda

Ejemplos:
  $0 start       # Iniciar el agente
  $0 status      # Ver si está corriendo
  $0 logs        # Ver logs en tiempo real
  $0 restart     # Reiniciar el agente

Archivos:
  Log:     agent_verbose.log
  PID:     $PID_FILE
  Script:  $AGENT_SCRIPT

Para configurar Google Calendar:
  ./venv/bin/python setup_calendar_auth.py

EOF
}

# Main
case "${1:-}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    help|--help|-h)
        help
        ;;
    *)
        echo -e "${RED}❌ Comando desconocido: ${1:-}${NC}"
        echo ""
        help
        exit 1
        ;;
esac

exit $?
