from loguru import logger
from logger_config import inicializar_logger, generar_resumen_auditoria
from flask import Flask, request, jsonify
from flask import Response
# 🚀 1. Inicializar el logger ANTES que el resto del sistema
inicializar_logger()
from agente import procesar_mensaje, obtener_todas_las_tools, TOOLS_REGISTRY
from utilities import obtener_configuraciones
from tools_hitl import decodificar_token_reactivacion
from langchain_core.runnables.graph import CurveStyle, NodeStyles, MermaidDrawMethod
from ddos_protection import ddos_protection
import sys
from agente import pool, workflow_builder # Importamos el builder, NO la app completa
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import ToolMessage
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

DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"


def enviar_mensaje_whatsapp(numero_destino: str, mensaje, nombre_instancia: str = None, instance_id: str = None):
    """Envía un mensaje a través de Evolution API.
    """

    EVOLUTION_URL = os.environ.get("EVOLUTION_API_URL", "https://evoapi.sisnova.com.ar")
    # headers = {
    #     "Content-Type": "application/json",
    #     "apikey": os.environ.get("EVOLUTION_API_KEY")
    # }      
    
    # logger.debug(f"Instance_name: {instance_name} - instance_id: {instance_id}")
    # logger.debug(f"Enviando mensaje a WhatsApp: {numero_destino} - {str(mensaje)[:50]}...")

    try:
        # response = requests.post(
        #     f"{evo_url}/message/sendText/{instance_name}", # Usamos la instancia del negocio
        #     json={"number": numero_destino, "text": mensaje},
        #     headers=headers
        # )
        url = f"{EVOLUTION_URL}/message/sendText/{nombre_instancia}"
        headers = {"apikey": os.environ.get("EVOLUTION_API_KEY")}
        
        payload = {
            # Evolution requiere el formato de número internacional sin el '+'
            "number": f"{numero_destino}", 
            "text": mensaje,
            "options": {
                "presence": "composing" # Muestra "Escribiendo..." en el celular del usuario
            }
        }
    
        response = requests.post(url, json=payload, headers=headers)
        status = response.status_code
        
        # Log full body for non-2xx to help debugging
        text = None
        try:
            text = response.json()
        except Exception:
            text = response.text
        
        logger.debug(f"Sent: with instance={nombre_instancia} status={status} response={str(text)[:200]}")
            
        telefono = numero_destino.split('@')[0] if numero_destino else "unknown"
        msg = f"[SND -> EVO] 📤 TEL: {telefono} - MSG: {str(mensaje)[:100]}..."
        generar_resumen_auditoria(nombre_instancia, msg)

        # # Llamar a findContacts para actualizar el contacto (si está habilitado)
        # if os.environ.get("SEND_FIND_CONTACTS", "false").lower() == "true":
        #     logger.debug(f"Attempting to call findContacts for instance={nombre_instancia} and numero={numero}")
        #     url2 = f"{EVOLUTION_API_URL}/chat/findContacts/{nombre_instancia}"
        #     payload2 = {
        #         "where": {
        #             "id": numero_destino
        #         }
        #     }
        #     response2 = requests.post(url2, json=payload2, headers=headers, timeout=30.0, verify=False)
        #     logger.debug(f"[SND -> EVO] findContacts response: {response2.status_code} {response2.text}")

        if 200 <= status < 300:
            return text
        else:
            logger.error(f"❌ Evolution API error: status={status}, response={text}")
            return {"status": status, "error": "Evolution API error", "response": text}
            
    except Exception as e:
        logger.error(f"🔴 Exception when sending with instance {nombre_instancia}: {e}")
        return {"status": "failed", "error": str(e)}


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
        TRANSCRIPTION_ENABLED = os.getenv("TRANSCRIPTION_ENABLED", "true").lower() == "true"
        TRANSCRIPTION_PROVIDER = os.getenv("TRANSCRIPTION_PROVIDER", "openai")
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

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
        try:
            os.unlink(temp_audio_path)
            if audio_path_to_use != temp_audio_path and os.path.exists(audio_path_to_use):
                os.unlink(audio_path_to_use)
        except Exception as e:
            logger.error(f"⚠️ [AUDIO] Error limpiando archivos temporales: {e}")
        
        if transcription:
            logger.info(f"[AUDIO] Transcripción exitosa: {transcription[:100]}...")
            return transcription
        else:
            logger.error("❌ [AUDIO] No se obtuvo transcripción")
            return None
            
    except Exception as e:
        logger.error(f"🔴 [AUDIO] Error transcribiendo audio: {e}")
        return None


def adaptar_procesar_mensaje(business_id: str, user_id: str, mensaje: str, client_name: str = "") -> str:
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


