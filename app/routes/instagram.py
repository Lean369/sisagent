from flask import Blueprint, request, jsonify
#from ..db import get_pool
from loguru import logger
from ..logger_config import generar_resumen_auditoria
from concurrent.futures import ThreadPoolExecutor
import os
import base64
import io
import json
from ..services.cliente_config import ClienteConfig
from ..utils.ddos_protection import ddos_protection
from ..services.agent import transcribir_audio
from ..services.router import route_text_message, route_image_message, route_audio_message


instagram_bp = Blueprint('instagram', __name__)

# Pool de threads para manejar múltiples mensajes en paralelo
# CPU de 4 núcleos (max_workers=10)
# CPU de 8+ núcleos (max_workers=20)
executor = ThreadPoolExecutor(max_workers=10)  # CPU de 2 núcleos - 10 mensajes simultáneos

logger.info("🚀 Starting Instagram Blueprint...")

DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"

@instagram_bp.route('/webhook/instagram', methods=['GET', 'POST'])
def webhook_instagram():
    """
    Endpoint para recibir webhooks de Instagram (comentarios en publicaciones, DMs y Verificación de webhook por parte de Meta)
    
    GET: Verificación de webhook por parte de Meta
    POST: Recepción de comentarios de Instagram y DMs 
    """
    logger.info(f"📨 Received Instagram webhook: method={request.method}, args={request.args}, payload={json.dumps(request.get_json(silent=True) or {})}")
    if request.method == 'GET':
        # Verificación de webhook de Meta
        verify_token = os.getenv('INSTAGRAM_VERIFY_TOKEN', 'instagram_webhook_verify_2026')
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode == 'subscribe' and token == verify_token:
            logger.info(f"✅ Instagram webhook verificado correctamente")
            return challenge, 200
        else:
            logger.warning(f"⚠️ Verificación fallida: mode={mode}, token={token}")
            return 'Forbidden', 403
    
    elif request.method == 'POST':
        try:
            payload = request.get_json(silent=True) or {}
            logger.info(f"📸 Instagram webhook recibido: {json.dumps(payload)[:300]}...")
            
            # Procesar cada entrada del webhook
            for entry in payload.get('entry', []):
                recipient_id = entry.get('id')  # Instagram Page ID (en DM)
                # Los comentarios vienen en el campo 'changes'
                for change in entry.get('changes', []):
                    if change.get('field') == 'comments':
                        value = change.get('value', {})
                        
                        # Extraer datos del comentario
                        comment_id = value.get('id')
                        comment_text = value.get('text', '')
                        media_id = value.get('media', {}).get('id')
                        media_type = value.get('media', {}).get('media_product_type', 'UNKNOWN')
                        
                        from_user = value.get('from', {})
                        user_id = from_user.get('id')
                        username = from_user.get('username', 'usuario')
                        
                        page_id = entry.get('id')  # Instagram Page ID

                        # Ignorar comentarios/respuestas del propio bot para evitar loops
                        if user_id == page_id:
                            logger.debug(f"🔁 Ignorando comentario propio del bot (user_id={user_id})")
                            continue

                        # Ignorar si es una reply (tiene parent_id) para evitar responder a respuestas
                        if value.get('parent_id'):
                            logger.debug(f"↩️ Ignorando reply de @{username} (parent_id={value.get('parent_id')})")
                            continue
                        
                        logger.info(f"💬 Comentario IG de @{username}({user_id}): {comment_text[:100]}")
                        logger.info(f"   Media: {media_type} (ID: {media_id})")

                        # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
                        if user_id and DDOS_PROTECTION_ENABLED and ddos_protection:
                            puede_procesar, msg_error = ddos_protection.puede_procesar(user_id, comment_text)

                            if not puede_procesar:
                                logger.warning(f"Escudo activado para {user_id}")
                                # Ignoramos el mensaje, devolvemos 200 a Meta y no gastamos IA
                                return jsonify({"status": "blocked_by_shield"}), 200
                        
                        logger.debug(f"🛡️ Escudo permitió el mensaje de {user_id}")

                        # Empaquetamos todo en una tupla y lo lanzamos a la cola
                        cola_comentarios.put((
                            page_id, user_id, username, comment_id, comment_text, media_id, media_type
                        ))

                # B)- Mensajes directos (DMs) vienen en el campo 'messaging'
                for msg_event in entry.get('messaging', []):
                    # Ignorar ediciones de mensaje
                    if 'message_edit' in msg_event:
                        logger.debug("✏️ Ignorando message_edit de IG DM")
                        continue

                    message = msg_event.get('message', {})
                    if not message:
                        continue

                    sender_id = msg_event.get('sender', {}).get('id')

                    page_id = entry.get('id')

                    # Ignorar echos (mensajes enviados por el propio bot)
                    if message.get('is_echo'):
                        logger.debug(f"🔁 Ignorando echo de DM propio del bot")
                        continue

                    dm_text = message.get('text', '')

                    mid = message.get('mid', '')

                    # if not dm_text:
                    #     logger.debug(f"ℹ️ DM sin texto (mid={mid}), ignorando")
                    #     continue

                    logger.info(f"📩 DM IG de {sender_id}: {dm_text[:100]}")
                    # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
                    if sender_id and DDOS_PROTECTION_ENABLED and ddos_protection:
                        puede_procesar, msg_error = ddos_protection.puede_procesar(sender_id, dm_text)

                        if not puede_procesar:
                            logger.warning(f"Escudo activado para {sender_id}")
                            return jsonify({"status": "blocked_by_shield"}), 200
                 
                    logger.debug(f"🛡️ Escudo permitió el DM de {sender_id}")
                    executor.submit(enviar_mensaje_dm_chatwoot, page_id, sender_id, dm_text, payload)
            
            return jsonify({"status": "received"}), 200
            
        except Exception as e:
            logger.error(f"🔴 Error procesando webhook Instagram: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500


def enviar_mensaje_dm_chatwoot(page_id, user_id, message_text, payload=None):
    """Envía un mensaje directo a Chatwoot para que el bot responda desde ahí (en lugar de responder directamente en IG)"""

    if payload is None:
        payload = generar_payload_ig_dm(page_id, user_id, message_text, mid=None)
    
    logger.debug(f"Payload simulado para DM → {json.dumps(payload)}")
    # Reenviar el DM al webhook de Chatwoot para crear/actualizar conversación
    try:
        chatwoot_ig_webhook = os.getenv("CHATWOOT_IG_WEBHOOK_URL", "https://sischat.sisnova.com.ar/webhooks/instagram")
        resp_cwt = requests.post(chatwoot_ig_webhook, json=payload, timeout=5)
        logger.debug(f"📤 DM reenviado a Chatwoot IG webhook → {resp_cwt.status_code}")
    except Exception as fwd_err:
        logger.error(f"🔴 Error reenviando DM a Chatwoot: {fwd_err}")


def responder_comentario_instagram(comment_id: str, mensaje: str):
    """Responde a un comentario de Instagram usando la Graph API de Meta
    
    Args:
        comment_id: ID del comentario a responder
        mensaje: Texto de la respuesta
    """
    try:
        access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        if not access_token:
            logger.error("❌ INSTAGRAM_ACCESS_TOKEN no configurado")
            return False
        
        # URL de la Graph API para responder comentarios
        url = f"https://graph.facebook.com/v23.0/{comment_id}/replies"
        
        # Limitar respuesta a 500 caracteres (límite de Instagram)
        mensaje_truncado = mensaje[:500]
        
        payload = {
            "message": mensaje_truncado,
            "access_token": access_token
        }
        
        response = requests.post(url, params=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            logger.info(f"📨 Respuesta IG enviada: {result}")
            return True
        else:
            # Analizamos el error de Meta
            error_data = response.json().get("error", {})
            error_code = error_data.get("code")
            error_msg = error_data.get("message", "").lower()
            logger.error(f"❌ Error al responder en IG: {response.status_code} - {response.text}")
            logger.error(f"❌ Error code {error_code} al responder en IG: {error_msg}")  
            # Código 10 o menciones de privacidad suelen ser cuentas cerradas
            if error_code == 10 or "privacy" in error_msg or "not allow" in error_msg:
                logger.warning(f"🔒 Cuenta privada detectada para {recipient_id}")
            return False
            
    except Exception as e:
        logger.error(f"🔴 Error en responder_comentario_instagram: {e}")
        return False


def generar_payload_ig_dm(page_id, user_id, message_text, mid):
    """Genera un Message ID (mid) falso con el mismo formato que usa Meta"""
    
    if mid is None:
        # 1. Creamos datos únicos (timestamp actual + un ID aleatorio)
        timestamp = int(time.time() * 1000)
        id_aleatorio = uuid.uuid4().hex
        
        # 2. Simulamos la estructura interna que Meta usa antes de codificar
        estructura_interna = f"m_id:test_saas:{timestamp}:{id_aleatorio}"
            
        # 3. Lo codificamos en Base64 para que se vea como el chorizo de letras real
        mid_base64 = base64.b64encode(estructura_interna.encode('utf-8')).decode('utf-8')

        mid = f"bWdf{mid_base64}"

    payload = {
        "object": "instagram",
        "entry": [
            {
            "time": int(time.time() * 1000),
            "id": page_id,
            "messaging": [
                    {
                        "sender": { "id": user_id },
                        "recipient": { "id": page_id },
                        "timestamp": int(time.time() * 1000),
                        "message": {
                            "mid": mid,
                            "text": message_text
                        }
                    }
                ]
            }
        ]
    }

    return payload



# No Funciona. Se deben enviar los DMs a Chatwoot para que el bot responda desde ahí
def enviar_dm_instagram(ig_page_id: str, recipient_id: str, mensaje: str):
    """Envía un mensaje directo de Instagram usando la Graph API de Meta (No Funciona)"""
    try:
        access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
        if not access_token:
            logger.error("❌ INSTAGRAM_ACCESS_TOKEN no configurado")
            return False

        url = f"https://graph.facebook.com/v25.0/{ig_page_id}/messages"

        # Límite de 1000 caracteres para IG DM
        mensaje_truncado = mensaje[:1000]

        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": mensaje_truncado},
            "messaging_type": "RESPONSE"         
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=payload, timeout=10)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"📨 DM IG enviado: {result.get('message_id', result)}")
            return True
        else:
            logger.error(f"❌ Error al enviar DM en IG: {response.status_code} - {response.text}")
            return False

    except requests.exceptions.Timeout:
        logger.error(f"🔴 Timeout al enviar DM IG a {recipient_id}")
        return False
    except Exception as e:
        logger.error(f"🔴 Error en enviar_dm_instagram: {e}")
        return False



