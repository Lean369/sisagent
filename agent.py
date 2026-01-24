import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from flask import Flask, request, jsonify
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import logging
from logging.handlers import RotatingFileHandler
import httpx
import requests
from langchain_anthropic import ChatAnthropic
from langchain_community.llms import HuggingFaceHub
from langchain_community.chat_models import ChatHuggingFace
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_classic.memory import ConversationBufferMemory
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
import pickle
import json
from dotenv import load_dotenv

# Importar prompts personalizados
try:
    from prompts import AGENT_INSTRUCTION
    print(f"✅ AGENT_INSTRUCTION cargado: {len(AGENT_INSTRUCTION)} caracteres")
    SESSION_INSTRUCTION = ""  # No se usa actualmente
except Exception as e:
    print(f"❌ Error importando prompts: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    AGENT_INSTRUCTION = ""
    SESSION_INSTRUCTION = ""

# Importar herramientas del agente
from agent_tools import (
    extract_lead_info,
    trigger_booking_tool
)

# Cargar variables de entorno
load_dotenv()

# Cargar conocimiento del negocio desde JSON
CONOCIMIENTO_NEGOCIO = {}
try:
    with open('conocimiento_negocio.json', 'r', encoding='utf-8') as f:
        CONOCIMIENTO_NEGOCIO = json.load(f)
    print("✅ Conocimiento del negocio cargado exitosamente")
except FileNotFoundError:
    print("⚠️  Advertencia: No se encontró conocimiento_negocio.json")
except json.JSONDecodeError as e:
    print(f"⚠️  Error al parsear conocimiento_negocio.json: {e}")

# Configuración
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "your_api_key")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "default")
EVOLUTION_INSTANCE_ID = os.getenv("EVOLUTION_INSTANCE_ID", "")

# Configuración del LLM - Elige uno de estos proveedores
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")  # opciones: gemini, anthropic, huggingface, openai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "your_gemini_key")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your_anthropic_key")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "your_hf_key")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_openai_key")

# Límite de mensajes en memoria por conversación
MAX_MESSAGES_PER_CONVERSATION = int(os.getenv("MAX_MESSAGES", "50"))  # Límite de mensajes en memoria

# Configuración para transcripción de audio
TRANSCRIPTION_ENABLED = os.getenv("TRANSCRIPTION_ENABLED", "true").lower() == "true"
TRANSCRIPTION_PROVIDER = os.getenv("TRANSCRIPTION_PROVIDER", "openai")  # opciones: openai, whisper-local

# Almacenamiento simple de memoria por usuario (thread-safe con Lock)
user_memories: Dict[str, Dict] = {}

# Configurar logging con rotación de archivos para evitar llenar el disco
# Mantiene hasta 10MB por archivo, con 5 archivos de respaldo (total: 50MB máximo)
rotating_handler = RotatingFileHandler(
    'sisagent_verbose.log',
    maxBytes=10*1024*1024,  # 10 MB por archivo
    backupCount=5,  # Mantener 5 archivos de respaldo (agent_verbose.log.1, .2, etc.)
    encoding='utf-8'
)
rotating_handler.setLevel(logging.DEBUG)
rotating_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

# Configurar el logger específico sin usar basicConfig para evitar duplicación
logger = logging.getLogger('sisagent')
logger.setLevel(logging.DEBUG)

# Limpiar handlers existentes para evitar duplicación
if logger.hasHandlers():
    logger.handlers.clear()

logger.addHandler(rotating_handler)
logger.addHandler(console_handler)
# Evitar que los logs se propaguen al root logger (evita duplicación)
logger.propagate = False

# Log de verificación del AGENT_INSTRUCTION
logger.info(f"🔍 Verificación AGENT_INSTRUCTION: {len(AGENT_INSTRUCTION)} caracteres")
if len(AGENT_INSTRUCTION) == 0:
    logger.error("❌ AGENT_INSTRUCTION está VACÍO - El agente NO funcionará correctamente")
else:
    logger.info(f"✅ AGENT_INSTRUCTION cargado correctamente")
    logger.debug(f"Primeros 200 chars: {AGENT_INSTRUCTION[:200]}")

# Configuración
app = Flask(__name__)

# Pool de threads para manejar múltiples mensajes en paralelo
# CPU de 4 núcleos (max_workers=10)
# CPU de 8+ núcleos (max_workers=20)
executor = ThreadPoolExecutor(max_workers=4)  # CPU de 2 núcleos - 10 mensajes simultáneos

