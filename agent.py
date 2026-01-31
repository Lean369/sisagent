import os
import time
from datetime import datetime, timedelta
#from typing import Dict, List, Optional

from flask import Flask, request, jsonify
#from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import logging
from logging.handlers import RotatingFileHandler
import httpx
import requests
from langchain_community.llms import HuggingFaceHub
from langchain_community.chat_models import ChatHuggingFace
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_anthropic import ChatAnthropic
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

from typing import TypedDict, Annotated
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
import operator
from psycopg_pool import ConnectionPool
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
import pickle
import json
import uuid
from dotenv import load_dotenv
import google.auth
from google.auth.credentials import AnonymousCredentials

# --- INICIO DE LA ZONA DE PARCHES (NO TOCAR) ---
# 1. LIMPIEZA DE VENENO: Aseguramos que NO exista la variable de credenciales
# Si existe y está vacía o apunta a algo malo, hace fallar todo.
if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
    del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

# 2. Configurar el proyecto fantasma ANTES de importar nada de Google
os.environ["GOOGLE_CLOUD_PROJECT"] = "proyecto-bypass-gemini"

# 3. INICIALIZACIÓN FORZADA (El paso que faltaba)
try:
    from google.cloud import aiplatform
    # Esto le dice a la librería: "Ya estoy configurado, no busques nada más"
    # Al pasar location y project, evitamos que busque credenciales de red.
    aiplatform.init(
        project="proyecto-bypass-gemini",
        location="us-central1"
    )
    print("🟢 Vertex AI inicializado manualmente (Bypass activo).")
except ImportError:
    pass

# --- FIN DE LA ZONA DE PARCHES ---

# Cargar variables de entorno lo antes posible para que módulos importados posteriormente
# (por ejemplo `agent_control`) reciban las variables desde .env
load_dotenv(override=True)

# ===============================================================================
# === Configurar logging con rotación de archivos para evitar llenar el disco ===
# Mantiene hasta 10MB por archivo, con 5 archivos de respaldo (total: 50MB máximo)
rotating_handler = RotatingFileHandler(
    os.getenv('LOG_FILE', 'sisagent_verbose.log'),
    maxBytes=int(os.getenv('MAX_BYTES_LOG_FILE', 10485760)),  # 10 MB por archivo
    backupCount=int(os.getenv('BACKUP_COUNT_LOG_FILES', 5)),  # Mantener 5 archivos de respaldo (agent_verbose.log.1, .2, etc.)
    encoding='utf-8'
)
rotating_handler.setLevel(os.getenv('LOG_LEVEL', 'DEBUG'))
rotating_handler.setFormatter(logging.Formatter(os.getenv('LOG_FORMAT', '%(asctime)s %(levelname)s %(name)s: %(message)s')))

console_handler = logging.StreamHandler()
console_handler.setLevel(os.getenv('LOG_LEVEL', 'DEBUG'))
console_handler.setFormatter(logging.Formatter(os.getenv('LOG_FORMAT', '%(asctime)s %(levelname)s %(name)s: %(message)s')))

# Configurar el logger específico sin usar basicConfig para evitar duplicación
logger = logging.getLogger(os.getenv('LOGGER_NAME', 'agent'))
logger.setLevel(os.getenv('LOG_LEVEL', 'DEBUG'))

# Limpiar handlers existentes para evitar duplicación
if logger.hasHandlers():
    logger.handlers.clear()

logger.addHandler(rotating_handler)
logger.addHandler(console_handler)

# Evitar que los logs se propaguen al root logger (evita duplicación)
logger.propagate = False

logger.debug("="*80)
logger.info(f"🚀 >======> Starting from reboot...")
logger.debug("="*80)
# ===============================================================================

# Configurar el saver de Postgres para LangGraph
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME_AGENT', 'checkpointer_db')
DB_USER = os.getenv('DB_USER', 'sisbot_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres_password')
DB_PORT = os.getenv('DB_PORT', '5432')

DB_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Crea la base de datos si no existe (ejecuta una vez)
from sqlalchemy import create_engine
engine = create_engine(DB_URI.rsplit("/", 1)[0] + "/postgres")  # Conecta a db 'postgres' para crear
with engine.connect() as conn:
    conn.execute("COMMIT")
    conn.execute("CREATE DATABASE n8n_checkpoints IF NOT EXISTS")

# =========Importar external_instructions y herramientas del agente ============
try:
    from external_instructions import AGENT_INSTRUCTION, OUTSIDE_BUSINESS_HOURS_MSG
    # Calcular una estimación del peso en tokens (heurística: ~1 token por 4 caracteres)
    if AGENT_INSTRUCTION:
        token_est = max(1, int(len(AGENT_INSTRUCTION) / 4))
        word_count = len(AGENT_INSTRUCTION.split())
    else:
        token_est = 0
        word_count = 0
    logger.info(
        f"✅ AGENT_INSTRUCTION loaded: length={len(AGENT_INSTRUCTION)} | words={word_count} | aprox_tokens={token_est}"
    )
    SESSION_INSTRUCTION = ""  # No se usa actualmente
