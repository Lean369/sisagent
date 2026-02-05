from flask import Flask, request, jsonify
from agente import procesar_mensaje
from loguru import logger
import sys
from agente import pool, workflow_builder # Importamos el builder, NO la app completa
from langgraph.checkpoint.postgres import PostgresSaver
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
import httpx
import requests
import json
import os


app = Flask(__name__)

# Pool de threads para manejar múltiples mensajes en paralelo
# CPU de 4 núcleos (max_workers=10)
# CPU de 8+ núcleos (max_workers=20)
executor = ThreadPoolExecutor(max_workers=10)  # CPU de 2 núcleos - 10 mensajes simultáneos

logger.info("🔄 Iniciando app Flask...")


def enviar_mensaje_whatsapp(numero: str, mensaje, instance_id: str = None, instance_name: str = None):
    """Envía un mensaje a través de Evolution API.
    
    Soporta:
    - Mensajes de texto (str)
    - Mensajes con botones (dict con type='button')

    Intentará varios identificadores en orden: `instance_id` (UUID), `instance_name` (friendly name),
    y finalmente la configuración `EVOLUTION_INSTANCE_ID`/`EVOLUTION_INSTANCE` desde el entorno.
    Devuelve el JSON de respuesta en caso de éxito o el dict con status/text en error.
    """
    headers = {
        "Content-Type": "application/json",
        "apikey": os.environ.get("EVOLUTION_API_KEY")
    }
    #logger.debug(f"[SND -> EVO] numero: {numero}, mensaje: {str(mensaje)[:50]}, instance_id: {instance_id}, instance_name: {instance_name}")
    # Detectar si el mensaje incluye botones
    is_button_message = isinstance(mensaje, dict) and mensaje.get('type') == 'button'
    
    if not str(mensaje).strip():
        logger.error("❌ Mensaje vacío. Usando fallback.")
        mensaje = "El servicio no está disponible en este momento. Por favor, inténtalo más tarde."

    if is_button_message:
        # Evolution API usa formato especial para botones con URLs
        # Usamos sendText con el texto y agregamos el link al final
        texto_mensaje = mensaje['content']['text']
        boton = mensaje['content']['buttons'][0]  # Tomar el primer botón
        url_boton = boton['url']
        display_text = boton['displayText']
        footer = mensaje['content'].get('footer', '')
        
        # Construir mensaje con formato especial para WhatsApp
        mensaje_completo = f"{texto_mensaje}\n\n{display_text}\n{url_boton}"
        if footer:
            mensaje_completo += f"\n\n_{footer}_"
        
        payload = {
            "number": numero,
            "text": mensaje_completo
        }
    else:
        # Payload para mensajes de texto simple
        payload = {
            "number": numero,
            "text": str(mensaje)
        }

    # Construir lista de candidatos para probar
    candidates = []
    if instance_id: candidates.append(str(instance_id))
    if instance_name: candidates.append(str(instance_name))

    # Añadir configuración desde entorno como último recurso
    if os.environ.get("EVOLUTION_INSTANCE_ID"):
        candidates.append(str(os.environ.get("EVOLUTION_INSTANCE_ID")))

    if os.environ.get("EVOLUTION_INSTANCE") and os.environ.get("EVOLUTION_INSTANCE") not in candidates:
        candidates.append(str(os.environ.get("EVOLUTION_INSTANCE")))

    # Deduplicate preserving order
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]
    logger.debug(f"Trying to send message to {numero} using candidates: {candidates}")
    for candidate in candidates:
        # Usar siempre sendText (Evolution API no tiene endpoint sendButtons separado)
        EVOLUTION_API_URL = os.environ.get("EVOLUTION_API_URL", "https://evoapi.sisnova.com.ar")
        
        url = f"{EVOLUTION_API_URL}/message/sendText/{candidate}"
        endpoint_type = "sendText (with button link)" if is_button_message else "sendText"
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30.0, verify=False)
            status = response.status_code
            # Log full body for non-2xx to help debugging
            text = None
            try:
                text = response.json()
            except Exception:
                text = response.text

            logger.debug(f"[SND -> EVO] Tried {endpoint_type} with candidate={candidate} status={status} response={str(text)[:200]}")

            if os.environ.get("SEND_FIND_CONTACTS", "false").lower() == "true":
                logger.debug(f"Attempting to call findContacts for candidate={candidate} and numero={numero}")
                url2 = f"{EVOLUTION_API_URL}/chat/findContacts/{candidate}"
                payload2 = {
                    "where": {
                        "id": numero
                    }
                }
                response2 = requests.post(url2, json=payload2, headers=headers, timeout=30.0, verify=False)
                logger.debug(f"[SND -> EVO] findContacts response: {response2.status_code} {response2.text}")

            if 200 <= status < 300:
                return text
            # Continue trying next candidate on 4xx/5xx
        except Exception as e:
            logger.exception(f"Exception when sending with candidate {candidate}: {e}")

    # If none succeeded, return an informative structure
    msg_type = "button message" if is_button_message else "text message"
    logger.error(f"❌ All send attempts failed for number={numero} (type={msg_type}); tried={candidates}")
    return {"status": "failed", "tried": candidates, "message_type": msg_type}


