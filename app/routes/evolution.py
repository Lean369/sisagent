from flask import Blueprint, request, jsonify
#from ..db import get_pool
from loguru import logger
from ..logger_config import generar_resumen_auditoria
from concurrent.futures import ThreadPoolExecutor
from evolutionapi.client import EvolutionClient  # del paquete oficial
import os
import base64
import io
import json
from ..services.cliente_config import ClienteConfig
from ..utils.ddos_protection import ddos_protection
from ..services.agent import transcribir_audio, analizar_imagen_con_ai
from ..services.router import route_text_message, route_image_message, route_audio_message



evolution_bp = Blueprint('evolution', __name__)

# Pool de threads para manejar múltiples mensajes en paralelo
# CPU de 4 núcleos (max_workers=10)
# CPU de 8+ núcleos (max_workers=20)
executor = ThreadPoolExecutor(max_workers=10)  # CPU de 2 núcleos - 10 mensajes simultáneos

logger.info("🚀 Starting Evolution Blueprint...")

DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"
EVOLUTION_URL = os.environ.get("EVOLUTION_API_URL", "https://evoapi.sisnova.com.ar")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY")

client = EvolutionClient(base_url=EVOLUTION_URL, api_token=EVOLUTION_API_KEY)

@evolution_bp.route('/webhook/evoapi', methods=['POST'])
def webhook():
    """
        Endpoint para recibir webhooks de Evolution API - CON CONCURRENCIA
    """

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
            
            # Obtener configuraciones específicas del negocio (como TTL, mensaje HITL, etc.)
            info_negocio = ClienteConfig(business_id)

            audio_transcripcion = info_negocio.audio_transcripcion or True

            if DDOS_PROTECTION_ENABLED and ddos_protection:
                if mensaje:
                    puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id, mensaje)
                else:
                    puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id)
                if not puede_procesar:
                    logger.warning(f"⛔ DDoS Protection: bloqueando mensaje de {user_id}: {mensaje_error}")
                    return jsonify({"status": "blocked", "reason": "rate_limit", "message": mensaje_error}), 429 

            #[TEXTO] Procesar mensaje de texto normal
            if mensaje and user_id and not from_me:   
                msg = f"[RCV <- EVO] 📨 ID: {client_id} - MSG: {mensaje[:100]}..."
                generar_resumen_auditoria(business_id, msg)
                executor.submit(procesar_texto_evoapi, business_id, user_id, mensaje, push_name, info_negocio)    

            # [MULTIMEDIA] Procesamiento de imágenes, videos, documentos y stickers
            if (image_message or video_message or document_message or sticker_message) and not from_me and user_id:
                tipo_archivo = "imagen" if image_message else \
                               "video" if video_message else \
                               "documento" if document_message else \
                               "sticker"

                logger.info(f"Incomming {tipo_archivo.upper()} from {user_id} ({push_name})")
                
                # Procesar imágenes y PDFs con AI Vision (PDFs vienen en documentMessage)
                if image_message or (document_message and document_message.get("mimetype") == "application/pdf"):
                    logger.info(f"🖼️ Procesando imagen de {user_id}. Analizando con AI Vision...")
                    executor.submit(procesar_imagen_evoapi, business_id, user_id, mensaje_data, push_name, info_negocio)
                else:
                    # Para videos, documentos y stickers, pedir texto
                    msg = f"Gracias por tu {tipo_archivo}. Para poder ayudarte mejor, ¿podrías escribir tu consulta como texto? 📝"
                    executor.submit(enviar_texto_whatsapp, user_id, msg, business_id)
            
            # [AUDIO] Si es un mensaje tipo nota de voz
            if audio_message and audio_message.get("ptt") and not from_me and user_id:
                if audio_transcripcion:
                    logger.info(f"🔊 Procesando audio de {user_id}. Transcribiendo y analizando con IA...")
                    executor.submit(procesar_audio_evoapi, business_id, user_id, mensaje_data, push_name, info_negocio)
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
                    executor.submit(procesar_texto_evoapi, business_id, user_id, text, push_name, info_negocio)  
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


def procesar_texto_evoapi(business_id, user_id, mensaje, push_name, info_negocio):
    """
        Función que corre en background:
        1. Llama al Agente IA para procesar el mensaje (Lento)
        2. Envía la respuesta por WhatsApp (I/O)
    """
    try:    
        # 1. Proceso Lento (IA)
        respuesta_ia = route_text_message(business_id, user_id, mensaje, client_name=push_name, info_negocio=info_negocio)
        
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 Agente IA terminó para {user_id}. Enviando respuesta...")
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
            logger.warning(f"⚠️ Agente IA no generó respuesta para {user_id}")
            #respuesta_ia = "Lo siento, no pude generar una respuesta en este momento."
            #enviar_texto_whatsapp(user_id, respuesta_ia, business_id)

    except Exception as e:
        logger.error(f"🔴 Error en worker background para {user_id}: {e}")