# No Funciona. Se deben enviar los DMs a Chatwoot para que el bot responda desde ahí
def procesar_y_responder_ig_dm(page_id, sender_id, texto, mid):
    """Procesa un mensaje directo de Instagram y responde usando el agente IA"""
    try:
        logger.info(f"📩 Procesando DM IG de {sender_id}: {texto[:80]}")

        ig_page_map_raw = os.getenv("INSTAGRAM_PAGE_MAP", "")
        ig_page_map = dict(pair.split(":") for pair in ig_page_map_raw.split(",") if ":" in pair)
        business_id = ig_page_map.get(str(page_id)) or os.getenv("INSTAGRAM_BUSINESS_ID", page_id)

        logger.debug(f"[IG DM] page_id={page_id} → business_id={business_id}")

        info_negocio = ClienteConfig(business_id)

        # Prefijo igdm_ para separar el hilo de DMs del de comentarios
        ig_user_id = f"igdm_{sender_id}"

        respuesta = route_text_message(
            business_id, ig_user_id, texto,
            client_name=sender_id, info_negocio=info_negocio
        )

        if respuesta:
            ok = enviar_dm_instagram(page_id, sender_id, respuesta)
            if ok:
                logger.info(f"✅ DM enviado a {sender_id} en IG")
                msg = f"[SND -> IG DM] 📤 ID: {sender_id} - MSG: {respuesta[:100]}..."
                generar_resumen_auditoria(business_id, msg)
            else:
                logger.error(f"❌ Fallo al enviar DM IG a {sender_id}. Verifica INSTAGRAM_ACCESS_TOKEN.")
        else:
            logger.warning(f"⚠️ No se obtuvo respuesta del agente IA para DM de {sender_id}")

    except Exception as e:
        logger.error(f"🔴 Error procesando DM Instagram de {sender_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())