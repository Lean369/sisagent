from flask import Blueprint, request, jsonify
#from ..db import get_pool
from loguru import logger
from ..logger_config import generar_resumen_auditoria
from concurrent.futures import ThreadPoolExecutor
import os
import base64
import io
import json
import requests
from ..services.cliente_config import ClienteConfig
from ..utils.ddos_protection import ddos_protection
from ..services.agent import transcribir_audio
from ..services.router import route_text_message, route_image_message, route_audio_message


chatwoot_bp = Blueprint('chatwoot', __name__)

# Pool de threads para manejar múltiples mensajes en paralelo
# CPU de 4 núcleos (max_workers=10)
# CPU de 8+ núcleos (max_workers=20)
executor = ThreadPoolExecutor(max_workers=10)  # CPU de 2 núcleos - 10 mensajes simultáneos

logger.info("🚀 Starting Chatwoot Blueprint...")

DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"

@chatwoot_bp.route('/webhook/chatwoot', methods=['POST'])
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
            client_id = f"ig_{data.get('sender', {}).get('additional_attributes', {}).get('social_instagram_user_name')}"
            user_id = f"{client_id}@{account_id}@{conversation_id}" if client_id else f"conv_{conversation_id}"
            msg = f"[RCV <- CWT] 📨 ID: {client_id} - MSG: {tipo_contenido[:100]}..."
        
        elif channel == "Channel::Whatsapp" or channel == "Channel::Api":
            client_id = f"api_{str(data.get('sender', {}).get('phone_number'))}"
            user_id = f"{client_id.replace('+', '')}@{account_id}@{conversation_id}" if client_id else f"conv_{conversation_id}"
            msg = f"[RCV <- CWT] 📨 ID: {client_id} - MSG: {tipo_contenido[:100]}..."
        
        elif channel == "Channel::WebWidget":
            client_id = f"web_{data.get('sender', {}).get('email') or 'unknown'}"
            user_id = f"{client_id}@{account_id}@{conversation_id}"
            msg = f"[RCV <- CWT] 📨 ID: {client_id} - MSG: {tipo_contenido[:100]}..."
        
        generar_resumen_auditoria(business_id, msg)

        # 🛡️ DDoS check DESPUÉS de resolver user_id correctamente
        if user_id and DDOS_PROTECTION_ENABLED and ddos_protection:
            if mensaje:
                puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id, mensaje)
            else:
                puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id)
            if not puede_procesar:
                logger.warning(f"⛔ DDoS Protection: bloqueando mensaje de {user_id}: {mensaje_error}")
                return jsonify({"status": "blocked", "reason": "rate_limit", "message": mensaje_error}), 429

        # 5. Obtener configuraciones específicas del negocio (como TTL, mensaje HITL, etc.)
        info_negocio = ClienteConfig(business_id)

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
                    client_name, client_id, info_negocio.ttl_minutos
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
                info_negocio
            )
        else:
            logger.warning(f"⚠️ [CWT] Mensaje sin contenido reconocido para conv={conversation_id}, ignorando.")

        return jsonify({"status": "recibido"}), 200

    except Exception as e:
        logger.error(f"🔴 Error en webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def worker_procesar_audio_chatwoot(business_id, user_id, audio_url, conversation_id, account_id, client_name, client_id, info_negocio):
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
                conversation_id, account_id, client_name, client_id, info_negocio
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


def procesar_y_responder_chatwoot(business_id, user_id, mensaje, conversation_id, account_id, client_name: str = "", client_id: str = "", info_negocio=None):
    """
        Función que corre en background para procesar mensajes de Chatwoot y responder
    """

    try:       
        logger.debug(f"Procesando mensaje para Chatwoot user_id={user_id} (Conv ID: {conversation_id})")

        # 1. Proceso Lento (IA)
        respuesta_ia = route_text_message(business_id, user_id, mensaje, client_name=client_name, info_negocio=info_negocio)
            
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 IA terminó para {user_id}. Enviando respuesta...")
            enviar_mensaje_chatwoot(account_id, conversation_id, respuesta_ia, client_id, business_id)
        else:
            logger.warning(f"⚠️ Agente IA no generó respuesta para {user_id}")

    except Exception as e:
        logger.error(f"🔴 Error en procesar_y_responder_chatwoot para {user_id}: {e}")


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
