"""
Herramientas del agente IA para deribar consultas a agentes humanos (HITL - Human In The Loop) 
"""
import os
import requests
import json
from loguru import logger
import jwt
import datetime
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from utilities import obtener_configuraciones
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()


SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default_inseguro")

def generar_token_reactivacion(business_id, user_id, expiracion_minutos=60):
    """
    Genera un token firmado que expira en X minutos.
    Oculta los IDs dentro del payload.
    """
    try:
        payload = {
            "bid": business_id,    # Usamos nombres cortos para que la URL no sea gigante
            "uid": user_id,
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=expiracion_minutos)
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
        return token
    except Exception as e:
        logger.error(f"Error generando token: {e}")
        return None


def obtener_mensaje_admin(motivo, thread_id):
    try:      
        cliente_telefono = thread_id.split(':')[1].split('@')[0] if ':' in thread_id else thread_id.split('@')[0]
        user_id = thread_id.split(':')[1] if ':' in thread_id else "default_user_id"
        business_id = thread_id.split(':')[0] if ':' in thread_id else "default_business"
        # Generamos el token seguro (válido por 24 horas por ejemplo)
        token = generar_token_reactivacion(business_id, user_id, expiracion_minutos=1440)
        
        # URL de tu servidor (ajusta localhost por tu dominio real en producción)
        base_url = os.getenv("APP_BASE_URL", "http://192.168.1.220:5000")
        magic_link = f"{base_url}/reactivar_bot_web?token={token}"

        # Mensaje al dueño con el link OCULTO
        msg_admin = (
            f"🚨 *SOLICITUD DE HUMANO*\n\n"
            f"Cliente: +{cliente_telefono}\n"
            f"Motivo: {motivo}\n\n"
            f"Negocio: {business_id}\n\n"
            f"👇 *Cuando termines, haz clic aquí para reactivar el bot:*\n\n"
            f"{magic_link}"
            f"\n\n⚠️ *Intervenir ahora.*"
        )
        logger.debug(f"Mensaje para admin generado: {msg_admin}")
        
        return msg_admin

    except Exception as e:
        logger.error(f"Error generando mensaje para admin: {e}")
        return f"🚨 *SOLICITUD DE HUMANO*\n\nCliente: +{cliente_telefono}\nMotivo: {motivo}\n\n(No se pudo generar el enlace de reactivación, contacta al soporte.)"



class TriggerHITLToolInput(BaseModel):
    motivo: str = Field(description="El motivo de la derivación (ej: cliente enojado, consulta compleja, solicitud de humano).")

@tool("solicitar_atencion_humana", args_schema=TriggerHITLToolInput)
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
        

        # Extraemos el teléfono del administrador desde el config dinámico (hot reload)
        config_actual = obtener_configuraciones() 
        info_negocio = config_actual.get(business_id)
        admin_phone = info_negocio['admin_phone'] 
        mensaje_HITL = info_negocio.get('mensaje_HITL', "consulta derivada")
        cliente_telefono = thread_id.split(':')[1].split('@')[0] if ':' in thread_id else thread_id.split('@')[0]

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
        msg_admin = obtener_mensaje_admin(motivo, thread_id)
        
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
            json={"number": cliente_telefono, "text": mensaje_HITL},
            headers=headers
        )

        # 4. Retorno al LLM (Instrucción de Silencio)
        # Le decimos al LLM que NO genere nada más, porque ya nos encargamos nosotros.
        logger.info(f"✅ Derivación a humano realizada para {thread_id}. Notificado admin y cliente.")
        return "DERIVACION_EXITOSA_SILENCIO"

    except Exception as e:
        logger.exception(f"🔴 Error en derivación a humano: {e}")
        return "Tuve un error intentando contactar al humano. Por favor intenta de nuevo."


def decodificar_token_reactivacion(token):
    """
    Lee el token, verifica la firma y la fecha de expiración.
    Retorna (business_id, user_id) o lanza excepción.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["bid"], payload["uid"]
    except jwt.ExpiredSignatureError:
        raise ValueError("El enlace ha expirado. Genera uno nuevo.")
    except jwt.InvalidTokenError:
        raise ValueError("Token inválido o manipulado.")


CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL", "https://tu-dominio-chatwoot.com")
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "tu_token_maestro_aqui")

@tool
def solicitar_atencion_humana_chatwoot(motivo: str, config: RunnableConfig) -> str:
    """
    Útil EXCLUSIVAMENTE cuando el usuario pide explícitamente hablar con un humano, 
    o cuando estás atascado y no puedes resolver su problema (frustración).
    Requiere un breve motivo de por qué se transfiere.
    """
    # 1. Extraemos los IDs desde la configuración inyectada por tu worker
    thread_id = config.get("configurable", {}).get("thread_id", "")

    # Asumimos el formato: cliente1:5491131376731@Channel::Api@1@10
    partes = thread_id.split("@")
    if len(partes) != 4:
        return "Error interno: Formato de hilo inválido para Chatwoot."
    
    account_id = partes[2]
    conversation_id = partes[3]

    # 2. Endpoint de Chatwoot para cambiar el estado de la conversación
    url_status = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_status"
    
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }

    try:
        # 3. Cambiamos el estado a 'open' (Abierto para agentes humanos)
        respuesta = requests.post(url_status, json={"status": "open"}, headers=headers, timeout=5)
        respuesta.raise_for_status()
        
        # 4. (Opcional pero recomendado) Dejar una nota interna para el humano
        url_nota = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        requests.post(url_nota, json={
            "content": f"🤖 Bot derivó esta charla. Motivo: {motivo}",
            "message_type": "outgoing",
            "private": True # CRÍTICO: El cliente final no lee esto, solo el humano en el panel
        }, headers=headers)

        logger.info(f"🔄 Conversación {conversation_id} derivada a humanos exitosamente.")
        
        # Le decimos al LLM qué pasó para que se despida
        return "DERIVACION_EXITOSA_CHATWOOT. Despídete amablemente diciendo que un agente se conectará pronto."

    except requests.exceptions.RequestException as e:
        logger.error(f"Error derivando en Chatwoot: {e}")
        return "No me fue posible contactar a un humano en este momento por un fallo de conexión."