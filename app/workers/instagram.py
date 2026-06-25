from dotenv import load_dotenv
from loguru import logger
import queue
import random
import uuid


# ==================== WEBHOOK DE INSTAGRAM COMMENTS y DMs ====================
# @app.route('/webhook/instagram', methods=['GET', 'POST'])
# def webhook_instagram():
#     """
#     Endpoint para recibir webhooks de Instagram (comentarios en publicaciones, DMs y Verificación de webhook por parte de Meta)
    
#     GET: Verificación de webhook por parte de Meta
#     POST: Recepción de comentarios de Instagram
#     """
#     logger.info(f"📨 Received Instagram webhook: method={request.method}, args={request.args}, payload={json.dumps(request.get_json(silent=True) or {})}")
#     if request.method == 'GET':
#         # Verificación de webhook de Meta
#         verify_token = os.getenv('INSTAGRAM_VERIFY_TOKEN', 'instagram_webhook_verify_2026')
#         mode = request.args.get('hub.mode')
#         token = request.args.get('hub.verify_token')
#         challenge = request.args.get('hub.challenge')
        
#         if mode == 'subscribe' and token == verify_token:
#             logger.info(f"✅ Instagram webhook verificado correctamente")
#             return challenge, 200
#         else:
#             logger.warning(f"⚠️ Verificación fallida: mode={mode}, token={token}")
#             return 'Forbidden', 403
    
#     elif request.method == 'POST':
#         try:
#             payload = request.get_json(silent=True) or {}
#             logger.info(f"📸 Instagram webhook recibido: {json.dumps(payload)[:300]}...")
            
#             # Procesar cada entrada del webhook
#             for entry in payload.get('entry', []):
#                 recipient_id = entry.get('id')  # Instagram Page ID (en DM)
#                 # Los comentarios vienen en el campo 'changes'
#                 for change in entry.get('changes', []):
#                     if change.get('field') == 'comments':
#                         value = change.get('value', {})
                        
#                         # Extraer datos del comentario
#                         comment_id = value.get('id')
#                         comment_text = value.get('text', '')
#                         media_id = value.get('media', {}).get('id')
#                         media_type = value.get('media', {}).get('media_product_type', 'UNKNOWN')
                        
#                         from_user = value.get('from', {})
#                         user_id = from_user.get('id')
#                         username = from_user.get('username', 'usuario')
                        
#                         page_id = entry.get('id')  # Instagram Page ID

#                         # Ignorar comentarios/respuestas del propio bot para evitar loops
#                         if user_id == page_id:
#                             logger.debug(f"🔁 Ignorando comentario propio del bot (user_id={user_id})")
#                             continue

#                         # Ignorar si es una reply (tiene parent_id) para evitar responder a respuestas
#                         if value.get('parent_id'):
#                             logger.debug(f"↩️ Ignorando reply de @{username} (parent_id={value.get('parent_id')})")
#                             continue
                        
#                         logger.info(f"💬 Comentario IG de @{username}({user_id}): {comment_text[:100]}")
#                         logger.info(f"   Media: {media_type} (ID: {media_id})")

#                         # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
#                         if user_id and DDOS_PROTECTION_ENABLED and ddos_protection:
#                             puede_procesar, msg_error = ddos_protection.puede_procesar(user_id, comment_text)

#                             if not puede_procesar:
#                                 logger.warning(f"Escudo activado para {user_id}")
#                                 # Ignoramos el mensaje, devolvemos 200 a Meta y no gastamos IA
#                                 return jsonify({"status": "blocked_by_shield"}), 200
                        
#                         logger.debug(f"🛡️ Escudo permitió el mensaje de {user_id}")

#                         # Empaquetamos todo en una tupla y lo lanzamos a la cola
#                         cola_comentarios.put((
#                             page_id, user_id, username, comment_id, comment_text, media_id, media_type
#                         ))

#                 # B)- Mensajes directos (DMs) vienen en el campo 'messaging'
#                 for msg_event in entry.get('messaging', []):
#                     # Ignorar ediciones de mensaje
#                     if 'message_edit' in msg_event:
#                         logger.debug("✏️ Ignorando message_edit de IG DM")
#                         continue

#                     message = msg_event.get('message', {})
#                     if not message:
#                         continue

#                     sender_id = msg_event.get('sender', {}).get('id')

#                     page_id = entry.get('id')