def transcribir_audio(audio_url: str, audio_base64: str = None) -> Optional[str]:
    """
    Transcribe un mensaje de audio a texto
    
    Args:
        audio_url: URL del archivo de audio (puede estar encriptado de WhatsApp)
        audio_base64: Audio en base64 (alternativa a URL)
    
    Returns:
        Texto transcrito o None si hay error
    """
    try:
        if not TRANSCRIPTION_ENABLED:
            logger.warning("⚠️ [AUDIO] Transcripción deshabilitada")
            return None
        
        logger.info(f"[AUDIO] Iniciando transcripción de audio")
        
        import tempfile
        import base64
        
        # Descargar o decodificar el audio
        audio_data = None
        
        if audio_base64:
            logger.debug("[AUDIO] Decodificando audio desde base64")
            audio_data = base64.b64decode(audio_base64)
        elif audio_url:
            logger.debug(f"[AUDIO] Descargando audio desde URL: {audio_url[:50]}...")
            response = requests.get(audio_url, timeout=30.0, verify=False)
            if response.status_code == 200:
                audio_data = response.content
            else:
                logger.error(f"❌ [AUDIO] Error descargando audio: status={response.status_code}")
                return None
        
        if not audio_data:
            logger.error("❌ [AUDIO] No se pudo obtener datos de audio")
            return None
        
        # Guardar temporalmente el audio
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as temp_audio:
            temp_audio.write(audio_data)
            temp_audio_path = temp_audio.name
        
        logger.debug(f"[AUDIO] Audio guardado temporalmente en {temp_audio_path}")
        
        # Convertir OGG a MP3 usando ffmpeg (formato compatible con OpenAI)
        import subprocess
        mp3_path = temp_audio_path.replace('.ogg', '.mp3')
        
        try:
            logger.debug("[AUDIO] Convirtiendo OGG a MP3...")
            subprocess.run(
                ['ffmpeg', '-i', temp_audio_path, '-acodec', 'libmp3lame', '-ar', '16000', mp3_path, '-y'],
                check=True,
                capture_output=True
            )
            logger.debug(f"[AUDIO] Audio convertido a {mp3_path}")
            audio_path_to_use = mp3_path
        except Exception as conv_error:
            logger.warning(f"⚠️ [AUDIO] Error convirtiendo audio: {conv_error}, usando archivo original")
            audio_path_to_use = temp_audio_path
        
        # Transcribir según el proveedor
        transcription = None
        
        if TRANSCRIPTION_PROVIDER == "openai":
            logger.debug("[AUDIO] Usando OpenAI Whisper API")
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            
            with open(audio_path_to_use, 'rb') as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="es"  # Español
                )
                transcription = transcript.text
        
        elif TRANSCRIPTION_PROVIDER == "whisper-local":
            logger.debug("[AUDIO] Usando Whisper local")
            import whisper
            model = whisper.load_model("base")
            result = model.transcribe(audio_path_to_use, language="es")
            transcription = result["text"]
        
        # Limpiar archivos temporales
        import os
        try:
            os.unlink(temp_audio_path)
            if audio_path_to_use != temp_audio_path and os.path.exists(audio_path_to_use):
                os.unlink(audio_path_to_use)
        except Exception as e:
            logger.exception(f"⚠️ [AUDIO] Error limpiando archivos temporales: {e}")
        
        if transcription:
            logger.info(f"[AUDIO] Transcripción exitosa: {transcription[:100]}...")
            return transcription
        else:
            logger.error("❌ [AUDIO] No se obtuvo transcripción")
            return None
            
    except Exception as e:
        logger.exception(f"🔴 [AUDIO] Error transcribiendo audio: {e}")
        return None