# Locks para thread-safety
memory_lock = Lock()
lead_lock = Lock()

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
        "apikey": EVOLUTION_API_KEY
    }
    
    # Detectar si el mensaje incluye botones
    is_button_message = isinstance(mensaje, dict) and mensaje.get('type') == 'button'
    
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
    if instance_id:
        candidates.append(str(instance_id))
    if instance_name:
        candidates.append(str(instance_name))
    # Añadir configuración desde entorno como último recurso
    if EVOLUTION_INSTANCE_ID:
        candidates.append(str(EVOLUTION_INSTANCE_ID))
    if EVOLUTION_INSTANCE and EVOLUTION_INSTANCE not in candidates:
        candidates.append(str(EVOLUTION_INSTANCE))

    # Deduplicate preserving order
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    for candidate in candidates:
        # Usar siempre sendText (Evolution API no tiene endpoint sendButtons separado)
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

            logger.debug("Tried %s with candidate=%s status=%s response=%s", endpoint_type, candidate, status, str(text)[:200])

            if 200 <= status < 300:
                return text
            # Continue trying next candidate on 4xx/5xx
        except Exception as e:
            logger.exception("Exception when sending with candidate %s: %s", candidate, e)

    # If none succeeded, return an informative structure
    msg_type = "button message" if is_button_message else "text message"
    logger.error("All send attempts failed for number=%s (type=%s); tried=%s", numero, msg_type, candidates)
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
            logger.warning("[AUDIO] Transcripción deshabilitada")
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
                logger.error(f"[AUDIO] Error descargando audio: status={response.status_code}")
                return None
        
        if not audio_data:
            logger.error("[AUDIO] No se pudo obtener datos de audio")
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
            logger.warning(f"[AUDIO] Error convirtiendo audio: {conv_error}, usando archivo original")
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
            logger.warning(f"[AUDIO] Error limpiando archivos temporales: {e}")
        
        if transcription:
            logger.info(f"[AUDIO] ✅ Transcripción exitosa: {transcription[:100]}...")
            return transcription
        else:
            logger.error("[AUDIO] No se obtuvo transcripción")
            return None
            
    except Exception as e:
        logger.exception(f"[AUDIO] Error transcribiendo audio: {e}")
        return None


def get_memory(user_id: str) -> ConversationBufferMemory:
    """Obtiene o crea memoria para un usuario (thread-safe)"""
    with memory_lock:
        logger.debug("get_memory called for user_id=%s", user_id)
        if user_id not in user_memories:
            # Intentar usar ConversationBufferMemory si está disponible
            try:
                # Ya importado al inicio del archivo
                memory_obj = ConversationBufferMemory(
                    memory_key="chat_history",
                    return_messages=True
                )
                # Agregar flag para rastrear si se envió link de reserva
                memory_obj.booking_sent = False
                user_memories[user_id] = memory_obj
                logger.debug("Created ConversationBufferMemory with booking_sent=False for user_id=%s", user_id)
            except Exception:
                # Fallback simple: almacenar mensajes en memoria con la misma API mínima
                class _SimpleChatMemory:
                    def __init__(self):
                        self.messages: List = []

                    def add_user_message(self, text: str):
                        self.messages.append(HumanMessage(content=text))

                    def add_ai_message(self, text: str):
                        self.messages.append(AIMessage(content=text))

                class _SimpleMemory:
                    def __init__(self):
                        self.chat_memory = _SimpleChatMemory()
                        self.booking_sent = False

                user_memories[user_id] = _SimpleMemory()
                logger.debug("Created simple in-memory conversation memory with booking_sent=False for user_id=%s", user_id)

    return user_memories[user_id]


def truncate_memory(memory) -> None:
    """
    Trunca la memoria para mantener solo los últimos MAX_MESSAGES_PER_CONVERSATION mensajes.
    Modifica la memoria in-place.
    """
    try:
        current_count = len(memory.chat_memory.messages)
        if current_count > MAX_MESSAGES_PER_CONVERSATION:
            # Mantener solo los últimos N mensajes
            memory.chat_memory.messages = memory.chat_memory.messages[-MAX_MESSAGES_PER_CONVERSATION:]
            logger.info(
                f"Truncated memory: {current_count} → {MAX_MESSAGES_PER_CONVERSATION} messages"
            )
    except Exception as e:
        logger.warning(f"Failed to truncate memory: {e}")


