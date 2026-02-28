from loguru import logger
from logger_config import inicializar_logger, generar_resumen_auditoria
from flask import Flask, request, jsonify, render_template_string
from flask import Response
# 🚀 1. Inicializar el logger ANTES que el resto del sistema
inicializar_logger()
from cliente_config import ClienteConfig
from agente import procesar_mensaje, obtener_todas_las_tools, TOOLS_REGISTRY, transcribir_audio, analizar_imagen_con_ai
from utilities import obtener_configuraciones
from tools_hitl import decodificar_token_reactivacion
from langchain_core.runnables.graph import CurveStyle, NodeStyles, MermaidDrawMethod
from ddos_protection import ddos_protection
import sys
from onboarding_coexistence import ONBOARDING_HTML
from politica_privacidad import politica_privacidad_html
from agente import pool, workflow_builder # Importamos el builder, NO la app completa
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import ToolMessage
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
import httpx
import requests
import json
import os
import base64
import io
from time import sleep
from pydantic import BaseModel
from evolutionapi.client import EvolutionClient  # del paquete oficial
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration


app = Flask(__name__)


# Inicializa Sentry
if os.getenv("SENTRY_ENABLED", "false").lower() == "true":
    sentry_sdk.init(
        dsn=os.getenv("DSN"), 
        integrations=[
            FlaskIntegration(),           # captura errores en rutas Flask
            SqlalchemyIntegration(),      # captura errores en consultas DB
            # Agrega más si usas Celery, Redis, etc.
        ],
        # Captura 100% en desarrollo, 10-20% en producción para no saturar
        traces_sample_rate=1.0 if os.getenv("FLASK_ENV") == "development" else 0.2,   
        # Perfiles de performance (útil para ver bottlenecks en agentes IA)
        profiles_sample_rate=0.5,
        environment=os.getenv("FLASK_ENV"),        # o "production"
        release=os.getenv("RELEASE"),          # opcional: versión de tu app
        send_default_pii=True,            # envía datos de usuario (email, ID) para mejor contexto
    )


# Pool de threads para manejar múltiples mensajes en paralelo
# CPU de 4 núcleos (max_workers=10)
# CPU de 8+ núcleos (max_workers=20)
executor = ThreadPoolExecutor(max_workers=10)  # CPU de 2 núcleos - 10 mensajes simultáneos

logger.info("🔄 Iniciando app Flask...")

DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"
EVOLUTION_URL = os.environ.get("EVOLUTION_API_URL", "https://evoapi.sisnova.com.ar")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY")

client = EvolutionClient(base_url=EVOLUTION_URL, api_token=EVOLUTION_API_KEY)

def enviar_documento_whatsapp(numero_destino: str, documento, nombre_instancia: str = None, 
                              filename: str = "documento.pdf", caption: str = None):
    """Envía un documento a través del cliente de Evolution API.
    
    Args:
        numero_destino: Número en formato internacional (549...)
        documento: Puede ser:
            - URL del documento (str que empiece con http:// o https://)
            - Base64 del documento (str sin prefijo o con data:application/pdf;base64,)
        nombre_instancia: Nombre de la instancia Evolution
        filename: Nombre del archivo que verá el usuario
        caption: Texto opcional que acompaña al documento
    """
    logger.debug(f"Enviando documento a WhatsApp: {numero_destino} - {filename}")

    try:
        endpoint = f"message/sendMedia/{nombre_instancia}"
        
        # Detectar si es URL o base64
        is_url = isinstance(documento, str) and (documento.startswith('http://') or documento.startswith('https://'))
        
        if is_url:
            # Enviar como URL
            payload = {
                "number": numero_destino,
                "mediatype": "document",
                "mimetype": "application/pdf",
                "caption": caption or f"📄 {filename}",
                "fileName": filename,
                "media": documento
            }
        else:
            # Enviar como base64
            # Limpiar el base64 si viene con el prefijo data:
            base64_data = documento
            if base64_data.startswith('data:'):
                base64_data = base64_data.split(',')[1]
            
            payload = {
                "number": numero_destino,
                "mediatype": "document",
                "mimetype": "application/pdf",
                "caption": caption or f"📄 {filename}",
                "fileName": filename,
                "media": base64_data
            }
    
        response = client.post(endpoint, data=payload)
        
        if not response:
            logger.error(f"❌ Evolution client returned empty response")
            return {"status": "failed", "error": "Empty response from Evolution API"}
        
        logger.info(f"✅ Documento '{filename}' enviado correctamente a {numero_destino}")
        logger.debug(f"Sent document with instance={nombre_instancia} response={str(response)[:200]}")
        
        return response
            
    except Exception as e:
        logger.error(f"🔴 Exception when sending document with instance {nombre_instancia}: {e}")
        return {"status": "failed", "error": str(e)}


def enviar_lista_whatsapp(numero_destino: str, mensaje, nombre_instancia: str = None):
    """Envía un mensaje con botones interactivos a través del cliente de Evolution API.
    Soporta hasta 3 botones de tipo 'reply'.
    """
    logger.debug(f"Enviando mensaje con botón a WhatsApp: {numero_destino} - {str(mensaje)[:50]}...")

    try:
        endpoint = f"message/sendText/{nombre_instancia}" # SOLO Whatsapp API 
        # endpoint = f"message/sendList/{nombre_instancia}" #SOLO Whatsapp API 
        # endpoint = f"message/sendPoll/{nombre_instancia}" # SOLO baileys
        # endpoint = f"message/sendButtons/{nombre_instancia}" #SOLO Whatsapp API 
        # endpoint = f"message/sendMedia/{nombre_instancia}" # Funciona en ambos

                # Estructura para envío de botones tipo "reply" (WhatsApp Cloud API)
        # Cada botón debe tener: type="reply" + reply: { id, title }
        import time
        payload = {
            "number": numero_destino,
            "text": f"https://sisagent.sisnova.org/", #?v={int(time.time())}",  # ?v= fuerza re-fetch del preview
            "linkPreview": True,
            "delay": 1200
        }

        payload_media = {
            "number": numero_destino,
            "mediatype": "image",
            "mimetype": "image/jpeg",
            "fileName": "botas.jpeg",
            "media": "https://sisagent.sisnova.org/static/botas.jpeg",
            "caption": "https://sisagent.sisnova.org/"
        }       

        payload_poll = {
            "number": numero_destino,
            "name": mensaje,
            "selectableCount": 1,
            "values": [
                "Opción 1",
                "Opción 2",
                "Opción 3"
            ]
        }

        # Estructura para envío de botones tipo "list" (más visual, recomendado para WhatsApp)
        payload_list = {
            "number": numero_destino,
            "title": mensaje,
            "description": "Selecciona una opción:",
            "buttonText": "Ver opciones",
            "footerText": "Powered by Sisnova",
            "sections": [
                {
                    "title": "Opciones disponibles",
                    "rows": [
                        {
                            "title": "Opción 1",
                            "description": "Descripción de opción 1",
                            "rowId": "btn_1"
                        },
                        {
                            "title": "Opción 2",
                            "description": "Descripción de opción 2",
                            "rowId": "btn_2"
                        }
                    ]
                }
            ]
        }
        
        # Estructura para envío de botones tipo "reply" (más simple, pero menos visual)
        payload_buttons = {
            "number": numero_destino,
            "title": mensaje,
            "description": "Selecciona una opción:",
            "footerText": "Powered by Sisnova",
            "buttons": [
                {
                    "type": "reply",
                    "displayText": "Opción 1",
                    "id": "btn_1"
                },
                {
                    "type": "reply",
                    "displayText": "Opción 2",
                    "id": "btn_2"
                },
                {
                    "type": "reply",
                    "displayText": "Opción 3",
                    "id": "btn_3"
                }
            ]
        }
    
        response = client.post(endpoint, data=payload)
        logger.debug(f"Response from Evolution API: {str(response)[:200]}")

        if not response:
            logger.error(f"❌ Evolution client returned empty response")
            return {"status": "failed", "error": "Empty response from Evolution API"}
        # else:
        #     sleep(0.2)  # Pequeña pausa 0,2 segundos para evitar problemas de orden en la API de Evolution
        #     buttons_endpoint = f"message/sendButtons/{nombre_instancia}"
        #     buttons_payload = {
        #         "number": numero_destino,
        #         "title": "¿Cómo podemos ayudarte?",
        #         "buttons": [
        #             {
        #                 "type": "reply",
        #                 "displayText": "🛒 Comprar ahora!",
        #                 "id": "btn_asesor"
        #             },
        #             {
        #                 "type": "reply",
        #                 "displayText": " Ver más información",
        #                 "id": "btn_info"
        #             }
        #         ]
        #     }
        #     response = client.post(buttons_endpoint, data=buttons_payload)
        #     logger.debug(f"Response from sending buttons: {str(response)[:200]}")
        
        logger.info(f"✅ Botones enviados correctamente a {numero_destino}")
        logger.debug(f"Sent button message with instance={nombre_instancia} response={str(response)[:200]}")
        
        return response
            
    except Exception as e:
        logger.error(f"🔴 Exception when sending button message with instance {nombre_instancia}: {e}")
        return {"status": "failed", "error": str(e)}