except Exception as e:
    logger.error(f"❌ Error importando external_instructions: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    AGENT_INSTRUCTION = ""
    SESSION_INSTRUCTION = ""
    OUTSIDE_BUSINESS_HOURS_MSG = "⏰ Hola! Gracias por contactarte con Sisnova. Nuestro horario de atención es de lunes a viernes de 9:00 a 18:00." 

# Log de verificación del AGENT_INSTRUCTION
logger.info(f"🔍 Verificación AGENT_INSTRUCTION: {len(AGENT_INSTRUCTION)} caracteres")
if len(AGENT_INSTRUCTION) == 0:
    logger.error("❌ AGENT_INSTRUCTION está VACÍO - El agente NO funcionará correctamente")
else:
    logger.info(f"✅ AGENT_INSTRUCTION cargado correctamente")
    logger.debug(f"First 200 chars: {AGENT_INSTRUCTION[:200]}")
    
# Importar elementos de booking_tools y agent_control
from booking_tools import (
    extract_lead_info,
    trigger_booking_tool
)
from agent_control import (
    rate_limiter,
    cache_respuestas,
    detector_intenciones
)
from ddos_protection import ddos_protection
from agent_metrics import MetricsDB, metricas_db, MetricaMensaje

# Configuración de webhook de monitoreo
MONITORING_WEBHOOK_URL = os.getenv('MONITORING_WEBHOOK_URL', '').strip()
MONITORING_WEBHOOK_ENABLED = bool(MONITORING_WEBHOOK_URL)
MONITORING_WEBHOOK_INTERVAL_MINUTES = int(os.getenv('MONITORING_WEBHOOK_INTERVAL_MINUTES', '60'))
# Modo de operaciones del sistema de monitoreo: 'push' -> el sistema externo hará POST a nuestro endpoint
# 'pull' -> el agente enviará métricas al webhook externo (default)
MONITORING_WEBHOOK_MODE = os.getenv('MONITORING_WEBHOOK_MODE', 'pull').strip().lower()

if MONITORING_WEBHOOK_ENABLED:
    logger.info(f"✅ Monitoring webhook habilitado: {MONITORING_WEBHOOK_URL}")
    logger.info(f"⏱️  Intervalo de envío automático: cada {MONITORING_WEBHOOK_INTERVAL_MINUTES} minutos")
    logger.info(f"🔀 Modo de monitoreo: {MONITORING_WEBHOOK_MODE}")
else:
    logger.info("⚠️  Monitoring webhook deshabilitado (MONITORING_WEBHOOK_URL no configurado)")

# Cargar conocimiento del negocio desde JSON (sin uso)
CONOCIMIENTO_NEGOCIO = {}
try:
    with open('conocimiento_negocio.json', 'r', encoding='utf-8') as f:
        CONOCIMIENTO_NEGOCIO = json.load(f)
    print("✅ Conocimiento del negocio cargado exitosamente")
except FileNotFoundError:
    print("⚠️  Advertencia: No se encontró conocimiento_negocio.json")
except json.JSONDecodeError as e:
    print(f"⚠️  Error al parsear conocimiento_negocio.json: {e}")
# ===============================================================================


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

# Rich prompts configuration
RICH_PROMPTS_DATE_NOW = os.getenv("RICH_PROMPTS_DATE_NOW", "true").lower() == "true"
RICH_PROMPTS_CLIENT_NAME = os.getenv("RICH_PROMPTS_CLIENT_NAME", "true").lower() == "true"
RICH_PROMPTS_FIRST_MESSAGE = os.getenv("RICH_PROMPTS_FIRST_MESSAGE", "true").lower() == "true"
RICH_PROMPTS_BOOKING_STATUS = os.getenv("RICH_PROMPTS_BOOKING_STATUS", "true").lower() == "true"

# Nombre del modelo global (se puede configurar con MODEL_NAME en .env)

def obtener_model_name_por_provider(provider: Optional[str]) -> str:
    """Devuelve el nombre del modelo a usar según el proveedor `provider`.

    Busca las variables de entorno específicas del proveedor y cae en
    valores por defecto razonables si no se encuentran.
    """
    p = (provider or "").lower()
    if p == 'gemini':
        return os.getenv('GEMINI_MODEL') or os.getenv('MODEL_NAME') or 'gemini-2.5-flash-lite'
    if p == 'anthropic':
        return os.getenv('ANTHROPIC_MODEL') or os.getenv('MODEL_NAME') or 'claude-sonnet-4'
    if p in ('openai', 'gpt'):
        return os.getenv('OPENAI_MODEL') or os.getenv('MODEL_NAME') or 'gpt-3.5-turbo'
    if p in ('huggingface', 'hf'):
        return os.getenv('HF_MODEL') or os.getenv('MODEL_NAME') or 'mistralai/Mistral-7B-Instruct-v0.2'
    if p == 'ollama':
        return os.getenv('OLLAMA_MODEL') or os.getenv('MODEL_NAME') or 'llama2'
    if p in ('local_huggingface', 'hf_local'):
        return os.getenv('HF_LOCAL_MODEL') or os.getenv('MODEL_NAME') or 'mistralai/Mistral-7B-Instruct-v0.2'

    # Fallback genérico: intentar varias variables de entorno
    return os.getenv('MODEL_NAME') or os.getenv('OPENAI_MODEL') or os.getenv('GEMINI_MODEL') or os.getenv('HF_MODEL') or os.getenv('HF_LOCAL_MODEL') or 'gemini-2.5-flash-lite'

# Inicializar MODEL_NAME a partir del proveedor configurado
LLM_MODEL_NAME = obtener_model_name_por_provider(LLM_PROVIDER)

TOOL_BOOKING_ENABLED = os.getenv("TOOL_BOOKING_ENABLED", "true").lower() == "true"

# Límite de mensajes en memoria por conversación
MAX_MESSAGES_PER_CONVERSATION = int(os.getenv("MAX_MESSAGES", "50"))  # Límite de mensajes en memoria

# Configuración para transcripción de audio
TRANSCRIPTION_ENABLED = os.getenv("TRANSCRIPTION_ENABLED", "true").lower() == "true"
TRANSCRIPTION_PROVIDER = os.getenv("TRANSCRIPTION_PROVIDER", "openai")  # opciones: openai, whisper-local

# Rate Limiter configuración
AFH_ENABLED = os.getenv("AFH_ENABLED", "false").lower() == "true"
BUSINESS_HOURS_START = os.getenv("BUSINESS_HOURS_START", "09:00")
BUSINESS_HOURS_END = os.getenv("BUSINESS_HOURS_END", "18:00")
WEEK_DAYS = os.getenv("WEEK_DAYS", "1,2,3,4,5")  # Días de la semana laborables (1=Lunes ... 7=Domingo)
RATE_LIMITER_ENABLED = os.getenv("RATE_LIMITER_ENABLED", "true").lower() == "true"
INTENT_DETECTOR_ENABLED = os.getenv("INTENT_DETECTOR_ENABLED", "true").lower() == "true"
FAQ_CACHE_ENABLED = os.getenv("FAQ_CACHE_ENABLED", "true").lower() == "true"
DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"


# Configuración
app = Flask(__name__)


# Helper para registrar métricas de forma simplificada
def registrar_metrica(user_id: str, mensaje: str, inicio: float, intencion: str = None, 
                      fue_cache: bool = False, error: bool = False, tokens: int = 0):
    """Registra métrica de mensaje de forma simplificada"""
    metricas_db.registrar_metrica(MetricaMensaje(
        timestamp=time.time(),
        user_id=user_id,
        tiempo_procesamiento=time.time() - inicio,
        tokens_usados=tokens,
        fue_cache=fue_cache,
        error=error,
        mensaje_length=len(mensaje),
        intencion=intencion or 'unknown'
    ))


def extraer_tokens_respuesta(respuesta_llm, respuesta, respuesta_texto: Optional[str] = None) -> int:
    """Extrae el número de tokens usados por la respuesta del LLM.

    Intenta extraer desde respuesta_llm.usage o respuesta_llm.llm_output.
    Si no encuentra información explícita, estima tokens por longitud del texto (~4 caracteres por token).
    
    Args:
        respuesta_llm: Objeto de respuesta del LLM (puede tener .usage o .llm_output)
        respuesta: Contenido de la respuesta (puede ser str o dict)
        respuesta_texto: Texto de la respuesta si ya está extraído
    
    Returns:
        int: Número estimado de tokens usados
    """
    tokens_usados = 0
    try:
        if respuesta_llm is not None:
            # 1) Intentar extraer desde .usage
            usage = getattr(respuesta_llm, 'usage', None)
            if usage:
                try:
                    if isinstance(usage, dict):
                        tokens_usados = int(usage.get('total_tokens', 0) or 0)
                    else:
                        tokens_usados = int(getattr(usage, 'total_tokens', 0) or 0)
                except Exception:
                    tokens_usados = 0
            else:
                # 2) Intentar extraer desde .llm_output
                llm_output = getattr(respuesta_llm, 'llm_output', None)
                if llm_output:
                    try:
                        if isinstance(llm_output, dict):
                            tu = llm_output.get('token_usage') or llm_output.get('tokens') or {}
                            if isinstance(tu, dict):
                                tokens_usados = int(tu.get('total_tokens', tu.get('completion_tokens', 0) or 0) or 0)
                        else:
                            if hasattr(llm_output, 'get'):
                                tokens_usados = int(llm_output.get('token_usage', 0) or 0)
                    except Exception:
                        tokens_usados = 0

        # 3) Si la respuesta es un dict con 'usage' o 'llm_output'
        if tokens_usados == 0 and isinstance(respuesta, dict):
            try:
                usage_field = respuesta.get('usage') or (respuesta.get('llm_output') or {}).get('token_usage')
                if isinstance(usage_field, dict):
                    tokens_usados = int(usage_field.get('total_tokens', 0) or 0)
            except Exception:
                tokens_usados = 0
    except Exception:
        tokens_usados = 0

    # Fallback: estimación basada en longitud del texto (~4 chars por token)
    try:
        text = respuesta_texto if respuesta_texto is not None else (respuesta if isinstance(respuesta, str) else str(respuesta))
        if not tokens_usados:
            tokens_usados = max(1, int(len(text) / 4))
    except Exception:
        tokens_usados = 0

    return tokens_usados


import tiktoken

def estimar_tokens(texto_entrada: str, texto_salida: str, modelo: str = None) -> int:
    """
    Estima tokens de entrada y salida para un modelo LLM.
    Funciona para OpenAI, Claude, y otros modelos similares usando tiktoken.
    
    Args:
        texto_entrada: Texto del mensaje de entrada/prompt
        texto_salida: Texto de la respuesta generada
        modelo: Nombre del modelo (usa MODEL_NAME global si no se especifica)
    
    Returns:
        int: Total de tokens estimados (entrada + salida)
    """
    try:
        # Resolver modelo a usar: parámetro > variable global > default
        modelo = modelo or MODEL_NAME or "gpt-3.5-turbo"
        # Intenta usar encoding del modelo específico
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        # Fallback a encoding común (usado por GPT-3.5, GPT-4, etc)
        encoding = tiktoken.get_encoding("cl100k_base")
    
    return len(encoding.encode(texto_entrada)) + len(encoding.encode(texto_salida))

def estimar_costo(input_tokens: int, output_tokens: int, modelo: str) -> float:
    """Estima costo en USD"""
    
    # Precios por 1M tokens (actualizar según pricing)
    precios = {
        'claude-sonnet-4': {'input': 3.0, 'output': 15.0},
        'claude-opus-4': {'input': 15.0, 'output': 75.0},
        'gpt-4': {'input': 30.0, 'output': 60.0},
        'gpt-3.5-turbo': {'input': 0.5, 'output': 1.5},
    }
    
    precio = precios.get(modelo, {'input': 1.0, 'output': 2.0})
    
    costo_input = (input_tokens / 1_000_000) * precio['input']
    costo_output = (output_tokens / 1_000_000) * precio['output']
    
    return costo_input + costo_output


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

            logger.debug("[SND -> EV] Tried %s with candidate=%s status=%s response=%s", endpoint_type, candidate, status, str(text)[:200])

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


@tool
def enviar_mensaje(texto: str) -> str:
    """Envía un mensaje de respuesta al usuario (simulación)."""
    print(f"📱 Enviando mensaje: {texto}")
    return "Mensaje enviado correctamente"


tools = [enviar_mensaje]


def crear_agente():
    """Crea el LLM para el agente"""
    llm = get_llm_model()
    llm_with_tools = llm.bind_tools(tools)
    logger.debug("LLM instance created: %s", type(llm).__name__)
    return llm_with_tools

# Patron factory para obtener el modelo LLM según configuración
def get_llm_model(provider_override=None):
    """Retorna el modelo LLM según la configuración
    
    Args:
        provider_override: Si se especifica, usa este provider en lugar del configurado
    """
    provider = (provider_override or LLM_PROVIDER).lower()
    logger.debug("Configuring LLM provider: %s", provider)
    
    # --- 1. GEMINI --- 
    if provider == "gemini":
        model_name = os.getenv("GEMINI_MODEL", "")
        os.environ["GOOGLE_CLOUD_PROJECT"] = "proyecto-fantasma-para-bypass"
        api_key = GEMINI_API_KEY
        logger.debug("Using Google Gemini model: %s", model_name)
        return ChatGoogleGenerativeAI(           
            model=model_name,
            google_api_key= api_key,
            temperature=0,
            transport="rest",
            convert_system_message_to_human=True, 
            max_tokens=2048,
        )
    
    # --- 2. ANTHROPIC --- 
    elif provider == "anthropic":
        # Asegúrate de tener la variable de entorno: ANTHROPIC_API_KEY
        return ChatAnthropic(
            model="claude-3-5-sonnet-latest", 
            temperature=0,
            max_tokens=4096  # Claude a veces requiere definir el límite de salida
        )

    # --- 3. HUGGING FACE (Inference API) ---    
    # Usamos la API Serverless (o Endpoints dedicados)
    elif provider == "huggingface":
        model_id = os.getenv("HF_MODEL", "")
        logger.debug("Using HuggingFace API for model: %s", model_id)
        # Primero conectamos al Endpoint
        llm = HuggingFaceEndpoint(
            repo_id=model_id, 
            task="text-generation",
            max_new_tokens=512,
            do_sample=False,
        )
        # Luego lo "envolvemos" para que tenga interfaz de Chat
        return ChatHuggingFace(llm=llm)
    
    # --- 4. OPENAI --- 
    elif provider == "openai":
        model_name = os.getenv("OPENAI_MODEL", "")
        logger.debug("Using OpenAI model: %s", model_name)
        return ChatOpenAI(
            model=model_name,
            api_key=OPENAI_API_KEY,
            temperature=0
        )
    
    # --- 5. GROK --- 
    # Grok usa el SDK de OpenAI pero cambiando la URL base
    elif provider == "grok":
        return ChatOpenAI(
            model="grok-2", # O el modelo más reciente
            openai_api_base="https://api.x.ai/v1", # Endpoint de xAI
            openai_api_key=os.environ.get("XAI_API_KEY"),
            temperature=0
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
        logger.info("[RCV <- EV] Received webhook payload: %s", json.dumps(payload)[:500])
        
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
            
            # 🛡️ PROTECCIÓN DDoS: verificar todas las capas de seguridad (si está habilitada)
            if remitente and not from_me and DDOS_PROTECTION_ENABLED and ddos_protection:
                puede_procesar, mensaje_error = ddos_protection.puede_procesar(remitente)
                if not puede_procesar:
                    logger.warning(f"DDoS Protection: bloqueando mensaje de {remitente}: {mensaje_error}")
                    # NO enviar mensaje automático para prevenir loops
                    return jsonify({"status": "blocked", "reason": "rate_limit", "message": mensaje_error}), 429
            
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


def es_horario_laboral():
    ahora = datetime.now()
    # Parsear horas configuradas (formato HH:MM) y días ("1,2,3,4,5")
    try:
        start_hour = int(BUSINESS_HOURS_START.split(':')[0])
    except Exception:
        start_hour = 9
    try:
        end_hour = int(BUSINESS_HOURS_END.split(':')[0])
    except Exception:
        end_hour = 18

    try:
        allowed_weekdays = [int(d.strip()) - 1 for d in WEEK_DAYS.split(',') if d.strip()]
    except Exception:
        allowed_weekdays = [0, 1, 2, 3, 4]

    return (ahora.weekday() in allowed_weekdays) and (start_hour <= ahora.hour < end_hour)


# Herramienta de ejemplo: consulta del clima
def get_weather(city: str):
    """Consulta el clima."""
    return f"Clima en {city}: Soleado, 25°C."


# Registrar herramientas disponibles
tools = [get_weather]


# setup() crea las tablas si no existen.
def setup_database():
    checkpointer.setup()
    logger.info("Database setup completed successfully.")


# Ejecutamos setup una vez al arrancar 
try:
    setup_database()
except Exception as e:
    logger.warning(f"Advertencia de DB: {e}")


# En la vida real, esto vendría de una tabla SQL "clients_config"
CLIENT_PROMPTS = {
    "cliente_abogado": (
        "Eres un experto legal sarcástico. "
        "Usa terminología jurídica compleja para todo. "
        "Si te preguntan por el clima, cita leyes sobre meteorología."
    ),
    "cliente_medico": (
        "Eres un asistente médico empático y suave. "
        "Trata al usuario como 'paciente'. "
        "Si preguntan por el clima, advierte sobre resfriados."
    ),
    "default": "Eres un asistente útil y neutral."
}


def get_system_prompt(prompt_id):
    """Busca la configuración específica del cliente."""
    return CLIENT_PROMPTS.get(prompt_id, CLIENT_PROMPTS["default"])


def procesar_mensaje(user_id: str, mensaje: str, client_name: str = "") -> str:
    """Procesa un mensaje usando el LLM"""
    try:
        inicio = time.time()
        intencion_detectada = None
        fue_cache_usado = False
        hubo_error = False
        
        if AFH_ENABLED:
            if not es_horario_laboral():
                logger.info(f"[AFH] Fuera de horario laboral. user_id={user_id}")
                return OUTSIDE_BUSINESS_HOURS_MSG

        # Obtener memoria del usuario
        # memory = get_memory(user_id)

        # Extraer información de lead 
        extract_lead_info(user_id, mensaje, client_name=client_name)
        
        # Detectar si es el primer mensaje (saludo inicial)
        #is_first_message = len(memory.chat_memory.messages) == 0
        #logger.debug(f"[MEMORY] user_id={user_id} tiene {len(memory.chat_memory.messages)} mensajes en memoria")

        # 1. RATE LIMITING
        if RATE_LIMITER_ENABLED:
            puede, mensaje_error = rate_limiter.puede_procesar(user_id)
            if not puede:
                registrar_metrica(user_id, mensaje, inicio, intencion='rate_limit_exceeded', error=True)
                return mensaje_error
        
        # 2. DETECCIÓN RÁPIDA DE INTENCIÓN
        if INTENT_DETECTOR_ENABLED:
            intencion = detector_intenciones.detectar(mensaje)
            logger.debug(f"[INTENCIÓN RÁPIDA] user_id={user_id} intención={intencion}")
            # Si es saludo o despedida simple de 2 o menos palabras, responder sin LLM
            if intencion == 'saludo' and len(mensaje.split()) <= 2 and is_first_message:
                logger.debug(f"[INTENCIÓN RÁPIDA] Respondiendo saludo rápido para user_id={user_id} nombre={client_name}")
                nombre = client_name
                respuesta = detector_intenciones.respuesta_rapida('saludo', nombre)
                registrar_metrica(user_id, mensaje, inicio, intencion='saludo', fue_cache=True)
                #with memory_lock:  
                #    memory.chat_memory.add_ai_message(respuesta)
                return respuesta
            if intencion == 'despedida' and len(mensaje.split()) <= 2:
                logger.debug(f"[INTENCIÓN RÁPIDA] Respondiendo despedida rápida para user_id={user_id} nombre={client_name}")
                nombre = client_name
                respuesta = detector_intenciones.respuesta_rapida('despedida', nombre)
                registrar_metrica(user_id, mensaje, inicio, intencion='despedida', fue_cache=True)
                return respuesta

        # 3. CACHE DE RESPUESTAS
        if FAQ_CACHE_ENABLED:
            respuesta_cache = cache_respuestas.obtener(mensaje)
            if respuesta_cache:
                logger.debug(f"[CACHE] Respuesta obtenida de cache para user_id={user_id} repuesta={str(respuesta_cache)[:100]}...")
                fue_cache_usado = True
                intencion_detectada = intencion if intencion else 'faq_cache'
                registrar_metrica(user_id, mensaje, inicio, intencion=intencion_detectada, fue_cache=True)
                return respuesta_cache
        
        # Crear sistema de prompt enriquecido
        # system_prompt = AGENT_INSTRUCTION
        # if RICH_PROMPTS_DATE_NOW:
        #     system_prompt += f"\nLa fecha y hora actual es: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."
        # if RICH_PROMPTS_CLIENT_NAME:
        #     system_prompt += f"\nEl nombre del usuario que envía el mensaje es: {client_name}" if client_name else ""
        # if RICH_PROMPTS_BOOKING_STATUS:
        #     booking_status = getattr(memory, 'booking_sent', False)
        #     system_prompt += f"\n\n🚨 ESTADO: booking_sent = {booking_status}"
        # if RICH_PROMPTS_FIRST_MESSAGE:
        #     system_prompt += f"\n\n🚨 ESTADO: is_first_message = {is_first_message}"
        
        #logger.debug(f"[PROMPT] Sistema para user_id={user_id}:\n{system_prompt}")
        
        # A. Recuperamos la "Personalidad" de este cliente
        system_instruction = get_system_prompt("default")
        logger.debug(f"[PROMPT CLIENTE] user_id={user_id} instrucción personalizada:\n{system_instruction}")

        # 3. CREACIÓN DEL AGENTE
        llm = obtener_model_name_por_provider(LLM_PROVIDER)

        # B. Creamos el Agente "Customizado" para esta request
        # Pasamos el 'checkpointer' GLOBAL.
        # El parámetro 'state_modifier' inyecta el System Prompt.
        agent = create_react_agent(
            llm, 
            tools, 
            checkpointer=checkpointer,
            prompt=system_instruction  # <--- PROMPT PERSONALIZADO AQUÍ
        )

        config = {"configurable": {"thread_id": user_id},
        "recursion_limit": 5  # <--- AGREGA ESTO: Falla rápido si entra en bucle
        }
    
        try:
            # LangGraph mezcla el historial guardado en Postgres + el nuevo Prompt del sistema
            response = agent.invoke(
                {"messages": [("human", message)]},
                config=config
            )
        
            respuesta = response["messages"][-1].content
            logger.debug(f"[RESPUESTA DEL AGENTE] user_id={user_id} respuesta={str(respuesta)[:100]}...")
            return respuesta
            # return jsonify({
            #     "response": respuesta,
            #     "thread_id": client_id
            #})

        except Exception as e:
            # Es buena práctica loguear el error real
            print(f"Error en chat: {e}")
            return jsonify({"error": "Error procesando solicitud"}), 500


        # Construir mensajes
        # messages = [SystemMessage(content=system_prompt)]
        # messages.extend(memory.chat_memory.messages)
        # messages.append(HumanMessage(content=mensaje))
        
        # Invocar LLM con sistema de fallback
        try:
            # LLM_MODEL_NAME = obtener_model_name_por_provider(LLM_PROVIDER)
            # respuesta_llm = agente.invoke(messages)
            # respuesta = respuesta_llm.content
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
                    LLM_MODEL_NAME = obtener_model_name_por_provider(fallback_provider)
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
        logger.debug(f"[RESPUESTA DEL LLM]: {str(respuesta)[:80]}...")
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
                    if TOOL_BOOKING_ENABLED:
                        respuesta = trigger_booking_tool(user_id, mensaje, client_name=client_name)
                        mark_tool_as_executed(user_id)
                    else:
                        logger.warning(f"Acción desconocida recibida del LLM: {accion}")
                        respuesta = "Lo siento, no puedo procesar esa solicitud en este momento."

            except json.JSONDecodeError as e:
                logger.warning(f"Error al parsear JSON: {e}")
                pass  # Si no es JSON válido, usar la respuesta como está
        
        # Guardar en memoria el mensaje del usuario (thread-safe)
        #with memory_lock:
        #    memory.chat_memory.add_user_message(mensaje)

        # Si la respuesta es un dict con botón, guardar el texto del contenido
        if isinstance(respuesta, dict) and respuesta.get('type') == 'button':
            respuesta_texto = respuesta['content']['text']
        else:
            respuesta_texto = str(respuesta)

        # Guardar en memoria (thread-safe)
        #with memory_lock:  
        #    memory.chat_memory.add_ai_message(respuesta_texto)
        
        # Truncar memoria si excede el límite
        #with memory_lock:
        #    truncate_memory(memory)
        
        # 5. GUARDAR EN CACHE (solo mensajes cortos y generales)
        #and intencion in ['consulta_precio', 'consulta_horario']:
        if len(mensaje) <= 10:
            logger.debug(f"[CACHE] Guardando en cache el mensaje = {mensaje} length={len(mensaje)}   ")
            cache_respuestas.guardar(mensaje, respuesta)

        # Estimar tokens usando mensaje de entrada y respuesta
        tiempo_total = time.time() - inicio
        texto_respuesta = respuesta_texto if 'respuesta_texto' in locals() else str(respuesta)
        tokens_usados = estimar_tokens(mensaje, texto_respuesta, LLM_MODEL_NAME)
        logger.debug(f"[METRICS] user_id={user_id} tiempo_total={tiempo_total:.2f}s tokens_usados={tokens_usados} model={LLM_MODEL_NAME}")
        registrar_metrica(user_id, mensaje, inicio, intencion=intencion_detectada, fue_cache=fue_cache_usado, tokens=tokens_usados)

        return respuesta
    
    except Exception as e:
        logger.exception(f"Error procesando mensaje: {e}")
        # Registrar métrica de error
        try:
            registrar_metrica(user_id, mensaje, inicio, intencion='exception', error=True)
        except Exception:
            pass  # No fallar si el registro de métrica falla
        return "Lo siento, ocurrió un error al procesar tu mensaje. Por favor intenta de nuevo."

# Endpoints Flask
@app.route('/stats', methods=['GET'])
def obtener_estadisticas():
    """Endpoint para estadísticas generales"""
    # Soporta dos modos:
    # - Por horas: ?horas=24 (default)
    # - Por rango ISO: ?start=2026-01-01T00:00:00&end=2026-01-31T23:59:59
    start = request.args.get('start')
    end = request.args.get('end')
    if (start and not end) or (end and not start):
        return jsonify({"error": "Proporcione ambos parámetros 'start' y 'end' o ninguno"}), 400

    try:
        if start and end:
            stats = metricas_db.obtener_estadisticas_por_rango(start, end)
        else:
            horas = request.args.get('horas', 24, type=int)
            stats = metricas_db.obtener_estadisticas_generales(horas)
        return jsonify(stats)
    except Exception as e:
        logger.exception("Error obteniendo estadísticas generales")
        return jsonify({"error": str(e)}), 500

@app.route('/stats/hourly', methods=['GET'])
def obtener_estadisticas_horarias():
    """Endpoint para métricas por hora"""
    # Soporta dos modos:
    # - Por horas: ?horas=24 (default)
    # - Por rango ISO: ?start=2026-01-01T00:00:00&end=2026-01-31T23:59:59
    start = request.args.get('start')
    end = request.args.get('end')
    if (start and not end) or (end and not start):
        return jsonify({"error": "Proporcione ambos parámetros 'start' y 'end' o ninguno"}), 400

    try:
        if start and end:
            stats = metricas_db.obtener_metricas_por_hora_rango(start, end)
        else:
            horas = request.args.get('horas', 24, type=int)
            stats = metricas_db.obtener_metricas_por_hora(horas)
        return jsonify(stats)
    except Exception as e:
        logger.exception("Error obteniendo métricas por hora")
        return jsonify({"error": str(e)}), 500

@app.route('/stats/top-users', methods=['GET'])
def obtener_top_usuarios_endpoint():
    """Endpoint para usuarios más activos"""
    limit = request.args.get('limit', 10, type=int)
    try:
        top = metricas_db.obtener_top_usuarios(limit)
        return jsonify(top)
    except Exception as e:
        logger.exception("Error obteniendo top usuarios")
        return jsonify({"error": str(e)}), 500

@app.route('/admin/cleanup', methods=['POST'])
def limpiar_metricas():
    """Endpoint para limpiar métricas antiguas (requiere auth)"""
    # TODO: Agregar autenticación
    dias = request.json.get('dias', 30)
    try:
        eliminados = metricas_db.limpiar_datos_antiguos(dias)
        return jsonify({"eliminados": eliminados, "dias": dias})
    except Exception as e:
        logger.exception("Error limpiando métricas antiguas")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/cleanup/all', methods=['POST'])
def limpiar_todas_metricas_endpoint():
    """Endpoint administrativo que borra TODAS las métricas (detalle y agregados).

    Nota: Esta acción es destructiva y debe protegerse en producción.
    """
    # TODO: Agregar autenticación/ACL en entornos productivos
    try:
        resultado = metricas_db.borrar_todas_metricas()
        return jsonify({"deleted": resultado}), 200
    except Exception as e:
        logger.exception("Error borrando todas las métricas")
        return jsonify({"error": str(e)}), 500


@app.route('/admin/metrics/flush', methods=['POST'])
def admin_metrics_flush():
    """Endpoint administrativo para forzar el flush del buffer de métricas en memoria."""
    # TODO: Agregar autenticación/ACL en entornos productivos
    try:
        resultado = metricas_db.forzar_flush()
        return jsonify(resultado), 200
    except Exception as e:
        logger.exception("Error forzando flush de métricas")
        return jsonify({"error": str(e)}), 500


from webhooks import webhooks_bp
app.register_blueprint(webhooks_bp)


@app.route("/health", methods=['GET'])
def health():
    """Endpoint de salud"""
    return {"status": "ok"}


@app.route("/ddos-stats", methods=['GET'])
def ddos_stats():
    """Endpoint de estadísticas de protección DDoS"""
    if not DDOS_PROTECTION_ENABLED or not ddos_protection:
        return jsonify({"enabled": False, "message": "DDoS protection disabled"})
    return jsonify({"enabled": True, "stats": ddos_protection.get_stats()})


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


# --- 3. LIMPIEZA DEL POOL DE POSTGRESAL CERRAR ---
# Esto asegura que las conexiones se cierren bien si apagas el server
import atexit
atexit.register(connection_pool.close)


if __name__ == '__main__':

    # Servidor
    print(f"\n🚀 SERVIDOR:")
    print(f"  🌐 Host: 0.0.0.0")
    print(f"  🔌 Puerto: 5000")
    print(f"  📋 Endpoints disponibles:")
    print(f"     POST /webhook - Recibe mensajes de WhatsApp")
    print(f"     GET  /health - Estado del servicio")
    print(f"     GET  /metrics - Métricas del sistema")
    print(f"     GET  /ddos-stats - Estadísticas de protección DDoS")
    print(f"     GET  /memory - Lista de conversaciones activas")
    print(f"     GET  /memory/{{user_id}} - Detalles de conversación")
    print("🔄 Modo concurrente: 4 workers activos")

    print("\n" + "="*60)
    print("✅ Inicialización completada - Esperando mensajes...")
    print("="*60 + "\n")

    # Iniciar scheduler de webhook automático (delegado al módulo webhooks)
    from webhooks import iniciar_scheduler_webhook
    scheduler = iniciar_scheduler_webhook()

    try:
        # Ejecutar Flask con threading habilitado
        app.run(
            host='0.0.0.0',
            port=5000,
            threaded=True,  # Importante: habilitar threading
            debug=True    # Cambiar a False en producción
        )
    finally:
        # Detener scheduler al cerrar la aplicación
        if scheduler:
            scheduler.shutdown()
            logger.info("🛑 Scheduler detenido")