def procesar_imagen_evoapi(business_id, user_id, mensaje, push_name, info_negocio):
    """
        Función que corre en background:
        1. Llama al Agente IA para procesar la imagen (Lento)
        2. Envía la respuesta por WhatsApp (I/O)
    """
    try:    
        # 1. Proceso Lento (IA)
        respuesta_ia = route_image_message(business_id, user_id, mensaje, client_name=push_name, info_negocio=info_negocio)
        
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 Agente IA terminó para {user_id}. Enviando respuesta...")
            enviar_texto_whatsapp(user_id, respuesta_ia, business_id)
        else:
            logger.warning(f"⚠️ Agente IA no generó respuesta para {user_id}")

    except Exception as e:
        logger.error(f"🔴 Error en worker background para {user_id}: {e}")


# def procesar_pdf_evoapi(business_id, user_id, mensaje, push_name, info_negocio):
#     """
#         Función que corre en background:
#         1. Llama al Agente IA para procesar el PDF (Lento)
#         2. Envía la respuesta por WhatsApp (I/O)
#     """
#     try:    
#         # 1. Proceso Lento (IA)
#         respuesta_ia = route_pdf_message(business_id, user_id, mensaje, client_name=push_name, info_negocio=info_negocio)
        
#         # 2. Envío de respuesta
#         if respuesta_ia:
#             logger.info(f"🤖 Agente IA terminó para {user_id}. Enviando respuesta...")
#             enviar_texto_whatsapp(user_id, respuesta_ia, business_id)
#         else:
#             logger.warning(f"⚠️ Agente IA no generó respuesta para {user_id}")

#     except Exception as e:
#         logger.error(f"🔴 Error en worker background para {user_id}: {e}")


def procesar_audio_evoapi(business_id, user_id, mensaje, push_name, info_negocio):
    """
        Función que corre en background:
        1. Llama al Agente IA para procesar el audio (Lento)
        2. Envía la respuesta por WhatsApp (I/O)
    """
    try:    
        # 1. Proceso Lento (IA)
        respuesta_ia = route_audio_message(business_id, user_id, mensaje, client_name=push_name, info_negocio=info_negocio)
        
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 Agente IA terminó para {user_id}. Enviando respuesta...")
            enviar_texto_whatsapp(user_id, respuesta_ia, business_id)
        else:
            logger.warning(f"⚠️ Agente IA no generó respuesta para {user_id}")

    except Exception as e:
        logger.error(f"🔴 Error en worker background para {user_id}: {e}")


def enviar_texto_whatsapp(numero_destino: str, mensaje, nombre_instancia: str = None):
    """
        Envía un mensaje a través del cliente de Evolution API.
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


# def worker_procesar_imagen(business_id, user_id, msg_id, mensaje, push_name, info_negocio):
#     """
#         Procesa imágenes enviadas por Evolution API - WhatsApp SOLO Baileys:
#         1. Descarga la imagen desde Evolution API
#         2. Analiza la imagen con AI multimodal
#         3. Responde al usuario con el análisis
#     """
#     try:
#         logger.debug(f"[IMAGE] Procesando imagen para {user_id}, instance={business_id}")
#         telefono = user_id.split("@")[0]
        
#         # Usar el cliente evolutionapi para obtener la imagen en base64
#         endpoint = f"chat/getBase64FromMediaMessage/{business_id}"
#         payload_media = {
#             "message": {
#                 "key": mensaje.get("key"),
#                 "message": mensaje.get("message")
#             },
#             "convertToMp4": False
#         }
        
#         logger.debug(f"[IMAGE] Solicitando descarga de imagen usando evolutionapi client...")
        
#         try:
#             response = client.post(endpoint, data=payload_media)
            
#             if not response or not isinstance(response, dict):
#                 logger.error(f"❌ [IMAGE] Respuesta inválida del cliente: {response}")
#                 msg = "Disculpa, tuve problemas para procesar tu imagen. ¿Podrías describir qué necesitas? 📝"
#                 enviar_texto_whatsapp(user_id, msg, business_id)
#                 return
            
#             base64_image = response.get("base64")
            
#             if not base64_image:
#                 logger.error(f"❌ [IMAGE] No se recibió base64 en la respuesta: {response}")
#                 msg = "Disculpa, no pude procesar tu imagen. ¿Podrías describir qué necesitas? 📝"
#                 enviar_texto_whatsapp(user_id, msg, business_id)
#                 return
            
#             # Decodificar el base64 a bytes
#             image_buffer = base64.b64decode(base64_image)
#             logger.info(f"[IMAGE] Imagen descargada: {len(image_buffer)} bytes")
            
#             # Extraer caption si existe
#             caption = mensaje.get("message", {}).get("imageMessage", {}).get("caption")
            
#             # Analizar la imagen con AI
#             thread_id = f"{business_id}:{user_id}"
#             analisis = analizar_imagen_con_ai(image_buffer, thread_id, caption)
            
#             if analisis:
#                 msg = f"[RCV <- EVO] 🖼️ ID: {telefono} - IMG: {caption[:50] if caption else 'sin texto'}"
#                 generar_resumen_auditoria(business_id, msg)
                
