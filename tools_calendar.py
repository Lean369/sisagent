import requests
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from loguru import logger
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# 1. Definimos el Esquema Estricto
class CitaSchema(BaseModel):
    nombre: str = Field(
        description="El nombre completo del usuario. Ej: Juan Pérez"
    )
    email: str = Field(
        description="El correo electrónico del usuario. Debe ser un formato válido."
    )
    fecha_hora_iso: str = Field(
        description="CRÍTICO: La fecha y hora exactas de la cita ESTRICTAMENTE en formato ISO 8601. Ejemplo: '2026-02-18T15:00:00'."
    )

@tool("agendar_cita_calendar", args_schema=CitaSchema, handle_tool_error=True)
def agendar_cita_calendar(nombre: str, email: str, fecha_hora_iso: str, config: RunnableConfig) -> str:
    """
    Útil para agendar una cita en el calendario del negocio.
    ÚSALA SOLO cuando el usuario ya confirmó día, hora, nombre y email.
    """
    # Recuperamos de qué cliente es este bot para saber a qué calendario enviarlo
    business_id = config.get("configurable", {}).get("business_id")
    
    url_webhook_n8n = f"{os.getenv('N8N_BASE_URL')}{os.getenv('N8N_CALENDAR_WEBHOOK')}"
    
    payload = {
        "business_id": business_id,
        "nombre_cliente": nombre,
        "email_cliente": email,
        "fecha_hora_inicio": fecha_hora_iso
    }
    
    try:
        respuesta = requests.post(url_webhook_n8n, json=payload, timeout=10)
        
        # 1. Errores que el LLM SÍ puede arreglar (ej. formato inválido)
        if respuesta.status_code == 400:
            raise ToolException(
                f"La API rechazó los datos: {respuesta.text}. "
                "Por favor, revisa el formato (especialmente la fecha ISO 8601) y VUELVE A INTENTARLO."
            )
            
        # 2. Errores Críticos que el LLM NO puede arreglar (401, 403)
        elif respuesta.status_code >= 401:
            # 🚀 Instrucción estricta de abortar
            raise ToolException(
                "ERROR FATAL DE AUTENTICACIÓN (403). "
                "INSTRUCCIÓN ESTRICTA: ¡NO VUELVAS A EJECUTAR ESTA HERRAMIENTA! "
                "Dile al usuario que el sistema de reservas está en mantenimiento en este momento "
                "y ofrécele transferirlo con un agente humano."
            )
            
        # 3. Errores del Servidor Caído (500, 502, 503)
        elif respuesta.status_code >= 500:
            raise ToolException(
                "ERROR FATAL DE SERVIDOR (500). "
                "INSTRUCCIÓN ESTRICTA: NO REINTENTES. "
                "Dile al usuario que hay una falla temporal de conexión y pide disculpas."
            )

        respuesta.raise_for_status()
        return "CITA_CREADA_EXITOSAMENTE."
        
    except requests.exceptions.Timeout:
        # El timeout a veces es mala suerte temporal, podemos dejarlo intentar 1 vez más
        logger.warning("⚠️ Timeout al conectar con n8n. Intentando solo 1 vez más...")
        raise ToolException("El servidor tardó mucho. Intenta solo 1 vez más. Si falla, ríndete.")