def crear_agente():
    """Crea el LLM para el agente"""
    llm = get_llm_model()
    logger.debug("LLM instance created: %s", type(llm).__name__)
    return llm


def get_llm_model(provider_override=None):
    """Retorna el modelo LLM según la configuración
    
    Args:
        provider_override: Si se especifica, usa este provider en lugar del configurado
    """
    provider = (provider_override or LLM_PROVIDER).lower()
    logger.debug("Configuring LLM provider: %s", provider)
    
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        model_name = os.getenv("GEMINI_MODEL", "")
        logger.debug("Using Google Gemini model: %s", model_name)
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=GEMINI_API_KEY,
            temperature=0.8,
            max_tokens=2048,
        )
    
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=ANTHROPIC_API_KEY,
            temperature=0.7
        )
    
    elif provider == "huggingface":
        model_id = os.getenv("HF_MODEL", "")
        logger.debug("Using HuggingFace API for model: %s", model_id)
        
        from huggingface_hub import InferenceClient
        
        # Wrapper para HuggingFace con chat_completion
        class HFChatWrapper:
            def __init__(self, model, token):
                self.model = model
                self.client = InferenceClient(token=token)
            
            def invoke(self, messages: List):
                # Convertir mensajes al formato de HuggingFace
                hf_messages = []
                for m in messages:
                    role = type(m).__name__
                    if role == 'SystemMessage':
                        hf_messages.append({"role": "system", "content": m.content})
                    elif role == 'HumanMessage':
                        hf_messages.append({"role": "user", "content": m.content})
                    elif role == 'AIMessage':
                        hf_messages.append({"role": "assistant", "content": m.content})
                
                try:
                    response = self.client.chat_completion(
                        messages=hf_messages,
                        model=self.model,
                        max_tokens=512,
                        temperature=0.7,
                    )
                    content = response.choices[0].message.content
                    return type("Resp", (), {"content": content})()
                except Exception as e:
                    logger.error(f"Error calling HuggingFace: {e}")
                    return type("Resp", (), {"content": "Lo siento, hubo un error al procesar tu solicitud."})()
        
        return HFChatWrapper(model_id, HUGGINGFACE_API_KEY)
    
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        model_name = os.getenv("OPENAI_MODEL", "")
        logger.debug("Using OpenAI model: %s", model_name)
        return ChatOpenAI(
            model=model_name,
            api_key=OPENAI_API_KEY,
            temperature=0.7
        )
    
    elif provider == "ollama":
        # Para modelos locales con Ollama
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "llama2"),
            base_url=os.getenv("OLLAMA_URL", "http://localhost:11434")
        )
    
    elif provider == "local_huggingface":
        # Opción 2: Modelo local de HuggingFace (requiere más recursos)
        from langchain_community.llms import HuggingFacePipeline
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
        
        model_id = os.getenv("HF_LOCAL_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            device_map="auto",
            load_in_8bit=True  # Reduce uso de memoria
        )
        
        pipe = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=512,
            temperature=0.7,
            top_p=0.95,
            repetition_penalty=1.15
        )
        
        return HuggingFacePipeline(pipeline=pipe)
    
    else:
        raise ValueError(f"Proveedor LLM no soportado: {provider}")


# Instancia global del agente
agente = crear_agente()