#                 # Enviar el análisis como respuesta
#                 respuesta = f"📸 He analizado tu imagen:\n\n{analisis}"
#                 if caption:
#                     respuesta = f"📸 Vi tu imagen y el texto '{caption}'.\n\n{analisis}"
                
#                 enviar_texto_whatsapp(user_id, respuesta, business_id)
#             else:
#                 msg = "Disculpa, no pude analizar tu imagen. ¿Podrías describir qué necesitas? 📝"
#                 enviar_texto_whatsapp(user_id, msg, business_id)
                
#         except Exception as api_error:
#             logger.error(f"❌ [IMAGE] Error llamando API Evolution: {api_error}")
#             msg = "Disculpa, tuve problemas procesando tu imagen. ¿Podrías describir qué necesitas? 📝"
#             enviar_texto_whatsapp(user_id, msg, business_id)

#     except Exception as e:
#         logger.error(f"🔴 Error procesando imagen background: {e}")
#         import traceback
#         logger.error(traceback.format_exc())
#         try:
#             msg = "Disculpa, tuve un error procesando tu imagen. ¿Podrías escribir tu consulta? 📝"
#             enviar_texto_whatsapp(user_id, msg, business_id)
#         except:
#             pass  # Evitar errores en cascada


# def worker_procesar_audio(business_id, user_id, msg_id, mensaje, push_name, info_negocio):
#     """
#         Procesa audios enviados por Evolution API - WhatsApp SOLO Baileys:
#         1. Descarga el audio desde Evolution API
#         2. Decodifica el audio de base64 a bytes
#         3. Transcribe el audio a texto
#         4. Procesa el texto con IA
#     """
#     try:
#         logger.debug(f"[AUDIO] Procesando audio para {user_id}, instance={business_id}")
#         telefono = user_id.split("@")[0]    
#         # Usar el cliente evolutionapi para obtener el audio en base64
#         # https://doc.evolution-api.com/v2/en/endpoints/messages#get-media
#         endpoint = f"chat/getBase64FromMediaMessage/{business_id}"
#         # Evolution necesita el objeto data completo (key + message + metadata)
#         payload_media = {
#             "message": {
#                 "key": mensaje.get("key"),
#                 "message": mensaje.get("message")
#             },
#             "convertToMp4": False  # Mantener formato original (ogg opus)
#         }
        
#         logger.debug(f"[AUDIO] Solicitando descarga de media usando evolutionapi client...")
        
#         try:
#             response = client.post(endpoint, data=payload_media)
            
#             if not response or not isinstance(response, dict):
#                 logger.error(f"❌ [AUDIO] Respuesta inválida del cliente: {response}")
#                 msg = "Disculpa, tuve problemas para procesar tu audio. ¿Podrías escribirlo? 📝"
#                 enviar_texto_whatsapp(user_id, msg, business_id)
#                 return
            
#             base64_audio = response.get("base64")
            
#             if not base64_audio:
#                 logger.error(f"❌ [AUDIO] No se recibió base64 en la respuesta: {response}")
#                 msg = "Disculpa, no pude procesar tu audio. ¿Podrías escribirlo? 📝"
#                 enviar_texto_whatsapp(user_id, msg, business_id)
#                 return
            
#             # Decodificar el base64 a bytes PRIMERO
#             audio_buffer = base64.b64decode(base64_audio)
#             logger.info(f"[AUDIO] Audio descargado: {len(audio_buffer)} bytes")

#             # 1. Transcribir (Lento)
#             texto_transcrito = transcribir_audio(audio_buffer, thread_id=f"{business_id}:{user_id}")
            
#             if texto_transcrito:
#                 # logger.info(f"🗣️ Audio transcrito: {texto_transcrito[:50].replace('\n', ' ')}")
#                 msg = f"[RCV <- EVO] 🔊 ID: {telefono} - MSG: {texto_transcrito[:100].replace('\n', ' ')}"
#                 generar_resumen_auditoria(business_id, msg)
#                 # 2. Reutilizamos el worker de texto existente para procesar con IA
#                 procesar_texto_evoapi(business_id, user_id, texto_transcrito, push_name, info_negocio)
#             else:
#                 msg = "Disculpa, no pude escuchar bien el audio. ¿Podrías escribirlo? 📝"
#                 enviar_texto_whatsapp(user_id, msg, business_id)
                
#         except Exception as api_error:
#             logger.error(f"❌ [AUDIO] Error llamando API Evolution: {api_error}")
#             msg = "Disculpa, tuve problemas descargando tu audio. ¿Podrías escribirlo? 📝"
#             enviar_texto_whatsapp(user_id, msg, business_id)

#     except Exception as e:
#         logger.error(f"🔴 Error procesando audio background: {e}")
#         import traceback
#         logger.error(traceback.format_exc())
#         try:
#             msg = "Disculpa, tuve un error procesando tu audio. ¿Podrías escribirlo? 📝"
#             enviar_texto_whatsapp(user_id, msg, business_id)
#         except:
#             pass  # Evitar errores en cascada


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
    """
        Envía un mensaje con botones interactivos a través del cliente de Evolution API.
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