def enviar_texto_whatsapp(numero_destino: str, mensaje, nombre_instancia: str = None):
    """Envía un mensaje a través del cliente de Evolution API.
    """
    logger.debug(f"Enviando mensaje a WhatsApp: {numero_destino} - {str(mensaje)[:50]}...")

    try:
        endpoint = f"message/sendText/{nombre_instancia}"
        
        payload = {
            # Evolution requiere el formato de número internacional sin el '+'
            "number": f"{numero_destino}", 
            "text": mensaje,
            "options": {
                "presence": "composing" # Muestra "Escribiendo..." en el celular del usuario
            }
        }
    
        response = client.post(endpoint, data=payload)
        
        if not response:
            logger.error(f"❌ Evolution client returned empty response")
            return {"status": "failed", "error": "Empty response from Evolution API"}
        
        logger.debug(f"Sent: with instance={nombre_instancia} response={str(response)[:200]}")
            
        client_id = numero_destino.split('@')[0] if numero_destino else "unknown"
        msg = f"[SND -> EVO] 📤 ID: {client_id} - MSG: {str(mensaje)[:100]}..."
        generar_resumen_auditoria(nombre_instancia, msg)

        # Verificar si la respuesta indica éxito
        if isinstance(response, dict) and response.get("key"):
            # Respuesta exitosa con message key
            return response
        else:
            logger.error(f"❌ Evolution API error: response={response}")
            return {"status": "failed", "error": "Evolution API error", "response": response}
            
    except Exception as e:
        logger.error(f"🔴 Exception when sending with instance {nombre_instancia}: {e}")
        return {"status": "failed", "error": str(e)}


def adaptar_procesar_mensaje(business_id: str, user_id: str, mensaje: str, client_name: str = "", ttl_minutos: int = 60) -> str:
    """Procesa un mensaje usando LangGraph y devuelve el resultado como texto"""
    try:
        # 1. Datos obligatorios      
        if not user_id or not business_id or not mensaje:
            logger.error("❌ Faltan IDs o mensaje en adaptar_procesar_mensaje")
            return None # Retorna None o un string vacío para que el worker sepa que falló

        # 2. Crear Thread ID Único (Aislamiento de Memoria)
        # Esto asegura que Postgres guarde la conversación en un "cajón" único
        thread_id = f"{business_id}:{user_id}"
        
        # 3. Configuración para LangGraph
        # Pasamos dentro de 'configurable' toda la info de la conversación para que el nodo lo pueda leer
        config = {
            "configurable": {
                "thread_id": thread_id,
                "business_id": business_id,
                "client_name": client_name,
                "ttl_minutos": ttl_minutos
            },
            "recursion_limit": 15
        }

        # 2. LLAMADA LIMPIA A LA FUNCIÓN
        logger.debug(f"Procesando mensaje para thread_id={thread_id}")

        resultado = procesar_mensaje(mensaje, config)     

        response = resultado.get("response")
        status = resultado.get("status")

        logger.debug(f"Respuesta recibida para {thread_id}: status={status}, response={str(response)[:50]}")

        if status == "COMPLETED" or status == "ERROR":
            logger.success(f"✅ Respuesta generada para {thread_id}: {str(response)[:50]}")
            return response
        elif status == "PAUSED":
            logger.warning(f"⏸️ Bot pausado para {thread_id}. No se generará respuesta.")
            return ""  # Retornamos cadena vacía para indicar que no se debe enviar nada al cliente
        else:
            logger.warning(f"⚠️ Respuesta desconocida con status {status} para {thread_id}: {str(response)[:50]}")
            return  "⚠️ En este momento no puedo procesar su solicitud."

        return response

    except Exception as e:
        logger.error(f"🔴 Error: {e}") 
        return  "No se pudo procesar su solicitud."


def procesar_y_responder_evoapi(business_id, user_id, mensaje, push_name, ttl_minutos):
    """
    Función que corre en background:
    1. Llama al Agente (Lento)
    2. Envía la respuesta por WhatsApp (I/O)
    """
    try:    
        # 1. Proceso Lento (IA)
        respuesta_ia = adaptar_procesar_mensaje(business_id, user_id, mensaje, client_name=push_name, ttl_minutos=ttl_minutos)
        
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 IA terminó para {user_id}. Enviando respuesta...")
            enviar_texto_whatsapp(user_id, respuesta_ia, business_id)

            # # Cargar el base64
            # with open('documento_prueba_base64.txt', 'r') as f:
            #     base64_pdf = ''.join([line for line in f if not line.startswith('#')]).strip()

            # # Usar la función actualizada
            # from app import enviar_documento_whatsapp

            # enviar_documento_whatsapp(
            #     "5491131376731",          # Tu número
            #     base64_pdf,               # El base64 del PDF
            #     "cliente2",               # Tu instancia
            #     "documento_prueba.pdf",   # Nombre del archivo
            #     "📄 Documento de prueba"  # Caption opcional
            # )


        else:
            logger.warning(f"⚠️ IA no generó respuesta para {user_id}")
            #respuesta_ia = "Lo siento, no pude generar una respuesta en este momento."
            #enviar_texto_whatsapp(user_id, respuesta_ia, business_id)

    except Exception as e:
        logger.error(f"🔴 Error en worker background para {user_id}: {e}")