@app.route('/webhook', methods=['POST'])
def webhook():
    """Endpoint para recibir webhooks de Evolution API - CON CONCURRENCIA"""
    try:
        payload = request.get_json()
        logger.info("Received webhook payload: %s", json.dumps(payload)[:500])
        
        # Extraer información del mensaje
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
            
            remitente = mensaje_data.get('key', {}).get('remoteJid', '')
            from_me = mensaje_data.get('key', {}).get('fromMe', False)
            push_name = mensaje_data.get('pushName', '') or mensaje_data.get('verifiedBizName', '')
            # Intentar obtener instance/id proporcionado en el webhook
            webhook_instance = payload.get('instance') or mensaje_data.get('instanceId') or None
            
            # Si es una imagen, video, documento o sticker, pedir que escriba texto
            if (image_message or video_message or document_message or sticker_message) and not from_me and remitente:
                tipo_archivo = "imagen" if image_message else \
                               "video" if video_message else \
                               "documento" if document_message else \
                               "sticker"
                
                logger.info(f"Received {tipo_archivo.upper()} from {remitente} ({push_name}), requesting text message")
                # Enviar en background usando ThreadPool
                executor.submit(
                    enviar_mensaje_whatsapp,
                    remitente,
                    f"Gracias por tu {tipo_archivo}. Para poder ayudarte mejor, ¿podrías escribir tu consulta como texto? 📝",
                    webhook_instance,
                    payload.get('instance')
                )
                return {"status": "success"}
            
            # Si es un mensaje de audio, transcribirlo
            if audio_message and not from_me and remitente:
                logger.info("Processing AUDIO message from %s (%s)", remitente, push_name)
                
                # Extraer URL o base64 del audio
                audio_url = audio_message.get('url', '')
                audio_base64 = audio_message.get('base64', '')
                
                # Transcribir el audio
                transcripcion = transcribir_audio(audio_url, audio_base64)
                
                if transcripcion:
                    logger.info(f"[AUDIO] Procesando transcripción como mensaje de texto")
                    mensaje = transcripcion
                else:
                    logger.warning("[AUDIO] No se pudo transcribir, enviando mensaje genérico")
                    # Enviar en background usando ThreadPool
                    executor.submit(
                        enviar_mensaje_whatsapp,
                        remitente, 
                        "Disculpa, recibí tu mensaje de audio pero tuve problemas para transcribirlo. ¿Podrías escribirlo como texto?",
                        webhook_instance,
                        payload.get('instance')
                    )
                    return {"status": "success"}
            
            if mensaje and remitente and not from_me:
                logger.info("Processing message from %s (%s): %s", remitente, push_name, mensaje)
                # Procesar mensaje con el nombre del cliente
                respuesta = procesar_mensaje(remitente, mensaje, client_name=push_name)
                
                # Solo enviar respuesta si no es None (conversación finalizada)
                if respuesta is not None:
                    # Enviar respuesta en background usando ThreadPool
                    executor.submit(enviar_mensaje_whatsapp, remitente, respuesta, webhook_instance, payload.get('instance'))
                else:
                    logger.info("[BOOKING] No se envía respuesta - conversación finalizada")
        
        # Soporte alternativo para formato con lista de mensajes
        for msg in payload.get("messages", []):
            if msg.get("type") == "conversation":
                from_jid = msg["key"]["remoteJid"]
                text = msg["message"]["conversation"]
                from_me = msg["key"].get("fromMe", False)
                push_name = msg.get('pushName', '') or msg.get('verifiedBizName', '')
                
                if text and from_jid and not from_me:
                    logger.info("Processing message from %s (%s): %s", from_jid, push_name, text)
                    respuesta = procesar_mensaje(from_jid, text, client_name=push_name)
                    # Solo enviar respuesta si no es None (conversación finalizada)
                    if respuesta is not None:
                        # If the msg contains instance info, prefer it
                        msg_instance = msg.get('instance') or msg.get('instanceId')
                        #await enviar_mensaje_whatsapp(from_jid, respuesta, instance_id=msg_instance, instance_name=msg.get('instance'))
                        # Procesar en background usando ThreadPool
                        # Esto NO bloquea el webhook, responde inmediatamente
                        executor.submit(enviar_mensaje_whatsapp, from_jid, respuesta, instance_id=msg_instance, instance_name=msg.get('instance'))
                        logger.info(f"✅ Mensaje encolado de {from_jid} para envío en background")
                    else:
                        logger.info("[BOOKING] No se envía respuesta - conversación finalizada")
        
        # Responder inmediatamente (sin esperar procesamiento)
        return jsonify({"status": "accepted"}), 202
    
    except Exception as e:
        print(f"Error en webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def es_mensaje_generico(mensaje: str) -> bool:
    """Detecta si un mensaje es solo un saludo o agradecimiento genérico sin pregunta real"""
    mensaje_lower = mensaje.lower().strip()
    
    # Palabras/frases genéricas que no requieren respuesta después de enviar el link
    palabras_genericas = [
        'hola', 'hello', 'hi', 'buenas', 'buenos dias', 'buenas tardes', 'buenas noches',
        'gracias', 'thanks', 'thank you', 'muchas gracias', 'ok', 'okay', 'dale', 
        'perfecto', 'excelente', 'genial', 'bárbaro', 'entendido', 'listo', 'si', 'sí',
        'no', 'chau', 'adiós', 'adios', 'bye', 'hasta luego', 'nos vemos'
    ]
    
    # Si el mensaje es muy corto y está en la lista, es genérico
    if len(mensaje_lower) < 20:
        for palabra in palabras_genericas:
            if mensaje_lower == palabra or mensaje_lower.startswith(palabra + ' ') or mensaje_lower.endswith(' ' + palabra):
                return True
    
    # Si tiene signos de interrogación, es una pregunta real
    if '?' in mensaje:
        return False
        
    return False


def mark_tool_as_executed(user_id: str):
    """Marca la conversación de un usuario como manejada (no responder más)"""
    # Obtener memoria del usuario
    memory = get_memory(user_id)
    
    # Marcar que se envió el link de reserva (siempre existe ahora)
    memory.booking_sent = True
    logger.info(f"[BOOKING] ✅ booking_sent establecido en True para user_id={user_id}")


def procesar_mensaje(user_id: str, mensaje: str, client_name: str = "") -> str:
    """Procesa un mensaje usando el LLM"""
    try:
        # Obtener memoria del usuario
        memory = get_memory(user_id)

        # Extraer información de lead 
        extract_lead_info(user_id, mensaje, client_name=client_name)
        
        # Detectar si es el primer mensaje (saludo inicial)
        is_first_message = len(memory.chat_memory.messages) == 0

        client_info = f"\nNombre del cliente: {client_name}" if client_name else ""
        
         # Leer estado de booking_sent
        booking_status = getattr(memory, 'booking_sent', False)
        booking_info = f"\n\n🚨 booking_sent = {booking_status}"
        logger.debug(f"[BOOKING] Estado de booking_sent para user_id={user_id}: {booking_status}")
        
        # Crear sistema de prompt enriquecido
        system_prompt = AGENT_INSTRUCTION + f"""\nFecha: {datetime.now().strftime("%Y-%m-%d")}{client_info}{booking_info}"""
        
        # Construir mensajes
        messages = [SystemMessage(content=system_prompt)]
        messages.extend(memory.chat_memory.messages)
        messages.append(HumanMessage(content=mensaje))
        
        # Invocar LLM con sistema de fallback
        try:
            respuesta_llm = agente.invoke(messages)
            respuesta = respuesta_llm.content
            # LOG DEL MENSAJE ENVIADO AL LLM
            logger.debug("="*80)
            logger.debug(f"[MENSAJE AL LLM]: {mensaje}")
            logger.debug("="*80)
        except Exception as llm_error:
            logger.error(f"Error con LLM provider principal ({LLM_PROVIDER}): {llm_error}")
            
            # Intentar con el fallback si está configurado
            fallback_provider = os.getenv('LLM_PROVIDER_FALLBACK', '').strip()
            if fallback_provider and fallback_provider.lower() != LLM_PROVIDER.lower():
                logger.warning(f"⚠️ Intentando con proveedor de respaldo: {fallback_provider}")
                try:
                    # Obtener instancia del LLM de fallback
                    agente_fallback = get_llm_model(provider_override=fallback_provider)
                    respuesta_llm = agente_fallback.invoke(messages)
                    respuesta = respuesta_llm.content
                    logger.info(f"✅ Respuesta exitosa con proveedor de respaldo: {fallback_provider}")
                except Exception as fallback_error:
                    logger.error(f"❌ Error también con proveedor de respaldo ({fallback_provider}): {fallback_error}")
                    return "Gracias por contactarnos. En este momento estamos experimentando dificultades técnicas. Por favor, intenta nuevamente en unos minutos o contáctanos directamente al número de atención al cliente."
            else:
                # No hay fallback configurado o es el mismo provider
                logger.error("❌ No hay proveedor de respaldo configurado o es el mismo que el principal")
                return "Gracias por contactarnos. En este momento estamos experimentando dificultades técnicas. Por favor, intenta nuevamente en unos minutos o contáctanos directamente al número de atención al cliente."
        
        # LOG DE LA RESPUESTA
        logger.debug("="*80)
        logger.debug(f"[RESPUESTA DEL LLM]: {str(respuesta)[:200]}")
        logger.debug("="*80)
        
        # Manejar diferentes formatos de respuesta del LLM
        if isinstance(respuesta, list):
            # Si es una lista de diccionarios, extraer el texto
            logger.debug("Respuesta es una lista, extrayendo texto de cada parte")
            texto_partes = []
            for item in respuesta:
                if isinstance(item, dict) and 'text' in item:
                    texto_partes.append(item['text'])
                elif isinstance(item, str):
                    texto_partes.append(item)
            respuesta = ''.join(texto_partes)
        elif not isinstance(respuesta, str):
            # Convertir a string si no es string
            respuesta = str(respuesta)
        
        # Verificar si se activó la TOOL
        if "accion" in respuesta:
            try:
                # Intentar extraer JSON de bloques markdown si existe
                import re
                json_match = re.search(r'```(?:json)?\s*(\{[^`]+\})\s*```', respuesta, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # Buscar JSON directamente en la respuesta
                    json_match = re.search(r'\{[^}]*"accion"[^}]*\}', respuesta, re.DOTALL)
                    json_str = json_match.group(0) if json_match else respuesta
                
                datos = json.loads(json_str)
                accion = datos.get("accion")
                
                if accion == "reserva":
                    respuesta = trigger_booking_tool(user_id, mensaje, client_name=client_name)
                    mark_tool_as_executed(user_id)

            except json.JSONDecodeError as e:
                logger.warning(f"Error al parsear JSON: {e}")
                pass  # Si no es JSON válido, usar la respuesta como está
        
        # Guardar en memoria
        memory.chat_memory.add_user_message(mensaje)
        # Si la respuesta es un dict con botón, guardar el texto del contenido
        if isinstance(respuesta, dict) and respuesta.get('type') == 'button':
            respuesta_texto = respuesta['content']['text']
        else:
            respuesta_texto = str(respuesta)

        # Guardar en memoria (thread-safe)
        with memory_lock:  
            memory.chat_memory.add_ai_message(respuesta_texto)
        
        # Truncar memoria si excede el límite
        truncate_memory(memory)
        
        return respuesta
    
    except Exception as e:
        logger.exception(f"Error procesando mensaje: {e}")
        return "Lo siento, ocurrió un error al procesar tu mensaje. Por favor intenta de nuevo."


@app.route("/health", methods=['GET'])
def health():
    """Endpoint de salud"""
    return {"status": "ok"}


@app.route("/memory", methods=['GET'])
def memory_index():
    """Lista los user_ids en memoria y la cantidad de mensajes guardados por cada uno."""
    result = {}
    for uid, mem in user_memories.items():
        try:
            count = len(mem.chat_memory.messages)
        except Exception:
            # Soporte para otras implementaciones de memoria
            try:
                count = len(mem.chat_memory._get_messages())
            except Exception:
                count = 0
        result[uid] = count
    return result


@app.route("/memory/<user_id>", methods=['GET'])
def memory_detail(user_id: str):
    """Devuelve detalle de la memoria para un usuario: conteo y los últimos 10 mensajes."""
    mem = user_memories.get(user_id)
    if not mem:
        return {"user_id": user_id, "count": 0, "messages": []}

    msgs = []
    try:
        # Intentar leer la lista estándar creada en el fallback
        raw = mem.chat_memory.messages
        for m in raw[-20:]:
            role = type(m).__name__
            msgs.append({"role": role, "content": getattr(m, 'content', str(m))})
    except Exception:
        try:
            # Intento alternativo para ConversationBufferMemory
            raw = mem.load_memory_variables({}).get('chat_history', [])
            for m in raw[-20:]:
                msgs.append({"role": type(m).__name__, "content": getattr(m, 'content', str(m))})
        except Exception:
            msgs = []

    return {"user_id": user_id, "count": len(msgs), "messages": msgs}


if __name__ == '__main__':

    # Servidor
    print(f"\n🚀 SERVIDOR:")
    print(f"  🌐 Host: 0.0.0.0")
    print(f"  🔌 Puerto: 5000")
    print(f"  📋 Endpoints disponibles:")
    print(f"     POST /webhook - Recibe mensajes de WhatsApp")
    print(f"     GET  /health - Estado del servicio")
    print(f"     GET  /memory - Lista de conversaciones activas")
    print(f"     GET  /memory/{{user_id}} - Detalles de conversación")
    print("🔄 Modo concurrente: 10 workers activos")

    print("\n" + "="*60)
    print("✅ Inicialización completada - Esperando mensajes...")
    print("="*60 + "\n")

    # Ejecutar Flask con threading habilitado
    app.run(
        host='0.0.0.0',
        port=5000,
        threaded=True,  # Importante: habilitar threading
        debug=False     # Cambiar a False en producción
    )