def procesar_y_responder_evoapi(business_id, user_id, mensaje, push_name, instance_id):
    """
    Función que corre en background:
    1. Llama al Agente (Lento)
    2. Envía la respuesta por WhatsApp (I/O)
    """
    try:    

        # 1. Proceso Lento (IA)
        respuesta_ia = adaptar_procesar_mensaje(business_id, user_id, mensaje, client_name=push_name)
        
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 IA terminó para {user_id}. Enviando respuesta...")
            enviar_mensaje_whatsapp(user_id, respuesta_ia, business_id, instance_id)
        else:
            logger.warning(f"⚠️ IA no generó respuesta para {user_id}")
            #respuesta_ia = "Lo siento, no pude generar una respuesta en este momento."
            #enviar_mensaje_whatsapp(user_id, respuesta_ia, business_id, instance_name=instance_id)

    except Exception as e:
        logger.error(f"🔴 Error en worker background para {user_id}: {e}")


def worker_procesar_audio(business_id, user_id, audio_url, audio_base64, push_name, instance_id):
    try:
        # 1. Transcribir (Lento)
        texto_transcrito = transcribir_audio(audio_url, audio_base64)
        
        if texto_transcrito:
            logger.info(f"🗣️ Audio transcrito: {texto_transcrito[:50]}...")
            # 2. Reutilizamos el worker de texto existente para procesar con IA
            procesar_y_responder_evoapi(business_id, user_id, texto_transcrito, push_name, instance_id)
        else:
            msg = "Disculpa, no pude escuchar bien el audio. ¿Podrías escribirlo? 📝"
            enviar_mensaje_whatsapp(user_id, msg, business_id, instance_id)

    except Exception as e:
        logger.error(f"🔴 Error procesando audio background: {e}")


def enviar_mensaje_chatwoot(account_id, conversation_id, texto_respuesta, telefono, business_id):
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

        msg = f"[SND -> EVO] 📤 TEL: {telefono} - MSG: {texto_respuesta[:100]}..."
        generar_resumen_auditoria(business_id, msg)

    except requests.exceptions.RequestException as e:
        logger.error(f"🔴 Error enviando a Chatwoot: {e}")