def worker_procesar_imagen(business_id, user_id, msg_id, mensaje, push_name):
    """
    Procesa imágenes enviadas por WhatsApp:
    1. Descarga la imagen desde Evolution API
    2. Analiza la imagen con AI multimodal
    3. Responde al usuario con el análisis
    """
    try:
        logger.debug(f"[IMAGE] Procesando imagen para {user_id}, instance={business_id}")
        telefono = user_id.split("@")[0]
        
        # Usar el cliente evolutionapi para obtener la imagen en base64
        endpoint = f"chat/getBase64FromMediaMessage/{business_id}"
        payload_media = {
            "message": {
                "key": mensaje.get("key"),
                "message": mensaje.get("message")
            },
            "convertToMp4": False
        }
        
        logger.debug(f"[IMAGE] Solicitando descarga de imagen usando evolutionapi client...")
        
        try:
            response = client.post(endpoint, data=payload_media)
            
            if not response or not isinstance(response, dict):
                logger.error(f"❌ [IMAGE] Respuesta inválida del cliente: {response}")
                msg = "Disculpa, tuve problemas para procesar tu imagen. ¿Podrías describir qué necesitas? 📝"
                enviar_texto_whatsapp(user_id, msg, business_id)
                return
            
            base64_image = response.get("base64")
            
            if not base64_image:
                logger.error(f"❌ [IMAGE] No se recibió base64 en la respuesta: {response}")
                msg = "Disculpa, no pude procesar tu imagen. ¿Podrías describir qué necesitas? 📝"
                enviar_texto_whatsapp(user_id, msg, business_id)
                return
            
            # Decodificar el base64 a bytes
            image_buffer = base64.b64decode(base64_image)
            logger.info(f"[IMAGE] Imagen descargada: {len(image_buffer)} bytes")
            
            # Extraer caption si existe
            caption = mensaje.get("message", {}).get("imageMessage", {}).get("caption")
            
            # Analizar la imagen con AI
            thread_id = f"{business_id}:{user_id}"
            analisis = analizar_imagen_con_ai(image_buffer, thread_id, caption)
            
            if analisis:
                msg = f"[RCV <- EVO] 🖼️ ID: {telefono} - IMG: {caption[:50] if caption else 'sin texto'}"
                generar_resumen_auditoria(business_id, msg)
                
                # Enviar el análisis como respuesta
                respuesta = f"📸 He analizado tu imagen:\n\n{analisis}"
                if caption:
                    respuesta = f"📸 Vi tu imagen y el texto '{caption}'.\n\n{analisis}"
                
                enviar_texto_whatsapp(user_id, respuesta, business_id)
            else:
                msg = "Disculpa, no pude analizar tu imagen. ¿Podrías describir qué necesitas? 📝"
                enviar_texto_whatsapp(user_id, msg, business_id)
                
        except Exception as api_error:
            logger.error(f"❌ [IMAGE] Error llamando API Evolution: {api_error}")
            msg = "Disculpa, tuve problemas procesando tu imagen. ¿Podrías describir qué necesitas? 📝"
            enviar_texto_whatsapp(user_id, msg, business_id)

    except Exception as e:
        logger.error(f"🔴 Error procesando imagen background: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            msg = "Disculpa, tuve un error procesando tu imagen. ¿Podrías escribir tu consulta? 📝"
            enviar_texto_whatsapp(user_id, msg, business_id)
        except:
            pass  # Evitar errores en cascada

def worker_procesar_audio(business_id, user_id, msg_id, mensaje, push_name, ttl_minutos):
    """Procesa audios enviados por Evolution API - WhatsApp SOLO Baileys:
    1. Descarga el audio desde Evolution API
    2. Decodifica el audio de base64 a bytes
    3. Transcribe el audio a texto
    4. Procesa el texto con IA
    """
    try:
        logger.debug(f"[AUDIO] Procesando audio para {user_id}, instance={business_id}")
        telefono = user_id.split("@")[0]    
        # Usar el cliente evolutionapi para obtener el audio en base64
        # https://doc.evolution-api.com/v2/en/endpoints/messages#get-media
        endpoint = f"chat/getBase64FromMediaMessage/{business_id}"
        # Evolution necesita el objeto data completo (key + message + metadata)
        payload_media = {
            "message": {
                "key": mensaje.get("key"),
                "message": mensaje.get("message")
            },
            "convertToMp4": False  # Mantener formato original (ogg opus)
        }
        
        logger.debug(f"[AUDIO] Solicitando descarga de media usando evolutionapi client...")
        
        try:
            response = client.post(endpoint, data=payload_media)
            
            if not response or not isinstance(response, dict):
                logger.error(f"❌ [AUDIO] Respuesta inválida del cliente: {response}")
                msg = "Disculpa, tuve problemas para procesar tu audio. ¿Podrías escribirlo? 📝"
                enviar_texto_whatsapp(user_id, msg, business_id)
                return
            
            base64_audio = response.get("base64")
            
            if not base64_audio:
                logger.error(f"❌ [AUDIO] No se recibió base64 en la respuesta: {response}")
                msg = "Disculpa, no pude procesar tu audio. ¿Podrías escribirlo? 📝"
                enviar_texto_whatsapp(user_id, msg, business_id)
                return
            
            # Decodificar el base64 a bytes PRIMERO
            audio_buffer = base64.b64decode(base64_audio)
            logger.info(f"[AUDIO] Audio descargado: {len(audio_buffer)} bytes")

            # 1. Transcribir (Lento)
            texto_transcrito = transcribir_audio(audio_buffer, thread_id=f"{business_id}:{user_id}")
            
            if texto_transcrito:
                # logger.info(f"🗣️ Audio transcrito: {texto_transcrito[:50].replace('\n', ' ')}")
                msg = f"[RCV <- EVO] 🔊 ID: {telefono} - MSG: {texto_transcrito[:100].replace('\n', ' ')}"
                generar_resumen_auditoria(business_id, msg)
                # 2. Reutilizamos el worker de texto existente para procesar con IA
                procesar_y_responder_evoapi(business_id, user_id, texto_transcrito, push_name, ttl_minutos)
            else:
                msg = "Disculpa, no pude escuchar bien el audio. ¿Podrías escribirlo? 📝"
                enviar_texto_whatsapp(user_id, msg, business_id)
                
        except Exception as api_error:
            logger.error(f"❌ [AUDIO] Error llamando API Evolution: {api_error}")
            msg = "Disculpa, tuve problemas descargando tu audio. ¿Podrías escribirlo? 📝"
            enviar_texto_whatsapp(user_id, msg, business_id)

    except Exception as e:
        logger.error(f"🔴 Error procesando audio background: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            msg = "Disculpa, tuve un error procesando tu audio. ¿Podrías escribirlo? 📝"
            enviar_texto_whatsapp(user_id, msg, business_id)
        except:
            pass  # Evitar errores en cascada


def enviar_mensaje_chatwoot(account_id, conversation_id, texto_respuesta, client_id, business_id):
    """
    Envía la respuesta generada por LangGraph de vuelta a la conversación en Chatwoot.
    """
    CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL", "https://sischat.sisnova.com.ar/")
    CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "your_chatwoot_api_token_here")

    url = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    
    headers = {
        "api_access_token": CHATWOOT_API_TOKEN,
        "Content-Type": "application/json"
    }
    
    payload = {
        "content": texto_respuesta,
        "message_type": "outgoing",
        "private": False # Si es True, es una nota interna que el cliente no ve
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"✅ Respuesta enviada a Chatwoot (Conv ID: {conversation_id})")

        msg = f"[SND -> CWT] 📤 ID: {client_id} - MSG: {texto_respuesta[:100]}..."
        generar_resumen_auditoria(business_id, msg)

    except requests.exceptions.RequestException as e:
        logger.error(f"🔴 Error enviando a Chatwoot: {e}")


def worker_procesar_audio_chatwoot(business_id, user_id, audio_url, conversation_id, account_id, client_name, client_id, ttl_minutos):
    """
    Procesa una nota de voz recibida vía Chatwoot:
    1. Descarga el audio desde la URL de active_storage de Chatwoot (requiere token)
    2. Transcribe el audio a texto con Whisper
    3. Procesa el texto con IA y responde en Chatwoot
    """
    try:
        logger.debug(f"[AUDIO-CWT] Procesando audio para {user_id}, conv={conversation_id}")

        CHATWOOT_BASE_URL = os.getenv("CHATWOOT_BASE_URL", "https://sischat.sisnova.com.ar/")
        CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_API_TOKEN", "")

        # Descargar el audio desde Chatwoot active_storage (autenticado con token)
        headers = {"api_access_token": CHATWOOT_API_TOKEN}
        logger.debug(f"[AUDIO-CWT] Descargando audio desde: {audio_url[:80]}...")

        resp = requests.get(audio_url, headers=headers, timeout=30)
        resp.raise_for_status()
        audio_buffer = resp.content
        logger.info(f"[AUDIO-CWT] Audio descargado: {len(audio_buffer)} bytes")

        # Detectar formato del audio por magic bytes
        def detectar_formato_audio(buf: bytes) -> str:
            if buf[:4] == b'OggS':
                return 'ogg'
            if len(buf) >= 8 and buf[4:8] == b'ftyp':
                return 'mp4'
            if buf[:3] == b'ID3' or (len(buf) >= 2 and buf[0] == 0xFF and buf[1] & 0xE0 == 0xE0):
                return 'mp3'
            if buf[:4] == b'RIFF' and buf[8:12] == b'WAVE':
                return 'wav'
            # Fallback: intentar inferir desde Content-Type
            ct = resp.headers.get('Content-Type', '')
            if 'mp4' in ct or 'aac' in ct or 'm4a' in ct:
                return 'mp4'
            if 'mpeg' in ct or 'mp3' in ct:
                return 'mp3'
            if 'ogg' in ct:
                return 'ogg'
            if 'wav' in ct:
                return 'wav'
            return 'ogg'  # default legacy

        audio_format = detectar_formato_audio(audio_buffer)
        logger.debug(f"[AUDIO-CWT] Formato detectado: {audio_format} (Content-Type: {resp.headers.get('Content-Type', 'desconocido')})")

        # Transcribir con Whisper
        thread_id = f"{business_id}:{user_id}"
        texto_transcrito = transcribir_audio(audio_buffer, thread_id=thread_id, audio_format=audio_format)

        if texto_transcrito:
            msg = f"[RCV <- CWT] 🔊 ID: {client_id} - MSG: {texto_transcrito[:100].replace(chr(10), ' ')}"
            generar_resumen_auditoria(business_id, msg)
            # Procesar con IA y responder en Chatwoot
            procesar_y_responder_chatwoot(
                business_id, user_id, texto_transcrito,
                conversation_id, account_id, client_name, client_id, ttl_minutos
            )
        else:
            msg = "Disculpa, no pude escuchar bien el audio. ¿Podrías escribirlo? 📝"
            enviar_mensaje_chatwoot(account_id, conversation_id, msg, client_id, business_id)

    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ [AUDIO-CWT] Error HTTP descargando audio: {e}")
        msg = "Disculpa, tuve problemas descargando tu audio. ¿Podrías escribirlo? 📝"
        enviar_mensaje_chatwoot(account_id, conversation_id, msg, client_id, business_id)
    except Exception as e:
        logger.error(f"🔴 [AUDIO-CWT] Error procesando audio: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            msg = "Disculpa, tuve un error procesando tu audio. ¿Podrías escribirlo? 📝"
            enviar_mensaje_chatwoot(account_id, conversation_id, msg, client_id, business_id)
        except:
            pass


def procesar_y_responder_chatwoot(business_id, user_id, mensaje, conversation_id, account_id, client_name: str = "", client_id: str = "", ttl_minutos: int = 60):
    """Función que corre en background para procesar mensajes de Chatwoot y responder"""

    try:       
        logger.debug(f"Procesando mensaje para Chatwoot user_id={user_id} (Conv ID: {conversation_id})")

        # 1. Proceso Lento (IA)
        respuesta_ia = adaptar_procesar_mensaje(business_id, user_id, mensaje, client_name=client_name, ttl_minutos=ttl_minutos)
            
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 IA terminó para {user_id}. Enviando respuesta...")
            enviar_mensaje_chatwoot(account_id, conversation_id, respuesta_ia, client_id, business_id)
        else:
            logger.warning(f"⚠️ IA no generó respuesta para {user_id}")

    except Exception as e:
        logger.error(f"🔴 Error en procesar_y_responder_chatwoot para {user_id}: {e}")


@app.route('/webhook/chatwoot', methods=['POST'])
def webhook_chatwoot():
    try:
        data = request.json
        #logger.info(f"📨 Received Chatwoot webhook: {json.dumps(data)[:200]}")
        logger.info(f"📨 Received Chatwoot webhook: {json.dumps(data)}")

        # 1. Validar que el evento sea la creación de un mensaje
        if data.get('event') != 'message_created':
            logger.warning(f"⚠️ Evento ignorado: {data.get('event')}")
            return jsonify({"status": "ignorado", "razon": "no es un mensaje"}), 200

        # 2. Ignorar mensajes enviados por el bot o los agentes (evitar bucles infinitos)
        if data.get('message_type') != 'incoming':
            logger.warning(f"⚠️ Mensaje ignorado: message_type={data.get('message_type')}")
            return jsonify({"status": "ignorado", "razon": "mensaje saliente"}), 200
        
        # Chatwoot maneja estos estados: 'open' (humano), 'resolved' (cerrada), 'pending', 'bot'
        estado_conversacion = data.get('conversation', {}).get('status')
        conversation_id = data.get('conversation', {}).get('id')

        # Si la conversación está abierta (manejada por un humano), el bot hace silencio absoluto.
        if estado_conversacion == 'open':
            logger.info(f"🤫 Silencio. La conversación {conversation_id} está en manos de un humano.")
            return jsonify({"status": "ignorado", "razon": "conversacion_abierta"}), 200

        # 3. Extraer los datos clave del payload de Chatwoot
        mensaje = data.get('content')
        account_id = data.get('account', {}).get('id')
        business_id = data.get('account', {}).get('name')
        inbox_id = data.get('inbox', {}).get('id')    
        client_name = data.get('sender', {}).get('name') 
        channel = data.get('conversation', {}).get('channel')
        user_id = ""
        msg = ""
        client_id = ""

        # Detectar si es una nota de voz (content=null + attachment con file_type='audio')
        attachments = data.get('attachments') or []
        audio_attachment    = next((a for a in attachments if a.get('file_type') == 'audio'), None)
        # Nota: WhatsApp Business API envía tanto fotos como stickers como file_type="image"
        # (incluyendo .webp para fotos reales). No es posible distinguirlos de forma confiable.
        image_attachment    = next((a for a in attachments if a.get('file_type') == 'image'), None)
        document_attachment = next((a for a in attachments if a.get('file_type') == 'file'), None)
        contact_attachments = [a for a in attachments if a.get('file_type') == 'contact']
        location_attachment = next((a for a in attachments if a.get('file_type') == 'location'), None)

        # Determinar etiqueta del tipo de contenido para logs
        tipo_contenido = (
            '[audio]'      if audio_attachment else
            '[imagen]'     if image_attachment else
            '[documento]'  if document_attachment else
            '[contacto]'   if contact_attachments else
            '[ubicación]'  if location_attachment else
            (mensaje or '[desconocido]')
        )

        logger.debug(f"Extracted data - business_id: {business_id}, channel: {channel}, conversation_id: {conversation_id}, account_id: {account_id}, tipo={tipo_contenido}")
        
        # 4. Generar el user_id para LangGraph
        if channel == "Channel::Instagram":
            client_id = data.get('sender', {}).get('additional_attributes', {}).get('social_instagram_user_name')
            user_id = f"{client_id}@{channel}@{account_id}@{conversation_id}" if client_id else f"conv_{conversation_id}"
            msg = f"[RCV <- CWT] 📨 ID: {client_id} - MSG: {tipo_contenido[:100]}..."
        
        elif channel == "Channel::Whatsapp" or channel == "Channel::Api":
            client_id = str(data.get('sender', {}).get('phone_number'))
            user_id = f"{client_id.replace('+', '')}@{channel}@{account_id}@{conversation_id}" if client_id else f"conv_{conversation_id}"
            msg = f"[RCV <- CWT] 📨 ID: {client_id} - MSG: {tipo_contenido[:100]}..."
        
        generar_resumen_auditoria(business_id, msg)

        # 5. Obtener configuraciones específicas del negocio (como TTL, mensaje HITL, etc.)
        info_negocio = ClienteConfig(business_id)
        ttl_minutos = info_negocio.ttl_sesion_minutos or 60
        audio_transcripcion = info_negocio.audio_transcripcion or True

        # 6. Delegar al ThreadPool según tipo de contenido
        if audio_attachment and not mensaje:
            # [AUDIO] Nota de voz
            if audio_transcripcion:
                logger.info(f"🔊 [CWT] Procesando nota de voz de {user_id}. Transcribiendo con IA...")
                executor.submit(
                    worker_procesar_audio_chatwoot,
                    business_id, user_id,
                    audio_attachment.get('data_url'),
                    conversation_id, account_id,
                    client_name, client_id, ttl_minutos
                )
            else:
                logger.info(f"🔊 [CWT] Nota de voz recibida de {user_id}, transcripción deshabilitada.")
                msg_resp = "Gracias por tu nota de voz. Para poder ayudarte mejor, ¿podrías escribir tu consulta como texto? 📝"
                executor.submit(enviar_mensaje_chatwoot, account_id, conversation_id, msg_resp, client_id, business_id)

        elif image_attachment and not mensaje:
            # [IMAGEN] Sin caption → pedir descripción
            logger.info(f"🖼️ [CWT] Imagen recibida de {user_id} (sin texto)")
            msg_resp = "Gracias por la imagen. Para poder ayudarte mejor, ¿podrías describir qué necesitas? 📝"
            executor.submit(enviar_mensaje_chatwoot, account_id, conversation_id, msg_resp, client_id, business_id)

        elif document_attachment and not mensaje:
            # [DOCUMENTO] Sin texto → pedir descripción
            logger.info(f"📄 [CWT] Documento recibido de {user_id} (sin texto)")
            msg_resp = "Gracias por el documento. Para poder ayudarte mejor, ¿podrías indicar qué necesitas con él? 📝"
            executor.submit(enviar_mensaje_chatwoot, account_id, conversation_id, msg_resp, client_id, business_id)

        elif contact_attachments:
            # [CONTACTO] Tarjeta de contacto compartida
            contact_name = mensaje or '(sin nombre)'
            phones = [a.get('fallback_title', '') for a in contact_attachments if a.get('fallback_title')]
            phones_str = ', '.join(phones) if phones else '(sin teléfono)'
            logger.info(f"👤 [CWT] Contacto compartido por {user_id} → Nombre: {contact_name} | Teléfonos: {phones_str}")
            msg_resp = f"Recibí el contacto de *{contact_name}* ({phones_str}). ¿En qué puedo ayudarte con respecto a esta persona? 📋"
            executor.submit(enviar_mensaje_chatwoot, account_id, conversation_id, msg_resp, client_id, business_id)

        elif location_attachment:
            # [UBICACIÓN] Coordenadas geográficas compartidas
            lat  = location_attachment.get('coordinates_lat')
            long = location_attachment.get('coordinates_long')
            title = location_attachment.get('fallback_title') or ''
            maps_url = f"https://www.google.com/maps?q={lat},{long}"
            loc_info = f"lat={lat}, long={long}" + (f", título='{title}'" if title else '')
            logger.info(f"📍 [CWT] Ubicación recibida de {user_id} → {loc_info} | Maps: {maps_url}")
            msg_resp = f"Recibí tu ubicación 📍" + (f" (*{title}*)" if title else '') + f".\nPuedes verla aquí: {maps_url}\n¿En qué puedo ayudarte?"
            executor.submit(enviar_mensaje_chatwoot, account_id, conversation_id, msg_resp, client_id, business_id)

        elif mensaje:
            # [TEXTO] Mensaje de texto normal (puede venir con o sin attachment adjunto)
            executor.submit(
                procesar_y_responder_chatwoot,
                business_id,
                user_id,
                mensaje,
                conversation_id,
                account_id,
                client_name,
                client_id,
                ttl_minutos
            )
        else:
            logger.warning(f"⚠️ [CWT] Mensaje sin contenido reconocido para conv={conversation_id}, ignorando.")

        return jsonify({"status": "recibido"}), 200

    except Exception as e:
        logger.error(f"🔴 Error en webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/webhook/evoapi', methods=['POST'])
def webhook():
    """Endpoint para recibir webhooks de Evolution API - CON CONCURRENCIA"""

    try:
        msg_id = "-"
        payload = request.json
        logger.info(f"📨 Received webhook payload: {json.dumps(payload)}...")
        
        # Extraer información del mensaje de Evolution API
        if payload.get('event') == 'messages.upsert':
            mensaje_data = payload.get('data', {})
            
            # Intentar extraer mensaje de texto
            mensaje = mensaje_data.get('message', {}).get('conversation') or \
                     mensaje_data.get('message', {}).get('extendedTextMessage', {}).get('text', '')
            
            # Verificar si es un audio, imagen, video, documento u otro archivo
            audio_message = mensaje_data.get('message', {}).get('audioMessage')
            image_message = mensaje_data.get('message', {}).get('imageMessage')
            video_message = mensaje_data.get('message', {}).get('videoMessage')
            document_message = mensaje_data.get('message', {}).get('documentMessage')
            sticker_message = mensaje_data.get('message', {}).get('stickerMessage')
            
            user_id = mensaje_data.get('key', {}).get('remoteJid', '')
            from_me = mensaje_data.get('key', {}).get('fromMe', False)
            msg_id = mensaje_data.get('key', {}).get('id', '-')
            push_name = mensaje_data.get('pushName', '') or mensaje_data.get('verifiedBizName', '')
            client_id = user_id.split('@')[0] if user_id else "unknown" #telefono

            # Intentar obtener instance/id proporcionado en el webhook desde Evolution API
            business_id = payload.get('instance') or None
            instance_id = mensaje_data.get('instanceId') or None

            # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
            if user_id and not from_me and DDOS_PROTECTION_ENABLED and ddos_protection:
                puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id)
                if not puede_procesar:
                    logger.warning(f"⛔ DDoS Protection: bloqueando mensaje de {user_id}: {mensaje_error}")
                    # NO enviar mensaje automático para prevenir loops
                    return jsonify({"status": "blocked", "reason": "rate_limit", "message": mensaje_error}), 429
                else:
                    logger.debug(f"🛡️ DDoS Protection: mensaje permitido de {user_id}")
            
            # Obtener configuraciones específicas del negocio (como TTL, mensaje HITL, etc.)
            info_negocio = ClienteConfig(business_id)
            ttl_minutos = info_negocio.ttl_sesion_minutos or 60
            audio_transcripcion = info_negocio.audio_transcripcion or True

            #[TEXTO] Procesar mensaje de texto normal
            if mensaje and user_id and not from_me:          
                msg = f"[RCV <- EVO] 📨 ID: {client_id} - MSG: {mensaje[:100]}..."
                generar_resumen_auditoria(business_id, msg)
                #enviar_lista_whatsapp(user_id, "Gracias por tu mensaje. Estoy procesando tu consulta... ⏳", business_id)
                executor.submit(procesar_y_responder_evoapi, business_id, user_id, mensaje, push_name, ttl_minutos)    
            else:
                logger.debug("No es mensaje de texto o es de 'from_me', saltando procesamiento de texto.")

            # [MULTIMEDIA] Procesamiento de imágenes, videos, documentos y stickers
            if (image_message or video_message or document_message or sticker_message) and not from_me and user_id:
                tipo_archivo = "imagen" if image_message else \
                               "video" if video_message else \
                               "documento" if document_message else \
                               "sticker"
                
                logger.info(f"Incomming {tipo_archivo.upper()} from {user_id} ({push_name})")
                
                # Procesar imágenes con AI Vision
                if image_message:
                    logger.info(f"🖼️ Procesando imagen de {user_id}. Analizando con AI Vision...")
                    executor.submit(worker_procesar_imagen, business_id, user_id, msg_id, mensaje_data, push_name)
                else:
                    # Para videos, documentos y stickers, pedir texto
                    msg = f"Gracias por tu {tipo_archivo}. Para poder ayudarte mejor, ¿podrías escribir tu consulta como texto? 📝"
                    executor.submit(enviar_texto_whatsapp, user_id, msg, business_id)
            
            # [AUDIO] Si es un mensaje de audio
            if audio_message and audio_message.get("ptt") and not from_me and user_id:
                if audio_transcripcion:
                    logger.info(f"🔊 Procesando audio de {user_id}. Transcribiendo y analizando con IA...")
                    executor.submit(worker_procesar_audio, business_id, user_id, msg_id, mensaje_data, push_name, ttl_minutos)
                else:
                    logger.info(f"🔊 Audio recibido de {user_id}, pero la transcripción está deshabilitada. Enviando mensaje para pedir texto.")
                    msg = f"Gracias por tu nota de voz. Para poder ayudarte mejor, ¿podrías escribir tu consulta como texto? 📝"
                    executor.submit(enviar_texto_whatsapp, user_id, msg, business_id)
        
        # [LISTA] Soporte alternativo para formato con lista de mensajes
        for msg in payload.get("messages", []):
            if msg.get("type") == "conversation":
                user_id = msg["key"]["remoteJid"]
                text = msg["message"]["conversation"]
                from_me = msg["key"].get("fromMe", False)
                push_name = msg.get('pushName', '') or msg.get('verifiedBizName', '')
                client_id = user_id.split('@')[0] if user_id else "unknown"
                
                if text and user_id and not from_me:
                    msg = f"[RCV <- EVO] 📄 ID: {client_id} - MSG: {text[:100]}..."
                    generar_resumen_auditoria(business_id, msg)
                    executor.submit(procesar_y_responder_evoapi, business_id, user_id, text, push_name, ttl_minutos)  
                else:
                    logger.warning("⚠️[LIST] No se pudo procesar, enviando mensaje genérico")
                    msg = f"No pudimos procesar tu solicitud."
                    executor.submit(enviar_texto_whatsapp, user_id, msg, business_id)
        
        # Responder inmediatamente (sin esperar procesamiento)
        logger.debug(f"Responding to webhook immediately with 200 OK - ID: {msg_id}")
        return jsonify({"status": "accepted"}), 200
    
    except Exception as e:
        logger.error(f"🔴 Error en webhook /webhook/evoapi: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# Endpoint para borrar memoria de un usuario específico
@app.route('/borrar_memoria', methods=['DELETE'])
def borrar_memoria():
    """Endpoint para borrar la memoria de un usuario específico."""    

    try:
        logger.debug("[RCV <- WEB] Received Endpoint \"borrar_memoria\" payload: {}", request.data[:500])  
        data = request.json
        # Necesitamos reconstruir el thread_id para saber qué borrar
        user_id = data.get('user_id')
        business_id = data.get('business_id')
        logger.info(f"Request to delete memory for business_id={business_id}, user_id={user_id}")
        if not user_id or not business_id:
            return jsonify({"error": "Faltan IDs"}), 400

        thread_id = f"{business_id}:{user_id}"

        with pool.connection() as conn:
            # Usamos conn.cursor() para ejecutar SQL crudo
            with conn.cursor() as cur:
                # 1. Borrar checkpoints (el estado principal)
                cur.execute(
                    "DELETE FROM checkpoints WHERE thread_id = %s", 
                    (thread_id,)
                )
                # 2. Borrar escrituras pendientes/auxiliares
                cur.execute(
                    "DELETE FROM checkpoint_writes WHERE thread_id = %s", 
                    (thread_id,)
                )
                # 3. Borrar blobs (datos grandes serializados)
                cur.execute(
                    "DELETE FROM checkpoint_blobs WHERE thread_id = %s", 
                    (thread_id,)
                )
                logger.info(f"Memoria borrada para thread_id={thread_id}")

        return jsonify({
            "status": "MEMORIA_BORRADA", 
            "message": f"Historial eliminado para {thread_id}"
        })

    except Exception as e:
        logger.error(f"🔴 Error borrando DB: {e}")
        return jsonify({"error": "Error al borrar memoria"}), 500


def ejecutar_reactivar_bot(business_id: str, user_id: str) -> bool:
    """Función para ejecutar la reactivación del bot. Se puede llamar desde un script o tarea programada."""
    try:
        thread_id = f"{business_id}:{user_id}"
        logger.info(f"🔄 Reactivando bot para {thread_id}")

        # Inyectamos un mensaje "falso" de Tool o System que contenga la clave "BOT_REACTIVADO"
        # Usamos ToolMessage para que sea consistente con la lógica de herramientas
        mensaje_reactivacion = ToolMessage(
            content="✅ ACCIÓN ADMINISTRATIVA: BOT_REACTIVADO. El humano ha terminado la intervención. Puedes volver a responder.",
            tool_call_id="admin_override_action"
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
                "business_id": business_id
            }
        }

        with pool.connection() as conn:
            checkpointer = PostgresSaver(conn)
            # Usamos update_state para inyectar el mensaje sin ejecutar el LLM
            # Esto simplemente agrega el mensaje al historial
            workflow_builder.compile(checkpointer=checkpointer).update_state(
                config,
                {"messages": [mensaje_reactivacion]},
                as_node="chatbot" # O el nodo que corresponda
            )
        
        client_id = thread_id.split(':')[1].split('@')[0] if thread_id else "unknown"
        msg = f"[---TOOL---] 🔧 ID: {client_id} - MSG: ACCIÓN ADMINISTRATIVA: BOT_REACTIVADO"
        generar_resumen_auditoria(business_id, msg)
        logger.info(f"Bot reactivado exitosamente para {thread_id}")
        return True

    except Exception as e:
        logger.error(f"🔴 Error ejecutando reactivación del bot: {e}")
        return False

@app.route('/reactivar_bot_web', methods=['GET'])
def reactivar_bot_web():
    """
    Reactiva al bot mediante Token Seguro (JWT).
    Uso: /reactivar_bot?token=eyJ...
    """
    token = request.args.get('token')
    
    if not token:
        return "❌ Error: Falta el token de seguridad.", 400
    
    try:
        # 🤖 DETECTAR SI ES UN BOT/CRAWLER (WhatsApp, Facebook, etc.)
        user_agent = request.headers.get('User-Agent', '')
        
        # Log completo para debugging
        logger.info(f"🔍 Reactivación solicitada - User-Agent: {user_agent}")
        logger.info(f"🔍 Headers completos: {dict(request.headers)}")
        
        user_agent_lower = user_agent.lower()
        is_crawler = any([
            'whatsapp' in user_agent_lower,
            'facebookexternalhit' in user_agent_lower,
            'facebot' in user_agent_lower,
            'bot' in user_agent_lower and 'google' in user_agent_lower,
            'telegram' in user_agent_lower,
            'slackbot' in user_agent_lower,
            'preview' in user_agent_lower,
            'crawler' in user_agent_lower,
            'spider' in user_agent_lower,
            # Patrones adicionales comunes
            user_agent == '',  # User-Agent vacío suele ser crawler
            'curl' in user_agent_lower,
            'wget' in user_agent_lower,
            user_agent_lower == 'node',  # Evolution API / WhatsApp preview fetcher
            'read-aloud' in user_agent_lower,  # Google-Read-Aloud bot
            'googlebot' in user_agent_lower,  # Google crawler
        ])
        
        # Si es un crawler, devolver solo metadata (Open Graph) sin ejecutar la acción
        if is_crawler:
            logger.warning(f"🤖 CRAWLER DETECTADO: {user_agent[:150]} - Bloqueando reactivación automática")
            
            # URL de la imagen para el preview (puede ser personalizada por negocio)
            preview_image_url = f"{os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')}/static/og-preview.png"
                   
            return f"""
            <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    
                    <!-- Open Graph / WhatsApp Preview -->
                    <meta property="fb:app_id" content="{os.getenv('META_APP_ID', '')}" />
                    <meta property="og:title" content="🚨 *SOLICITUD DE ASISTENCIA*" />
                    <meta property="og:description" content="Toca aquí para reactivar la conversación con el bot" />
                    <meta property="og:type" content="website" />
                    <meta property="og:image" content="{preview_image_url}" />
                    <meta property="og:image:type" content="image/png" />
                    <meta property="og:image:width" content="1200" />
                    <meta property="og:image:height" content="630" />
                    <meta property="og:image:alt" content="Reactivar Bot" />
                    
                    <!-- Twitter Card (por si acaso) -->
                    <meta name="twitter:card" content="summary_large_image" />
                    <meta name="twitter:title" content="🚨 *SOLICITUD DE ASISTENCIA*" />
                    <meta name="twitter:description" content="Toca aquí para reactivar la conversación con el bot" />
                    <meta name="twitter:image" content="{preview_image_url}" />
                    
                    <!-- SEO -->
                    <meta name="robots" content="noindex, nofollow" />
                    <title>Reactivar Bot - SisAgent</title>
                </head>
                <body style="font-family: sans-serif; text-align: center; padding: 40px; background: #f5f5f5;">
                    <h1 style="color: #666;">⚠️ Preview Mode</h1>
                    <p style="color: #999;">Este enlace debe ser abierto manualmente para activar la acción.</p>
                    <p style="color: #ccc; font-size: 12px; margin-top: 40px;">Bot detection active</p>
                </body>
            </html>
            """, 200
        
        # 1. Decodificar y Validar (Si esto pasa, los datos son auténticos)
        logger.info(f"✅ Usuario real detectado (no crawler) - User-Agent: {user_agent[:100]}")
        business_id, user_id = decodificar_token_reactivacion(token)

        thread_id = f"{business_id}:{user_id}"
        
        # 2. Lógica de Reactivación (Igual que antes)
        logger.info(f"🔓 Token validado. Reactivando {thread_id}")

        if ejecutar_reactivar_bot(business_id, user_id):
            return f"""
            <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Bot Reactivado</title>
                </head>
                <body style="font-family: sans-serif; text-align: center; padding: 80px;">
                    <h1 style="color: green;">✅ Bot Reactivado</h1>
                    <p>El cliente <b>{user_id.split('@')[0]}</b> ya puede hablar con el Bot nuevamente.</p>
                    <p style="color: #666;">Negocio: {thread_id.split(':')[0]}</p>
                    <p style="color: #666;"><b>Puedes cerrar esta ventana.</b></p>
                    <p id="message" style="color: #666; margin-top: 20px;"></p>
                </body>
            </html>
            """, 200
        else:
            return jsonify({"error": "Error al reactivar el bot"}), 500

    except ValueError as ve:
        # Error de token expirado o inválido
        return f"<html><body style='text-align:center; color:red;'><h1>⛔ Enlace Inválido</h1><p>{str(ve)}</p></body></html>", 403
    except Exception as e:
        logger.exception(f"🔴 Error reactivando bot: {e}")
        return "Error interno del servidor", 500


@app.route('/reactivar_bot', methods=['POST'])
def reactivar_bot():
    """
    Inserta un mensaje de sistema invisible para 'despertar' al bot
    después de una intervención humana.
    """
    try:
        logger.debug("[RCV <- WEB] Received Endpoint \"reactivar_bot\" payload: {}", request.data[:500])  
        data = request.json
        user_id = data.get('user_id')
        business_id = data.get('business_id')
        
        if not user_id or not business_id:
            return jsonify({"error": "Faltan IDs"}), 400

        if ejecutar_reactivar_bot(business_id, user_id):
            return jsonify({"status": "BOT_REACTIVADO", "message": "El bot volverá a responder mensajes nuevos."})
        else:
            return jsonify({"error": "Error al reactivar el bot"}), 500

    except Exception as e:
        logger.exception(f"🔴 Error reactivando bot: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    try:
        # 1. Datos obligatorios
        mensaje = data.get('message')
        user_id = data.get('user_id')         # Ej: "549111234567"
        business_id = data.get('business_id') # Ej: "negocio_zapatillas"

        #Devolver el diccionario tal cual (Flask lo convierte a JSON)
        return adaptar_procesar_mensaje(business_id, user_id, mensaje, ttl_minutos=120)

    except Exception as e:
        logger.error(f"🔴 Error: {e}") 
        return jsonify({"response": "No se pudo procesar su solicitud.", "status": "ERROR"}), 500

from datetime import datetime, timedelta

@app.route('/api/metrics', methods=['GET'])
def get_business_metrics():
    """
    Endpoint para obtener métricas agregadas de un negocio.
    Params:
        - business_id (obligatorio)
        - start_date (opcional, YYYY-MM-DD)
        - end_date (opcional, YYYY-MM-DD)
    """
    try:
        # 1. Obtener parámetros
        business_id = request.args.get('business_id')
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        if not business_id:
            return jsonify({"error": "Falta el parámetro 'business_id'"}), 400

        # 2. Definir rango de fechas (Default: últimos 30 días)
        if not end_date_str:
            end_date = datetime.now()
        else:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1) # Incluir el día completo

        if not start_date_str:
            start_date = end_date - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')

        logger.info(f"📊 Consultando métricas para {business_id} desde {start_date} hasta {end_date}")

        metrics = {
            "period": {
                "start": start_date.strftime('%Y-%m-%d'),
                "end": end_date.strftime('%Y-%m-%d')
            },
            "summary": {},
            "models_breakdown": [],
            "sentiment_breakdown": {}
        }

        with pool.connection() as conn:
            with conn.cursor() as cur:
                
                # --- QUERY 1: RESUMEN GENERAL (KPIs) ---
                sql_summary = """
                    SELECT 
                        COUNT(*) as total_interactions,
                        COALESCE(SUM(input_tokens), 0) as total_input,
                        COALESCE(SUM(output_tokens), 0) as total_output,
                        COALESCE(SUM(estimated_cost), 0.0) as total_cost,
                        COALESCE(AVG(latency_ms), 0)::INT as avg_latency
                    FROM analytics_events 
                    WHERE business_id = %s 
                    AND timestamp >= %s AND timestamp < %s
                """
                cur.execute(sql_summary, (business_id, start_date, end_date))
                row = cur.fetchone()
                
                metrics["summary"] = {
                    "total_interactions": row[0],
                    "total_input_tokens": row[1],
                    "total_output_tokens": row[2],
                    "total_tokens": row[1] + row[2],
                    "total_cost_usd": round(row[3], 6),
                    "avg_latency_ms": row[4]
                }

                # --- QUERY 2: DESGLOSE POR MODELO (Primary vs Backup) ---
                sql_models = """
                    SELECT model_name, COUNT(*), SUM(estimated_cost)
                    FROM analytics_events 
                    WHERE business_id = %s 
                    AND timestamp >= %s AND timestamp < %s
                    AND model_name IS NOT NULL
                    GROUP BY model_name
                    ORDER BY COUNT(*) DESC
                """
                cur.execute(sql_models, (business_id, start_date, end_date))
                for m_row in cur.fetchall():
                    metrics["models_breakdown"].append({
                        "model": m_row[0],
                        "usage_count": m_row[1],
                        "cost": round(m_row[2] or 0, 6)
                    })

                # --- QUERY 3: SENTIMIENTO (Si lo estás guardando) ---
                sql_sentiment = """
                    SELECT sentiment_label, COUNT(*)
                    FROM analytics_events 
                    WHERE business_id = %s 
                    AND timestamp >= %s AND timestamp < %s
                    AND sentiment_label IS NOT NULL
                    GROUP BY sentiment_label
                """
                cur.execute(sql_sentiment, (business_id, start_date, end_date))
                for s_row in cur.fetchall():
                    metrics["sentiment_breakdown"][s_row[0]] = s_row[1]

        return jsonify(metrics)

    except ValueError:
        return jsonify({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}), 400
    except Exception as e:
        logger.exception(f"🔴 Error obteniendo métricas: {e}")
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# ENDPOINTS DE GESTIÓN DE CLIENTES (config_negocios.json)
# ==============================================================================

@app.route('/api/get-tools', methods=['GET'])
def listar_tools():
    """Obtiene la lista completa de herramientas disponibles."""
    try:
        tools = obtener_todas_las_tools()
        logger.info(f"📋 Listando {len(tools)} herramientas (raw objects)")

        # Obtener clientes que usan cada tool (desde config hot-reload)
        config = obtener_configuraciones()
        clients_map: dict = {}
        for business_id, conf in (config or {}).items():
            if not isinstance(conf, dict):
                continue
            for t in conf.get('tools_habilitadas', []) or []:
                if isinstance(t, str):
                    clients_map.setdefault(t, []).append(business_id)

        tools_meta = []
        for t in tools:
            # Usar el atributo .name del tool object directamente
            tool_name = getattr(t, 'name', None) or getattr(t, '__name__', str(t))
            description = getattr(t, 'description', None) or (t.__doc__ if hasattr(t, '__doc__') else '')
            
            tools_meta.append({
                "name": tool_name,
                "description": description or "",
                "module": getattr(t, '__module__', ''),
                "clients": clients_map.get(tool_name, [])
            })

        logger.info(f"📋 Entregando {len(tools_meta)} herramientas (serializables)")
        return jsonify(tools_meta), 200
    except Exception as e:
        logger.exception(f"🔴 Error listando herramientas: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/config/clientes', methods=['GET'])
def listar_clientes():
    """Obtiene la lista completa de clientes."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config_negocios.json')
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        logger.info(f"📋 Listando {len(config)} clientes")
        return jsonify(config), 200
        
    except Exception as e:
        logger.exception(f"🔴 Error listando clientes: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/config/clientes/<business_id>', methods=['GET'])
def obtener_cliente(business_id):
    """Obtiene la configuración de un cliente específico."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config_negocios.json')
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if business_id not in config:
            logger.warning(f"⚠️ Cliente {business_id} no encontrado")
            return jsonify({"error": f"Cliente {business_id} no existe"}), 404
        
        logger.info(f"📄 Obteniendo configuración de cliente {business_id}")
        return jsonify(config[business_id]), 200
        
    except Exception as e:
        logger.exception(f"🔴 Error obteniendo cliente {business_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/config/clientes/<business_id>', methods=['PUT'])
def actualizar_cliente_completo(business_id):
    """Actualiza completamente la configuración de un cliente (reemplaza todo)."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config_negocios.json')
        
        # Cargar configuración actual
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if business_id not in config:
            logger.warning(f"⚠️ Cliente {business_id} no encontrado")
            return jsonify({"error": f"Cliente {business_id} no existe"}), 404
        
        # Obtener datos del request
        nuevos_datos = request.json
        if not nuevos_datos:
            return jsonify({"error": "No se enviaron datos"}), 400
        
        # Validar campos requeridos
        campos_requeridos = ['nombre', 'ttl_sesion_minutos', 'admin_phone']
        for campo in campos_requeridos:
            if campo not in nuevos_datos:
                return jsonify({"error": f"Campo requerido faltante: {campo}"}), 400
        
        # Reemplazar completamente
        config[business_id] = nuevos_datos
        
        # Guardar archivo
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        logger.success(f"✅ Cliente {business_id} actualizado completamente")
        return jsonify({
            "status": "success",
            "message": f"Cliente {business_id} actualizado",
            "data": config[business_id]
        }), 200
        
    except Exception as e:
        logger.exception(f"🔴 Error actualizando cliente {business_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/config/clientes/<business_id>', methods=['PATCH'])
def actualizar_cliente_parcial(business_id):
    """Actualiza parcialmente la configuración de un cliente (solo los campos enviados)."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config_negocios.json')
        
        # Cargar configuración actual
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if business_id not in config:
            logger.warning(f"⚠️ Cliente {business_id} no encontrado")
            return jsonify({"error": f"Cliente {business_id} no existe"}), 404
        
        # Obtener datos del request
        actualizaciones = request.json
        if not actualizaciones:
            return jsonify({"error": "No se enviaron datos para actualizar"}), 400
        
        # Actualizar solo los campos enviados (merge recursivo para objetos anidados)
        def merge_dicts(base, updates):
            """Merge recursivo de diccionarios."""
            for key, value in updates.items():
                if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                    merge_dicts(base[key], value)
                else:
                    base[key] = value
        
        merge_dicts(config[business_id], actualizaciones)
        
        # Guardar archivo
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        logger.success(f"✅ Cliente {business_id} actualizado parcialmente: {list(actualizaciones.keys())}")
        return jsonify({
            "status": "success",
            "message": f"Cliente {business_id} actualizado",
            "updated_fields": list(actualizaciones.keys()),
            "data": config[business_id]
        }), 200
        
    except Exception as e:
        logger.exception(f"🔴 Error actualizando cliente {business_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/config/clientes/<business_id>', methods=['DELETE'])
def eliminar_cliente(business_id):
    """Elimina un cliente de la configuración."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config_negocios.json')
        
        # Cargar configuración actual
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        if business_id not in config:
            logger.warning(f"⚠️ Cliente {business_id} no encontrado")
            return jsonify({"error": f"Cliente {business_id} no existe"}), 404
        
        # Guardar copia antes de eliminar
        cliente_eliminado = config[business_id]
        
        # Eliminar
        del config[business_id]
        
        # Guardar archivo
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        logger.warning(f"🗑️ Cliente {business_id} eliminado")
        return jsonify({
            "status": "success",
            "message": f"Cliente {business_id} eliminado",
            "deleted_data": cliente_eliminado
        }), 200
        
    except Exception as e:
        logger.exception(f"🔴 Error eliminando cliente {business_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/config/clientes', methods=['POST'])
def crear_cliente():
    """Crea un nuevo cliente en la configuración."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config_negocios.json')
        
        # Cargar configuración actual
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Obtener datos del request
        nuevos_datos = request.json
        if not nuevos_datos:
            return jsonify({"error": "No se enviaron datos"}), 400
        
        # Validar que se envíe el business_id
        business_id = nuevos_datos.get('business_id')
        if not business_id:
            return jsonify({"error": "Campo 'business_id' es requerido"}), 400
        
        # Verificar que no exista
        if business_id in config:
            return jsonify({"error": f"Cliente {business_id} ya existe"}), 409
        
        # Validar campos requeridos
        campos_requeridos = ['nombre', 'ttl_sesion_minutos', 'admin_phone']
        for campo in campos_requeridos:
            if campo not in nuevos_datos:
                return jsonify({"error": f"Campo requerido faltante: {campo}"}), 400
        
        # Estructura por defecto si no se proporciona
        nuevo_cliente = {
            "nombre": nuevos_datos['nombre'],
            "ttl_sesion_minutos": nuevos_datos['ttl_sesion_minutos'],
            "admin_phone": nuevos_datos['admin_phone'],
            "fuera_de_servicio": nuevos_datos.get('fuera_de_servicio', {
                "activo": False,
                "horario_inicio": "09:00",
                "horario_fin": "18:00",
                "dias_laborales": [1, 2, 3, 4, 5],
                "zona_horaria": "America/Argentina/Buenos_Aires",
                "mensaje": []
            }),
            "system_prompt": nuevos_datos.get('system_prompt', []),
            "mensaje_HITL": nuevos_datos.get('mensaje_HITL', ""),
            "mensaje_usuario_1": nuevos_datos.get('mensaje_usuario_1', []),
            "tools_habilitadas": nuevos_datos.get('tools_habilitadas', [])
        }
        
        # Agregar a la configuración
        config[business_id] = nuevo_cliente
        
        # Guardar archivo
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        logger.success(f"✅ Cliente {business_id} creado exitosamente")
        return jsonify({
            "status": "success",
            "message": f"Cliente {business_id} creado",
            "data": nuevo_cliente
        }), 201
        
    except Exception as e:
        logger.exception(f"🔴 Error creando cliente: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/ver-grafo', methods=['GET'])
def ver_grafo_png():
    try:       
        logger.info("Generando grafo de estados del agente para visualización...")

        # 1. Compilamos el grafo para poder dibujarlo
        app_visual = workflow_builder.compile()

        # 2. Generamos los bytes del PNG 
        # (Esto usa la API de Mermaid automáticamente, no requiere configuración extra)
        png_bytes = app_visual.get_graph().draw_mermaid_png()

        # 3. Retornamos la imagen al navegador
        return Response(png_bytes, mimetype='image/png')

    except Exception as e:
        return f"Error generando grafo: {str(e)}", 500

# curl -sS http://localhost:5001/health
# curl -sS http://sisagent.sisnova.org/health
@app.route('/health', methods=['GET'])
def status():
    logger.info("🔍 Health check endpoint called")
    return jsonify({"status": "ok"}), 200


# Webhook para recibir código de autorización de Google Calendar OAuth
@app.route('/oauth/calendar/callback', methods=['GET'])
def calendar_oauth_callback():
    """
    Recibe el código de autorización de Google OAuth y completa la autenticación automáticamente.
    Parámetros esperados: code, state (opcional), business_id (en state)
    """
    try:
        logger.info(f"📨 Callback OAuth recibido") #{request}")
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')
        
        logger.info(f"📨 Callback OAuth recibido - Code: {code[:20] if code else None}... State: {state}")
        
        if error:
            logger.error(f"❌ Error en OAuth: {error}")
            return f"""
            <html>
                <head><title>Error - Autorización</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>❌ Error en la autorización</h1>
                    <p>Hubo un problema: {error}</p>
                    <p>Por favor, vuelve a intentarlo desde WhatsApp.</p>
                </body>
            </html>
            """, 400
        
        if not code:
            logger.error("❌ No se recibió código de autorización")
            return """
            <html>
                <head><title>Error - Sin código</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>❌ Error</h1>
                    <p>No se recibió el código de autorización.</p>
                </body>
            </html>
            """, 400
        
        # Extraer business_id del state si está presente
        business_id = "cliente1"  # Default
        if state and ':' in state:
            parts = state.split(':')
            if len(parts) >= 2:
                business_id = parts[1]
        
        # Limpiar cualquier corrupción de caracteres (por si acaso)
        business_id = business_id.strip().rstrip(')*').strip()
        
        logger.info(f"🔐 Procesando autorización para business_id: {business_id}")
        
        # Importar la función de autenticación
        from tools_calendar import authenticate_with_code
        
        # Autenticar y obtener credenciales
        creds = authenticate_with_code(code)
        
        # Guardar token
        if not os.path.exists("tokens_calendar"):
            os.makedirs("tokens_calendar")
        token_file = f"tokens_calendar/{business_id}_token.json"
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
        
        logger.info(f"✅ Token guardado exitosamente para {business_id}")
        
        return f"""
        <html>
            <head>
                <title>✅ Autorización Exitosa</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        margin: 0;
                        padding: 20px;
                        min-height: 100vh;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    }}
                    .container {{
                        background: white;
                        border-radius: 20px;
                        padding: 40px;
                        max-width: 500px;
                        box-shadow: 0 10px 50px rgba(0,0,0,0.3);
                        text-align: center;
                    }}
                    h1 {{
                        color: #10b981;
                        font-size: 2.5em;
                        margin: 0 0 20px 0;
                    }}
                    p {{
                        color: #64748b;
                        font-size: 1.1em;
                        line-height: 1.6;
                    }}
                    .success-icon {{
                        font-size: 5em;
                        margin-bottom: 20px;
                    }}
                    .button {{
                        background: #667eea;
                        color: white;
                        padding: 15px 30px;
                        border-radius: 10px;
                        text-decoration: none;
                        display: inline-block;
                        margin-top: 20px;
                        font-weight: bold;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="success-icon">✅</div>
                    <h1>¡Autorización Exitosa!</h1>
                    <p><strong>Tu Google Calendar está conectado.</strong></p>
                    <p>Ya puedes cerrar esta ventana y volver a WhatsApp para agendar tu cita.</p>
                    <p style="font-size: 0.9em; color: #94a3b8; margin-top: 30px;">
                        Business ID: {business_id}
                    </p>
                </div>
            </body>
        </html>
        """, 200
        
    except Exception as e:
        logger.error(f"❌ Error en callback OAuth: {e}")
        return f"""
        <html>
            <head><title>Error - Autorización</title></head>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1>❌ Error al procesar la autorización</h1>
                <p>{str(e)}</p>
                <p>Por favor, contacta con soporte.</p>
            </body>
        </html>
        """, 500

@app.route('/politica-privacidad')
@app.route('/privacy')
@app.route('/politica-de-privacidad')
def privacy_policy():
    logger.info("📄 Política de privacidad solicitada")
    return render_template_string(politica_privacidad_html)

@app.route('/')
def home():
    base_url = os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SisAgent _ Asistente Virtual</title>
  <!-- Open Graph / WhatsApp link preview -->
  <meta property="fb:app_id"       content="{os.getenv('META_APP_ID', '')}" />
  <meta property="og:type"        content="website" />
  <meta property="og:url"         content="{base_url}/" />
  <meta property="og:title"       content="SisAgent Asistente Virtual" />
  <meta property="og:description" content="Descubrí la nueva forma de interactuar con tu negocio a través de WhatsApp" />
  <meta property="og:image"        content="{base_url}/static/og-preview.png" />
  <meta property="og:image:type"   content="image/png" />
  <meta property="og:image:width"  content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt"    content="SisAgent" />
</head>
<body style="font-family:sans-serif;text-align:center;padding:60px;">
  <h1>Bienvenido a SisAgent</h1>
  <p>Política de privacidad: <a href='/politica-privacidad'>/politica-privacidad</a></p>
</body>
</html>"""

# Configuraciones (poné en .env en producción)
META_APP_ID = os.getenv("META_APP_ID", "TU_APP_ID")  # ID de tu app en Meta for Developers
META_APP_SECRET = os.getenv("META_APP_SECRET", "TU_APP_SECRET")  # Si necesitás intercambiar code por token
REDIRECT_URI = f"{os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')}/callback/whatsapp"  # Debe coincidir con Meta

class EvolutionInstanceCreate(BaseModel):
    instanceName: str
    integration: str = "WHATSAPP-BUSINESS"
    token: str  # Permanent Access Token
    number: str  # Phone Number ID (ej: "123456789012345")
    qrcode: bool = False  # No QR para Cloud API

@app.route("/callback/whatsapp", methods=['GET'])
def whatsapp_callback():
    code = request.args.get('code')
    waba_id = request.args.get('waba_id')
    phone_number_id = request.args.get('phone_number_id')
    error = request.args.get('error')
    error_description = request.args.get('error_description')

    if error:
        logger.error(f"Error en Embedded Signup: {error} - {error_description}")
        return f"<h1>Error: {error_description}</h1><p>Contacta soporte.</p>"

    # Caso 1: Embedded Signup envía datos directamente via params (común en v4+ con helper)
    if phone_number_id and waba_id:
        logger.info(f"Recibidos directamente: Phone ID={phone_number_id}, WABA ID={waba_id}")
        import asyncio
        asyncio.run(create_evolution_instance(phone_number_id, waba_id))
        return "<h1>¡Conexión exitosa!</h1><p>Tu WhatsApp está siendo configurado en Evolution. Redirigiendo...</p>"

    # Caso 2: Viene 'code' → intercambiar por token y obtener datos (OAuth flow manual)
    if code:
        try:
            token_url = "https://graph.facebook.com/v21.0/oauth/access_token"
            params = {
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "redirect_uri": REDIRECT_URI,
                "code": code
            }
            resp = requests.get(token_url, params=params)
            resp.raise_for_status()
            token_data = resp.json()
            access_token = token_data.get("access_token")

            graph_url = f"https://graph.facebook.com/v21.0/me?fields=whatsapp_business_accounts{{phone_numbers{{id,name}}}}&access_token={access_token}"
            graph_resp = requests.get(graph_url)
            graph_resp.raise_for_status()
            data = graph_resp.json()

            waba = data.get("whatsapp_business_accounts", {}).get("data", [{}])[0]
            phone = waba.get("phone_numbers", {}).get("data", [{}])[0]
            phone_number_id = phone.get("id")
            waba_id = waba.get("id")

            if not phone_number_id:
                raise ValueError("No se encontró Phone Number ID")

            logger.info(f"Obtenido via token: Phone ID={phone_number_id}, WABA ID={waba_id}")

            import asyncio
            asyncio.run(create_evolution_instance(phone_number_id, waba_id, access_token))
            return "<h1>¡Éxito!</h1><p>Instancia creada en Evolution. Podés cerrar esta ventana.</p>"

        except Exception as e:
            logger.exception("Error procesando code")
            return jsonify({"error": str(e)}), 500

    return "<h1>Callback recibido, pero faltan parámetros. Intenta de nuevo.</h1>"


@app.route("/onboard-whatsapp", methods=['GET'])
def onboard_page():
    logger.info("🔗 Página de onboarding solicitada")
    return ONBOARDING_HTML


# Endpoint principal de onboarding: recibe code + phone_number_id + waba_id desde el frontend
# El frontend los obtiene: code via FB.login() callback, phone_number_id/waba_id via postMessage
@app.route("/api/onboard-whatsapp", methods=['POST'])
def receive_embedded_data():
    data = request.json or {}
    code = data.get('code')
    phone_number_id = data.get('phone_number_id')
    waba_id = data.get('waba_id')
    business_id = data.get('business_id')

    if not code or not phone_number_id or not waba_id:
        return jsonify({"status": "error", "error": "Faltan datos requeridos (code, phone_number_id, waba_id)"}), 400

    logger.info(f"📨 Onboarding iniciado: Phone ID={phone_number_id}, WABA ID={waba_id}")

    try:
        # Paso 1: Intercambiar el código de autorización por un access token
        # El code tiene TTL de 30s, hacerlo de inmediato
        token_resp = requests.get(
            f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION','v21.0')}/oauth/access_token",
            params={
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "code": code
                # Nota: NO incluir redirect_uri para el flow iniciado por FB.login()
            },
            timeout=15
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError(f"No se obtuvo access_token: {token_data}")
        logger.info(f"✅ Token intercambiado para phone {phone_number_id}")

        graph_headers = {"Authorization": f"Bearer {access_token}"}

        # Paso 2: Registrar el número de teléfono para usar Cloud API
        # Esto es obligatorio para que el número pueda enviar/recibir mensajes via Cloud API
        register_resp = requests.post(
            f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION','v21.0')}/{phone_number_id}/register",
            headers=graph_headers,
            json={"messaging_product": "whatsapp", "pin": "000000"},
            timeout=15
        )
        if register_resp.status_code not in (200, 201):
            logger.warning(f"⚠️ Registro de teléfono respondió {register_resp.status_code}: {register_resp.text}")
        else:
            logger.info(f"✅ Número {phone_number_id} registrado en Cloud API")

        # Paso 3: Suscribir la app a los webhooks del WABA del cliente
        # Necesario para recibir mensajes entrantes en nuestro webhook
        subscribe_resp = requests.post(
            f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION','v21.0')}/{waba_id}/subscribed_apps",
            headers=graph_headers,
            timeout=15
        )
        if subscribe_resp.status_code not in (200, 201):
            logger.warning(f"⚠️ Suscripción webhooks respondió {subscribe_resp.status_code}: {subscribe_resp.text}")
        else:
            logger.info(f"✅ App suscrita a webhooks del WABA {waba_id}")

        # Paso 4: Crear instancia en Evolution API con los datos del cliente
        import asyncio
        asyncio.run(create_evolution_instance(phone_number_id, waba_id, access_token))

        return jsonify({
            "status": "ok",
            "message": "WhatsApp onboardeado exitosamente",
            "phone_number_id": phone_number_id,
            "waba_id": waba_id
        })

    except requests.HTTPError as e:
        logger.exception(f"HTTP error en onboarding: {e.response.text if e.response else e}")
        return jsonify({"status": "error", "error": str(e)}), 500
    except Exception as e:
        logger.exception("Error en onboarding completo")
        return jsonify({"status": "error", "error": str(e)}), 500


async def create_evolution_instance(phone_number_id: str, waba_id: str, access_token: str = None):
    """
    Crea instancia en Evolution API con WHATSAPP-BUSINESS.
    Usa el permanent token (generado antes o aquí via System User).
    """
    # En producción: genera o usa un permanent token por cliente (mejor práctica)
    # Por simplicidad, asumimos que usás un token permanente de System User con acceso al WABA
    permanent_token = access_token or "TU_PERMANENT_TOKEN_CON_PERMISOS_AL_WABA_DEL_CLIENTE"

    payload = {
        "instanceName": f"cliente-{phone_number_id[-6:]}",  # Nombre único
        "integration": "WHATSAPP-BUSINESS",
        "token": permanent_token,
        "number": phone_number_id,  # ¡Este es el Phone Number ID!
        "qrcode": False,            # No QR para Cloud API
        "webhook": {
            "url": f"{os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')}/webhook/evoapi",
            "enabled": True,
            "events": ["MESSAGES_UPSERT"]
            }
    }

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{EVOLUTION_API_URL}/instance/create",
                json=payload,
                headers=headers,
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Instancia creada en Evolution: {data}")
            # Aquí podés guardar en tu DB: cliente → instanceName, instanceKey, etc.
        except httpx.HTTPStatusError as e:
            logger.error(f"Error creando instancia: {e.response.text}")
            raise

logger.info("✅ App Flask iniciada.")

if __name__ == "__main__":
    # Flask es WSGI, no ASGI - usar app.run() directamente
    try:
        app.run(
            host='0.0.0.0',
            port=int(os.getenv('APP_PORT', 5000)),
            threaded=True,  # Importante para manejar concurrencia
            debug=False
        )
    except Exception as e:
        logger.exception(f"🔴 Error iniciando Flask: {e}")


# En producción, es recomendable usar Gunicorn con workers y threads configurados para manejar la concurrencia de manera eficiente:
# gunicorn -w 4 --threads 10 -b 0.0.0.0:5000 app:app
    #finally:
        # Detener scheduler al cerrar la aplicación
        # if scheduler:
        #     scheduler.shutdown()
        #     logger.info("🔴 🟢 y 🟡, o 🟩 y 🟨, o ✅ y ⚠️Scheduler detenido")