def extraer_datos_respuesta(respuesta):
    """
    Extrae datos de cualquier tipo de respuesta (Flask, Requests, Dict, String).
    """
    try:
        logger.debug(f"🔍 Extrayendo datos de respuesta tipo: {type(respuesta)}")

        # TIPO 1: Diccionario directo
        if isinstance(respuesta, dict):
            return respuesta

        # TIPO 2: Objeto Response de Flask (El que te dio error)
        if hasattr(respuesta, 'get_data'):
            try:
                # Leemos el texto crudo del cuerpo de la respuesta
                texto_json = respuesta.get_data(as_text=True)
                if texto_json:
                    return json.loads(texto_json)
            except Exception as e:
                logger.exception(f"⚠️ Error leyendo data de Flask Response: {e}")

        # TIPO 3: Objeto Response de Requests (HTTP externo)
        if hasattr(respuesta, 'json'):
            try:
                if callable(respuesta.json):
                    return respuesta.json()
                else:
                    return respuesta.json
            except:
                pass

        # TIPO 4: Fallback genérico (Intentar leer atributo .text o .data)
        texto_crudo = None
        if hasattr(respuesta, 'text'): # Requests
            texto_crudo = respuesta.text
        elif hasattr(respuesta, 'data'): # Werkzeug bytes
            texto_crudo = respuesta.data.decode('utf-8')
            
        if texto_crudo:
            return json.loads(texto_crudo)

    except Exception as e:
        logger.exception(f"🔴 Error crítico extrayendo JSON: {e}")
        return None

    return None
        