#                     # Ignorar echos (mensajes enviados por el propio bot)
#                     if message.get('is_echo'):
#                         logger.debug(f"🔁 Ignorando echo de DM propio del bot")
#                         continue

#                     dm_text = message.get('text', '')

#                     mid = message.get('mid', '')

#                     # if not dm_text:
#                     #     logger.debug(f"ℹ️ DM sin texto (mid={mid}), ignorando")
#                     #     continue

#                     logger.info(f"📩 DM IG de {sender_id}: {dm_text[:100]}")
#                     # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
#                     if sender_id and DDOS_PROTECTION_ENABLED and ddos_protection:
#                         puede_procesar, msg_error = ddos_protection.puede_procesar(sender_id, dm_text)

#                         if not puede_procesar:
#                             logger.warning(f"Escudo activado para {sender_id}")
#                             return jsonify({"status": "blocked_by_shield"}), 200
                 
#                     logger.debug(f"🛡️ Escudo permitió el DM de {sender_id}")
#                     executor.submit(enviar_mensaje_dm_chatwoot, page_id, sender_id, dm_text, payload)
            
#             return jsonify({"status": "received"}), 200
            
#         except Exception as e:
#             logger.error(f"🔴 Error procesando webhook Instagram: {e}")
#             return jsonify({"status": "error", "message": str(e)}), 500


# 1. Crear la Cola Global en memoria
cola_comentarios = queue.Queue()

# 2. Definir el "Obrero" (Worker) que vivirá en segundo plano
def worker_secuencial_instagram():
    logger.info("👷 Worker de Instagram iniciado y esperando tareas...")
    while True:
        # El hilo se pausa aquí sin consumir CPU hasta que entre un mensaje
        tarea = cola_comentarios.get() 
        
        if tarea is None:
            break # Señal de apagado
            
        try:
            # Desempaquetamos los datos
            page_id, user_id, username, comment_id, comment_text, media_id, media_type = tarea
            
            # PACING & JITTER: Retraso aleatorio (ej: 4 a 12 segundos)
            # ¿Cuántos mensajes quedan esperando en la fila?
            # Como acabamos de hacer un .get(), si qsize() es 0, significa que este era el ÚNICO mensaje pendiente.
            mensajes_en_espera = cola_comentarios.qsize()
            
            if mensajes_en_espera == 0:
                # Tráfico normal: Respondemos casi al instante.
                # Nota de seguridad Meta: No uses 0.0. Un humano tarda al menos
                # 1.5 a 2 segundos en leer y presionar "Enviar". 
                retraso = random.uniform(1.5, 2.5) 
                logger.info(f"⚡ Fila vacía. Respondiendo rápido a @{username} (Pausa: {retraso:.1f}s)")
            else:
                # Tráfico viral: Modo Anti-Baneo activado.
                retraso = random.uniform(5.0, 14.0)
                logger.info(f"🚦 Fila: {mensajes_en_espera} pendientes. Aplicando JITTER de {retraso:.1f}s a @{username}")
            
            time.sleep(retraso)
            
            # Contesta el comentario y envia un mensaje a Chatwoot para que envíe un DM si es necesario
            procesar_y_responder_ig_keyword_comment(
                page_id, user_id, username, comment_id, comment_text, media_id, media_type
            )
            
        except Exception as e:
            logger.error(f"🔴 Error en Worker procesando a @{username}: {e}")
        finally:
            # Le avisamos a la cola que terminamos con este ítem
            cola_comentarios.task_done()