def procesar_y_responder_chatwoot(business_id, user_id, mensaje, conversation_id, account_id, client_name: str = "", phone_number: str = ""):
    """Función que corre en background para procesar mensajes de Chatwoot y responder"""

    try:       
        logger.debug(f"Procesando mensaje para Chatwoot user_id={user_id} (Conv ID: {conversation_id})")

        # 1. Proceso Lento (IA)
        respuesta_ia = adaptar_procesar_mensaje(business_id, user_id, mensaje, client_name=client_name)
            
        # 2. Envío de respuesta
        if respuesta_ia:
            logger.info(f"🤖 IA terminó para {user_id}. Enviando respuesta...")
            enviar_mensaje_chatwoot(account_id, conversation_id, respuesta_ia, phone_number, business_id)
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
        phone_number = str(data.get('sender', {}).get('phone_number'))
        client_name = data.get('sender', {}).get('name') or phone_number or "unknown"
        channel = data.get('conversation', {}).get('channel')
        
        msg = f"[RCV <- EVO] 📨 TEL: {phone_number} - MSG: {mensaje[:100]}..."
        generar_resumen_auditoria(business_id, msg)

        # 4. Generar el user_id para LangGraph usando el conversation_id
        user_id = f"{phone_number.replace('+', '')}@{channel}@{account_id}@{conversation_id}" if phone_number else f"conv_{conversation_id}"
        logger.debug(f"Extracted data - business_id: {business_id}, user_id: {user_id}, conversation_id: {conversation_id}, account_id: {account_id}")

        # 5. Delegar al ThreadPool (igual que hacías con WhatsApp)
        executor.submit(
            procesar_y_responder_chatwoot, 
            business_id, 
            user_id, 
            mensaje, 
            conversation_id, 
            account_id,
            client_name,
            phone_number
        )

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
        logger.info(f"📨 Received webhook payload: {json.dumps(payload)}")
        
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

            # Intentar obtener instance/id proporcionado en el webhook desde Evolution API
            business_id = payload.get('instance') or None
            instance_id = mensaje_data.get('instanceId') or None

            telefono = user_id.split('@')[0] if user_id else "unknown"
            msg = f"[RCV <- EVO] 📨 TEL: {telefono} - MSG: {mensaje[:100]}..."
            generar_resumen_auditoria(business_id, msg)

            # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
            if user_id and not from_me and DDOS_PROTECTION_ENABLED and ddos_protection:
                puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id)
                if not puede_procesar:
                    logger.warning(f"⛔ DDoS Protection: bloqueando mensaje de {user_id}: {mensaje_error}")
                    # NO enviar mensaje automático para prevenir loops
                    return jsonify({"status": "blocked", "reason": "rate_limit", "message": mensaje_error}), 429
                else:
                    logger.debug(f"🛡️ DDoS Protection: mensaje permitido de {user_id}")
            
            #[TEXTO] Procesar mensaje de texto normal
            if mensaje and user_id and not from_me:
                logger.info(f"Incomming TEXT message from {user_id} ({push_name})")
                executor.submit(procesar_y_responder_evoapi, business_id, user_id, mensaje, push_name, instance_id)    
            else:
                logger.debug("No es mensaje de texto o es de 'from_me', saltando procesamiento de texto.")

            # [MULTIMEDIA] Si es una imagen, video, documento o sticker, pedir que escriba texto
            if (image_message or video_message or document_message or sticker_message) and not from_me and user_id:
                tipo_archivo = "imagen" if image_message else \
                               "video" if video_message else \
                               "documento" if document_message else \
                               "sticker"
                
                logger.info(f"Incomming {tipo_archivo.upper()} from {user_id} ({push_name}), requesting text message..")
                # Enviar en background usando ThreadPool
                msg = f"Gracias por tu {tipo_archivo}. Para poder ayudarte mejor, ¿podrías escribir tu consulta como texto? 📝"
                executor.submit(enviar_mensaje_whatsapp, user_id, msg, business_id, instance_id)
            
            # [AUDIO] Si es un mensaje de audio
            if audio_message and not from_me and user_id:
                logger.info(f"🔊 Recibido AUDIO de {user_id}. Procesando en background...")
                audio_url = audio_message.get('url', '')
                audio_base64 = audio_message.get('base64', '')
                
                
                # Enviamos TODO al fondo inmediatamente
                executor.submit(worker_procesar_audio, business_id, user_id, audio_url, audio_base64, push_name, instance_id)
        
        # [LISTA] Soporte alternativo para formato con lista de mensajes
        for msg in payload.get("messages", []):
            if msg.get("type") == "conversation":
                user_id = msg["key"]["remoteJid"]
                text = msg["message"]["conversation"]
                from_me = msg["key"].get("fromMe", False)
                push_name = msg.get('pushName', '') or msg.get('verifiedBizName', '')
                
                if text and user_id and not from_me:
                    logger.info(f"Processing LIST message from {user_id} ({push_name})")
                    executor.submit(procesar_y_responder_evoapi, business_id, user_id, text, push_name, instance_id)  
                else:
                    logger.warning("⚠️[LIST] No se pudo procesar, enviando mensaje genérico")
                    msg = f"No pudimos procesar tu solicitud."
                    executor.submit(enviar_mensaje_whatsapp, user_id, msg, business_id, payload.get('instance'))
        
        # Responder inmediatamente (sin esperar procesamiento)
        logger.debug(f"Responding to webhook immediately with 200 OK - ID: {msg_id}")
        return jsonify({"status": "accepted"}), 200
    
    except Exception as e:
        logger.error(f"🔴 Error en webhook: {e}")
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


def ejecutar_reactivar_bot(business_id: str, user_id: str):
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
        # 1. Decodificar y Validar (Si esto pasa, los datos son auténticos)
        business_id, user_id = decodificar_token_reactivacion(token)
        
        # # # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
        # if user_id and not from_me and DDOS_PROTECTION_ENABLED and ddos_protection:
        #     puede_procesar, mensaje_error = ddos_protection.puede_procesar(user_id)
        #     if not puede_procesar:
        #         logger.warning(f"⛔ DDoS Protection: bloqueando mensaje de {user_id}: {mensaje_error}")
        #         # NO enviar mensaje automático para prevenir loops
        #         return jsonify({"status": "blocked", "reason": "rate_limit", "message": mensaje_error}), 429
        #     else:
        #         logger.debug(f"🛡️ DDoS Protection: mensaje permitido de {user_id}")

        thread_id = f"{business_id}:{user_id}"
        
        # 2. Lógica de Reactivación (Igual que antes)
        logger.info(f"🔓 Token validado. Reactivando {thread_id}")

        if ejecutar_reactivar_bot(business_id, user_id):
            return f"""
            <html>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: green;">✅ Bot Reactivado</h1>
                    <p>El cliente <b>{user_id}</b> ya puede hablar con la IA nuevamente.</p>
                    <p>Thread ID: {thread_id}</p>
                    <button onclick="window.close()">Cerrar pestaña</button>
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
        return adaptar_procesar_mensaje(business_id, user_id, mensaje)

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


logger.info("✅ App Flask iniciada.")

if __name__ == "__main__":
    # Flask es WSGI, no ASGI - usar app.run() directamente
    try:
        app.run(
            host='0.0.0.0',
            port=5001,
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