@app.route('/webhook', methods=['POST'])
def webhook():
    """Endpoint para recibir webhooks de Evolution API - CON CONCURRENCIA"""

    try:
        payload = request.json
        logger.debug("[RCV <- EVO] Received webhook payload: {}", json.dumps(payload)[:500])
        
        # Extraer información del mensaje de Evolution API
        if payload.get('event') == 'messages.upsert':
            mensaje_data = payload.get('data', {})
            
            # Intentar extraer mensaje de texto
            mensaje = mensaje_data.get('message', {}).get('conversation') or \
                     mensaje_data.get('message', {}).get('extendedTextMessage', {}).get('text', '')
            
            # Verificar si es un mensaje de audio
            audio_message = mensaje_data.get('message', {}).get('audioMessage')
            
            # Verificar si es una imagen, video, documento u otro archivo
            image_message = mensaje_data.get('message', {}).get('imageMessage')
            video_message = mensaje_data.get('message', {}).get('videoMessage')
            document_message = mensaje_data.get('message', {}).get('documentMessage')
            sticker_message = mensaje_data.get('message', {}).get('stickerMessage')
            
            user_id = mensaje_data.get('key', {}).get('remoteJid', '')
            from_me = mensaje_data.get('key', {}).get('fromMe', False)
            push_name = mensaje_data.get('pushName', '') or mensaje_data.get('verifiedBizName', '')

            # Intentar obtener instance/id proporcionado en el webhook
            business_id = payload.get('instance') or mensaje_data.get('instanceId') or None
            logger.info(f"🔔 {business_id}")

            # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
            # if user_id and not from_me and DDOS_PROTECTION_ENABLED and ddos_protection:
            #     puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id)
            #     if not puede_procesar:
            #         logger.warning(f"⚠️ DDoS Protection: bloqueando mensaje de {user_id}: {mensaje_error}")
            #         # NO enviar mensaje automático para prevenir loops
            #         return jsonify({"status": "blocked", "reason": "rate_limit", "message": mensaje_error}), 429
            
            #[TEXTO] Procesar mensaje de texto normal
            if mensaje and user_id and not from_me:
                mensaje_usuario = adaptar_procesar_mensaje(business_id, user_id, mensaje, client_name=push_name) 
                
                logger.info(f"Generated response for {user_id}: {str(mensaje_usuario)[:50]}")

                executor.submit(enviar_mensaje_whatsapp, user_id, mensaje_usuario, business_id, payload.get('instance'))    
            else:
                logger.debug("No es mensaje de texto o es de 'from_me', saltando procesamiento de texto.")

            # [MULTIMEDIA] Si es una imagen, video, documento o sticker, pedir que escriba texto
            if (image_message or video_message or document_message or sticker_message) and not from_me and user_id:
                tipo_archivo = "imagen" if image_message else \
                               "video" if video_message else \
                               "documento" if document_message else \
                               "sticker"
                
                logger.info(f"Received {tipo_archivo.upper()} from {user_id} ({push_name}), requesting text message")
                # Enviar en background usando ThreadPool
                executor.submit(
                    enviar_mensaje_whatsapp,
                    user_id,
                    f"Gracias por tu {tipo_archivo}. Para poder ayudarte mejor, ¿podrías escribir tu consulta como texto? 📝",
                    business_id,
                    payload.get('instance')
                )
                return {"status": "success"}
            
            # [AUDIO] Si es un mensaje de audio, transcribirlo
            if audio_message and not from_me and user_id:
                logger.info(f"Processing AUDIO message from {user_id} ({push_name})")
                
                # Extraer URL o base64 del audio
                audio_url = audio_message.get('url', '')
                audio_base64 = audio_message.get('base64', '')
                
                # Transcribir el audio
                transcripcion = transcribir_audio(audio_url, audio_base64)
                
                if transcripcion:
                    logger.info(f"[AUDIO] Procesando transcripción como mensaje de texto")
                    mensaje = transcripcion
                else:
                    logger.warning("⚠️[AUDIO] No se pudo transcribir, enviando mensaje genérico")
                    # Enviar en background usando ThreadPool
                    executor.submit(
                        enviar_mensaje_whatsapp,
                        user_id,
                        "Disculpa, recibí tu mensaje de audio pero tuve problemas para transcribirlo. ¿Podrías escribirlo como texto?",
                        business_id,
                        payload.get('instance')
                    )
                    return {"status": "success"}
        
        # [LISTA] Soporte alternativo para formato con lista de mensajes
        for msg in payload.get("messages", []):
            if msg.get("type") == "conversation":
                user_id = msg["key"]["remoteJid"]
                text = msg["message"]["conversation"]
                from_me = msg["key"].get("fromMe", False)
                push_name = msg.get('pushName', '') or msg.get('verifiedBizName', '')
                
                if text and user_id and not from_me:
                    logger.info("Processing message type: LIST")

                respuesta = adaptar_procesar_mensaje(business_id, user_id, text, client_name=push_name)            

                executor.submit(enviar_mensaje_whatsapp, user_id, respuesta, business_id, payload.get('instance')) 
                
                logger.info(f"Generated response for {user_id}: {respuesta[:50]}")
                    
                # Solo enviar respuesta si no es None (conversación finalizada)
                if respuesta is not None:
                    # If the msg contains instance info, prefer it
                    msg_instance = msg.get('instance') or msg.get('instanceId')
                    # Procesar en background usando ThreadPool
                    # Esto NO bloquea el webhook, responde inmediatamente
                    executor.submit(enviar_mensaje_whatsapp, user_id, response, business_id, instance_name=msg.get('instance'))
                    logger.info(f"✅ Mensaje encolado de {user_id} para envío en background")
                else:
                    logger.info("[BOOKING] No se envía respuesta - conversación finalizada")
        
        # Responder inmediatamente (sin esperar procesamiento)
        return jsonify({"status": "accepted"}), 200
    
    except Exception as e:
        logger.exception(f"🔴 Error en webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def adaptar_procesar_mensaje(business_id: str, user_id: str, mensaje: str, client_name: str = "") -> str:
    """Procesa un mensaje usando LangGraph y devuelve el resultado como texto"""
    try:
        # 1. Datos obligatorios      
        if not user_id or not business_id or not mensaje:
            return exception("Faltan IDs o mensaje"), 500

        # 2. Crear Thread ID Único (Aislamiento de Memoria)
        # Esto asegura que Postgres guarde la conversación en un "cajón" único
        thread_id = f"{business_id}:{user_id}"
        
        # 3. Configuración para LangGraph
        # Pasamos business_id dentro de 'configurable' para que el nodo lo pueda leer
        config = {
            "configurable": {
                "thread_id": thread_id,
                "business_id": business_id,
                "client_name": client_name
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
        else:
            logger.warning(f"⚠️ Respuesta desconocida con status {status} para {thread_id}: {str(response)[:50]}")
            return  "⚠️ En este momento no puedo procesar su solicitud."

        return response

    except Exception as e:
        logger.exception(f"🔴 Error: {e}") 
        return  "No se pudo procesar su solicitud."


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
        logger.exception(f"🔴 Error borrando DB: {e}")
        return jsonify({"error": "Error al borrar memoria"}), 500


@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    try:
        # 1. Datos obligatorios
        mensaje = data.get('message')
        user_id = data.get('user_id')         # Ej: "549111234567"
        business_id = data.get('business_id') # Ej: "negocio_zapatillas"

        #Devolver el diccionario tal cual (Flask lo convierte a JSON)
        return adaptar_procesar_mensaje(business_id, user_id, mensaje)

    except Exception as e:
        logger.exception(f"🔴 Error: {e}") 
        return jsonify({"response": "No se pudo procesar su solicitud.", "status": "ERROR"}), 500


@app.route('/aprobar', methods=['POST'])
def aprobar():
    """Endpoint para recibir aprobaciones de usuarios humanos."""
    try:     
        logger.debug("[RCV <- WEB] Received Endpoint \"aprobar\" payload: {}", request.data[:500])  
        data = request.json

        business_id = data.get('business_id')
        user_id = data.get('user_id')
        decision = data.get('decision') # "approve" o "reject"
        
        thread_id = f"{business_id}:{user_id}"

        logger.info(f"Received approval request for thread_id={thread_id} with decision={decision}")

        # LLAMADA A LA FUNCIÓN DE APROBACIÓN
        resultado = ejecutar_aprobacion(thread_id, decision)
        
        procesar_respuesta_LLM(resultado, user_id, business_id)
        
        return jsonify({"status": "APROBACION_PROCESADA"})

    except Exception as e:
        logger.exception(f"🔴 Error en aprobación: {e}")
        return jsonify({"error": str(e)}), 500


# # Prueba rápida al iniciar el script directamente
# logger.info("✅ Inicianda la app Flask...")
# telefono_cliente = "5491112345678"

# print("--- CASO 1: El cliente escribe a la Pizzería ---")
# resp = procesar_mensaje(
#     business_id="pizzeria_luigi",
#     user_id=telefono_cliente, 
#     mensaje_usuario="Hola, ¿qué venden?"
# )
# print(f"🍕 Bot Pizzería: {resp}\n")

# print("--- CASO 2: El MISMO cliente escribe a Nike ---")
# resp2 = procesar_mensaje(
#     business_id="zapatillas_nike_outlet",
#     user_id=telefono_cliente,
#     mensaje_usuario="Hola, ¿qué venden?"
# )
# print(f"👟 Bot Nike: {resp2}\n")

# print("--- CASO 3: Probando Memoria en Pizzería ---")
# # El bot de pizza debería recordar que ya saludamos, pero no saber nada de zapatillas
# resp3 = procesar_mensaje(
#     business_id="pizzeria_luigi",
#     user_id=telefono_cliente,
#     mensaje_usuario="¿Tienen de ananá?"
# )
# print(f"🍕 Bot Pizzería: {resp3}")

    
logger.info("✅ App Flask iniciada.")

if __name__ == '__main__':
    try:
        # Ejecutar Flask con threading habilitado
        app.run(
            host='0.0.0.0',
            port=5000,
            threaded=True,  # Importante: habilitar threading
            debug=False    # Cambiar a False en producción
        )
    except Exception as e:
        logger.exception(f"🔴 Error de inicio a app: {e}")
    #finally:
        # Detener scheduler al cerrar la aplicación
        # if scheduler:
        #     scheduler.shutdown()
        #     logger.info("🔴 🟢 y 🟡, o 🟩 y 🟨, o ✅ y ⚠️Scheduler detenido")
