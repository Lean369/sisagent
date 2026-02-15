import sys
import os
from loguru import logger
from dotenv import load_dotenv

load_dotenv()  # Carga las variables de entorno desde el archivo .env


# 2. Función que rechaza los logs de auditoría
def filtro_log_principal(record):
    # Devuelve True SOLO si NO es una auditoría
    return not record["extra"].get("is_audit", False)

def inicializar_logger():
    """Configura Loguru para toda la aplicación (Consola y Archivos por Cliente)."""
    # Configuración de Consola - con protección para evitar errores si ya fue removido
    try:
        logger.remove(0)  # Elimina el handler por defecto (si existe)
    except ValueError:
        pass  # Ya fue removido por otro módulo

    logger.add(
        sys.stdout, 
        filter=filtro_log_principal,
        level=os.getenv("LOG_LEVEL", "DEBUG"),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )

    # Configuración de Archivo con Rotación y Compresión
    os.makedirs("logs", exist_ok=True)
    logger.add(
        os.getenv("LOG_FILE_PATH", "logs/sisagent_verbose.log"),
        rotation=os.getenv("MAX_BYTES_LOG_FILE", "10 MB"),
        retention= os.getenv("RETENTION_LOGS", "20 days"),
        compression=os.getenv("COMPRESSION_LOGS", "zip"),
        level=os.getenv("LOG_LEVEL", "DEBUG"),
        enqueue=True,
        encoding="utf-8"
    )

# Usamos un Set en memoria para registrar qué clientes ya tienen su handler activo
_clientes_configurados = set()


def generar_resumen_auditoria(business_id, message):
    """
    Registra el resumen de la conversación en el archivo exclusivo del cliente.
    Crea el archivo automáticamente si es la primera vez que el cliente interactúa.
    """
    
    # Asegurar que existe la carpeta de logs
    if not os.path.exists("logs_auditoria"):
        os.makedirs("logs_auditoria")
        
    # 2. Creación explícita del Handler para el cliente (Solo corre 1 vez por cliente)
    if business_id not in _clientes_configurados:
        # Usamos f-strings de Python puro para el nombre, sin depender de Loguru
        ruta_archivo = f"logs_auditoria/audit_{business_id}.log"
        
        # ⚠️ Filtro estricto: Solo atrapa a ESTE cliente y que SEA auditoría
        def filtro_cliente_especifico(record):
            extra = record["extra"]
            return extra.get("is_audit") is True and extra.get("business_id") == business_id

        # Agregamos el archivo a Loguru
        logger.add(
            ruta_archivo,
            filter=filtro_cliente_especifico,
            format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
            rotation="10 MB",
            retention="30 days",
            enqueue=True, # Thread-safe
            encoding="utf-8"
        )
        _clientes_configurados.add(business_id)
        
    # Emitimos el log "etiquetado". 
    logger.bind(business_id=business_id, is_audit=True).info(message)