def procesar_y_responder_ig_keyword_comment(page_id, user_id, username, comment_id, comment_text, media_id, media_type):
    """Procesa un comentario de Instagram y responde usando el agente IA"""
    try:
        logger.info(f"Procesando comentario keyword IG de @{username}: {comment_text[:80]}")
        
        # Mapear el page_id numérico de IG al business_id configurado en el sistema.
        # Si no hay mapeo explícito, fallback al valor fijo INSTAGRAM_BUSINESS_ID del .env.
        ig_page_map_raw = os.getenv("INSTAGRAM_PAGE_MAP", "cliente1")  # formato: "page_id1:biz1,page_id2:biz2"
        ig_page_map = dict(pair.split(":") for pair in ig_page_map_raw.split(",") if ":" in pair)
        business_id = ig_page_map.get(str(page_id)) or os.getenv("INSTAGRAM_BUSINESS_ID", page_id)
        
        logger.debug(f"[IG] page_id={page_id} → business_id={business_id}")
        
        info_negocio = ClienteConfig(business_id)
        ttl_minutos = info_negocio.ttl_sesion_minutos or 60
        
        # user_id único: prefijado con ig_ para no colisionar con threads de WhatsApp
        ig_user_id = f"ig_{user_id}"
        logger.debug(f"Generando user_id para IG: {ig_user_id}")
        
        respuesta = "Gracias"  # Respuesta genérica por defecto
        keyword = "info"

        # Normalizar el texto del comentario antes de comparar (quita espacios y case-insensitive)
        comentario_norm = (comment_text or "").strip().lower()
        # Verifica si el comentario contiene la keyword (subcadena), no solo igualdad
        if keyword in comentario_norm:
            logger.info(f"🔍 Comentario coincide con keyword '{keyword}', enviando respuesta automática.")
            # 🚀 2. VERIFICAMOS EL TRACKER
            if tracker_dms.ya_recibio_dm(user_id):
                # CASO A: Ya recibió un DM hoy. Solo respondemos el comentario, sin enviar DM.
                logger.info(f"⚠️ @{username} ya recibió un DM hoy. Respondiendo solo el comentario sin enviar otro DM.")
                respuesta = f"Hola @{username}, ya te envié un mensaje privado con la información. ¡Échale un vistazo! 📬"
            else:
                # CASO B: Es la primera vez que pregunta hoy.
                # Respondemos el comentario Y mandamos el DM.
                respuesta = "Te vamos a mandar un mensaje privado con la información que solicitaste. Por favor revisa tu bandeja de entrada. 📩"
                message_text = "Quiero información adicional" # El texto del DM que se enviará a Chatwoot para que el bot responda desde ahí         
                enviar_mensaje_dm_chatwoot(page_id, user_id, message_text)
                # 🚀 3. REGISTRAMOS EL ENVÍO PARA BLOQUEAR FUTUROS DMs
                tracker_dms.registrar_envio(user_id)
                logger.info(f"✅ DM enviado y registrado para @{username}.")
        
        if respuesta:
            ok = responder_comentario_instagram(comment_id, respuesta)
            if ok:
                logger.info(f"✅ Respuesta enviada a @{username} en IG")
                msg = f"[SND -> IG] 📤 ID: @{username} - MSG: {respuesta[:100]}..."
                generar_resumen_auditoria(business_id, msg)
            else:
                logger.error(f"❌ Fallo al publicar respuesta en IG para @{username}. Verifica INSTAGRAM_ACCESS_TOKEN.")
        else:
            logger.info(f"⚠️ No se detectó keyword en el comentario de @{username}")
        
        # contexto_adicional = f"\n[Usuario: @{username} comentó en tu {media_type}]"
        # mensaje_completo = comment_text + contexto_adicional
        
        # # Procesar con el agente IA usando adaptar_procesar_mensaje (maneja el config correctamente)
        # respuesta = adaptar_procesar_mensaje(
        #     business_id, ig_user_id, mensaje_completo,
        #     client_name=username, ttl_minutos=ttl_minutos
        # )
            
    except Exception as e:
        logger.error(f"🔴 Error procesando comentario Instagram de @{username}: {e}")
        import traceback
        logger.error(traceback.format_exc())


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
def procesar_y_responder_ig_dm(page_id, sender_id, texto, mid):
    """Procesa un mensaje directo de Instagram y responde usando el agente IA"""
    try:
        logger.info(f"📩 Procesando DM IG de {sender_id}: {texto[:80]}")

        ig_page_map_raw = os.getenv("INSTAGRAM_PAGE_MAP", "")
        ig_page_map = dict(pair.split(":") for pair in ig_page_map_raw.split(",") if ":" in pair)
        business_id = ig_page_map.get(str(page_id)) or os.getenv("INSTAGRAM_BUSINESS_ID", page_id)

        logger.debug(f"[IG DM] page_id={page_id} → business_id={business_id}")

        info_negocio = ClienteConfig(business_id)
        ttl_minutos = info_negocio.ttl_sesion_minutos or 60

        # Prefijo igdm_ para separar el hilo de DMs del de comentarios
        ig_user_id = f"igdm_{sender_id}"

        respuesta = adaptar_procesar_mensaje(
            business_id, ig_user_id, texto,
            client_name=sender_id, ttl_minutos=ttl_minutos
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
            logger.warning(f"⚠️ No se obtuvo respuesta del agente para DM de {sender_id}")

    except Exception as e:
        logger.error(f"🔴 Error procesando DM Instagram de {sender_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())


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

