"""
Herramientas del agente IA para deribar consultas a agentes humanos (HITL - Human In The Loop) 
"""
import os
import requests
import json
from loguru import logger
#import sys
#from typing import Dict, Optional

#from datetime import datetime
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from utilities import obtener_configuraciones
#import threading
#import time
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Mensaje FIJO que recibirá el cliente (Sin LLM)
MENSAJE_ESPERA_CLIENTE = """🤖 *Consulta Derivada*

He notificado a un asesor humano sobre tu consulta. 
En breve se pondrán en contacto contigo por este medio.

¡Gracias por tu paciencia!"""

class TriggerHITLToolInput(BaseModel):
    motivo: str = Field(description="El motivo de la derivación (ej: cliente enojado, consulta compleja, solicitud de humano).")

@tool(args_schema=TriggerHITLToolInput)
def solicitar_atencion_humana(motivo: str, config: RunnableConfig) -> str:
    """
    Activa esta herramienta cuando el cliente pida hablar con un humano, 
    esté enojado o la consulta sea muy compleja.
    Notifica al dueño y avisa al cliente.
    """
    try:
        # 1. Obtener datos de configuración
        configuration = config.get('configurable', {})
        business_id = configuration.get('business_id', 'default')
        thread_id = configuration.get('thread_id', '')
        cliente_telefono = thread_id.split(':')[1].split('@')[0] if ':' in thread_id else thread_id.split('@')[0]

        # Extraemos el teléfono del administrador desde el config dinámico (hot reload)
        config_actual = obtener_configuraciones() 
        info_negocio = config_actual.get(business_id)
        admin_phone = info_negocio['admin_phone'] 

        if not admin_phone:
            logger.error(f"🔴 No hay teléfono de administrador configurado para {business_id}. No se puede derivar a humano.")
            return "🔴 Error: No hay un teléfono de administrador configurado para notificar."
        else:
            logger.info(f"📞 Teléfono de administrador para {business_id}: {admin_phone}")

        # 3. URL de Evolution API (La tomamos de entorno o config)
        evo_url = os.environ.get("EVOLUTION_API_URL", "https://evoapi.sisnova.com.ar")
        headers = {
            "Content-Type": "application/json",
            "apikey": os.environ.get("EVOLUTION_API_KEY")
        }

        # --- ACCIÓN A: AVISAR AL DUEÑO ---
        msg_admin = f"🚨 *SOLICITUD DE HUMANO*\n\nCliente: +{cliente_telefono}\nMotivo: {motivo}\nBusiness: {business_id}\n\n⚠️ *Intervenir ahora.*"
        
        response = requests.post(
            f"{evo_url}/message/sendText/{business_id}", # Usamos la instancia del negocio
            json={"number": admin_phone, "text": msg_admin},
            headers=headers
        )
        status = response.status_code
        text = None
        try:
            text = response.json()
        except Exception:
            text = response.text

        logger.debug(f"[SND -> EVO] Tried send message to admin: status={status} response={str(text)[:200]}")

        # --- ACCIÓN B: RESPONDER AL CLIENTE (FRASE FIJA) ---
        # Enviamos el mensaje DIRECTAMENTE desde aquí para evitar que el LLM lo parafrasee
        requests.post(
            f"{evo_url}/message/sendText/{business_id}",
            json={"number": cliente_telefono, "text": MENSAJE_ESPERA_CLIENTE},
            headers=headers
        )

        # 4. Retorno al LLM (Instrucción de Silencio)
        # Le decimos al LLM que NO genere nada más, porque ya nos encargamos nosotros.
        logger.info(f"✅ Derivación a humano realizada para {thread_id}. Notificado admin y cliente.")
        return "DERIVACION_EXITOSA_SILENCIO"

    except Exception as e:
        logger.exception(f"🔴 Error en derivación a humano: {e}")
        return "Tuve un error intentando contactar al humano. Por favor intenta de nuevo."
