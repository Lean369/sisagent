import os
import time
from typing import Annotated, TypedDict, List, Optional
import operator
from dotenv import load_dotenv
from loguru import logger
import sys
import json
import threading
import base64
from datetime import datetime

# --- Imports de IA ---
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import ToolMessage

# --- Imports de Grafo y DB ---
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

# --- Imports de Herramientas ---
from cliente_config import ClienteConfig
from utilities import obtener_configuraciones, gestionar_expiracion_sesion
from tools_crm import trigger_booking_tool, consultar_stock, ver_menu
from tools_hitl import solicitar_atencion_humana
from tools_rag import consultar_base_conocimiento
from tools_n8n import invoke_n8n
from tools_calendar import completar_auth_calendar, agendar_cita_calendar, consultar_citas_calendar
from analytics import registrar_evento

# Cargar .env
load_dotenv(override=True)

# Configurar el saver de Postgres para LangGraph
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME_AGENT', 'checkpointer_db')
DB_USER = os.getenv('DB_USER', 'sisbot_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres_password')
DB_PORT = os.getenv('DB_PORT', '5432')
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_openai_key")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "your_google_key")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "your_groq_key")

logger.info("🚀 Iniciando la Agente AI...")


# ==============================================================================
# REGISTRO DE HERRAMIENTAS
# ==============================================================================
# Mapeo de nombres de herramientas a objetos tool
TOOLS_REGISTRY = {
    "consultar_stock": consultar_stock,
    "ver_menu": ver_menu,
    "trigger_booking_tool": trigger_booking_tool,
    "solicitar_atencion_humana": solicitar_atencion_humana,
    "consultar_base_conocimiento": consultar_base_conocimiento,
    "invoke_n8n": invoke_n8n,
    "agendar_cita_calendar": agendar_cita_calendar,
    "consultar_citas_calendar": consultar_citas_calendar
}

# ==============================================================================
# 1. SETUP GLOBAL (MODELOS Y DB)
# ==============================================================================
# Patron factory para obtener el modelo LLM según configuración
def get_llm_model(provider_override=None):
    """Retorna el modelo LLM según la configuración
   
    Args:
        provider_override: Si se especifica, usa este provider en lugar del configurado
    """
    try:
        provider = provider_override or os.getenv("LLM_PROVIDER", "google").lower()
        
        if provider == "openai":
            OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            logger.info("Usando modelo OpenAI:" + OPENAI_MODEL)
            return ChatOpenAI(model=OPENAI_MODEL, temperature=0, max_retries=2)
        
        elif provider == "groq":
            GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
            logger.info("Usando modelo Groq " + GROQ_MODEL)
            return ChatGroq(model=GROQ_MODEL, temperature=0, max_retries=2)

        elif provider == "gemini":
            GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
            logger.info("Usando modelo Google Gemini " + GEMINI_MODEL)
            return ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=0, max_retries=2)

        else:
            raise ValueError(f"Proveedor LLM desconocido: {provider}")

    except Exception as e:
        logger.exception(f"🔴 Error al inicializar el modelo LLM ({provider}): {e}")


LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
LLM_PROVIDER_FALLBACK = os.getenv("LLM_PROVIDER_FALLBACK", "openai").lower()

llm_primary = get_llm_model(LLM_PROVIDER)
llm_backup = get_llm_model(LLM_PROVIDER_FALLBACK)

logger.info(f"LLM Provider configurado: {LLM_PROVIDER}")
logger.info(f"LLM Provider fallback: {LLM_PROVIDER_FALLBACK}")

DB_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Configuración del pool de conexiones a Postgres para el checkpointer de LangGraph
# Soporta hasta 20 conexiones concurrentes (20 usuarios simultáneos). Ajustar según necesidades y recursos.
pool = ConnectionPool(conninfo=DB_URI, min_size=1, max_size=20, kwargs={"autocommit": True})

with pool.connection() as conn:
    checkpointer_temp = PostgresSaver(conn)
    checkpointer_temp.setup()


def _lanzar_metricas_background(pool, response_msg, thread_id, latency_ms, isLlmPrimary=True):
    """Lanza el registro de métricas en un hilo independiente para no bloquear."""
    hilo = threading.Thread(
        target=registrar_evento,
        args=(pool, response_msg, thread_id, latency_ms, isLlmPrimary),
        daemon=False # False asegura que se guarde aunque el request principal termine
    )
    hilo.start()

# ==============================================================================
# 2. DEFINICIÓN DEL GRAFO MULTI-TENANT
# ==============================================================================
class State(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


# Prompting Dinámico "Zero-Storage". Se inyecta el SystemMessage al vuelo en la variable mensajes_entrada.
# Recibe el estado anterior de la conversación (state) y la configuración del negocio (config) para decidir qué prompt, herramientas utilizar. Puede devolver un estado nuevo / actualizado.
# NO lo agrego al state para ahorrar tokens en la DB.
# Si se cambia la configuración del negocio, se aplica inmediatamente.
def nodo_chatbot(state: State, config: RunnableConfig):
    # 1. Recuperar Configuración desde parámetro config (que viene de app.py)
    configurable = config.get("configurable", {})

    business_id = configurable.get("business_id", "default")
    nombre_cliente = configurable.get("client_name", "Cliente")
    thread_id = configurable.get("thread_id", "unknown_thread")
    
    # Instanciamos el objeto
    info_negocio = ClienteConfig(business_id)

    #info_negocio = config_actual.get(business_id)
    if not info_negocio:
        logger.error(f"🔴 No se encontró configuración para business_id: {business_id}.")
        return {"messages": [AIMessage(content="No se encontró la configuración del negocio. Por favor, contacta al soporte.")]}
    
    logger.info(f"💼 Negocio: {business_id} ({info_negocio.nombre}) | Thread: {thread_id}")

    # 3. Verificar horario laboral
    en_horario, mensaje_fuera_horario = info_negocio.es_horario_laboral()
    if not en_horario:
        logger.info(f"⏰ Fuera de horario laboral para {business_id}. Respondiendo con mensaje de fuera de servicio.")
        return {"messages": [AIMessage(content=mensaje_fuera_horario)]}

    if not info_negocio.enabled:
        logger.info(f"⏰ Negocio {business_id} deshabilitado. Respondiendo con mensaje de fuera de servicio.")
        return {"messages": [AIMessage(content="El negocio está temporalmente fuera de servicio. Disculpa las molestias.")]}
    
    # ---------------------HITL------------------------------------
    mensajes_historia = state["messages"]
    bot_pausado = False
    
    # Escaneamos hacia atrás para ver el estado actual
    for msg in reversed(mensajes_historia):
        # 1. Si encontramos una señal de reactivación, el bot está ACTIVO
        if "BOT_REACTIVADO" in str(msg.content):
            bot_pausado = False
            break
            
        # 2. Si encontramos la señal de derivación, el bot está PAUSADO
        # Buscamos el string exacto que retorna tu tool 'solicitar_atencion_humana'
        if isinstance(msg, ToolMessage) and "DERIVACION_EXITOSA_SILENCIO" in str(msg.content):
            bot_pausado = True
            break
    
    # Retornamos una lista vacía o un mensaje nulo para detener el grafo sin romper la ejecución. 
    if bot_pausado:
        logger.warning(f"⛔ Bot pausado para {business_id} (Derivación activa). Ignorando mensaje.")
        return {"messages": []} 
    # ---------------------------------------------------------

    # 4. Convertir nombres de tools a objetos tool
    tools_nombres = info_negocio.tools_habilitadas if info_negocio else []
    mis_tools = []
    for tool_nombre in tools_nombres:
        if isinstance(tool_nombre, str) and tool_nombre in TOOLS_REGISTRY:
            tool_obj = TOOLS_REGISTRY[tool_nombre]
            # Validar que la herramienta tenga un nombre
            if not hasattr(tool_obj, 'name') or not tool_obj.name:
                logger.error(f"🔴 Herramienta '{tool_nombre}' no tiene atributo 'name' válido")
                continue
            mis_tools.append(tool_obj)
        elif not isinstance(tool_nombre, str):
            # Validar que el objeto tenga nombre
            if hasattr(tool_nombre, 'name') and tool_nombre.name:
                mis_tools.append(tool_nombre)
            else:
                logger.error(f"🔴 Objeto tool sin nombre válido: {type(tool_nombre)}") 

    # 5. Preparar el prompt del sistema dinámico con la configuración del negocio
    # Si solo hay 1 mensaje, significa que la charla acaba de empezar
    if len(mensajes_historia) == 1:
        logger.info("👋 Detectada nueva conversación.")

    prompt_sistema = info_negocio.system_prompt if info_negocio else "Eres un asistente útil."
    if isinstance(prompt_sistema, list):
        prompt_sistema_unido = "\n".join(prompt_sistema)  # Une los strings con saltos de línea
    else:
        prompt_sistema_unido = prompt_sistema

    CLIENT_NAME_IN_CONTEXT = os.getenv("CLIENT_NAME_IN_CONTEXT", "false").lower()
    if len(nombre_cliente) > 3 and CLIENT_NAME_IN_CONTEXT == "true":
        prompt_final = (
        f"{prompt_sistema_unido}\n"
        f"DATOS DE CONTEXTO:\n"
        f"- Estás hablando con: {nombre_cliente}.\n"
    )
    else:
        prompt_final = prompt_sistema_unido

    INTERNAL_CLOCK_IN_CONTEXT = os.getenv("INTERNAL_CLOCK_IN_CONTEXT", "false").lower()
    if INTERNAL_CLOCK_IN_CONTEXT == "true":
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dia_semana = datetime.now().strftime("%A") # Ej: Monday, Tuesday.
        prompt_final = (
        f"{prompt_final}\n"
        f"RELOJ INTERNO: Hoy es {dia_semana}, {ahora}.\n"
    )

    #logger.debug(f"📝 Prompt final para {business_id}:\n{prompt_final}")

    # 5. VINCULACIÓN DINÁMICA (Aquí ocurre la magia ✨)
    if mis_tools:
        # Creamos una instancia temporal del LLM que solo conoce estas tools
        try:
            llm_actual = llm_primary.bind_tools(mis_tools)
            llm_backup_actual = llm_backup.bind_tools(mis_tools)
            logger.info(f"🔧 Vinculadas {len(mis_tools)} herramientas para {business_id}")
            for tool in mis_tools:
                logger.info(f"Tool vinculada: {tool.name}")
        except Exception as e:
            logger.error(f"🔴 Error vinculando herramientas para {business_id}: {e}")
            logger.error(f"Herramientas problemáticas: {[getattr(t, 'name', str(t)) for t in mis_tools]}")
            raise
    else:
        # Si no hay tools, usamos el modelo base sin capacidades extra
        llm_actual = llm_primary
        llm_backup_actual = llm_backup
        logger.info(f"ℹ️ No hay herramientas vinculadas para {business_id}")
    
    # 6. Construir mensajes (System + Historia)
    mensajes_entrada = [SystemMessage(content=prompt_final)] + state["messages"]

    logger.info(f"Ejecutando LLM para thread: {thread_id}")
    # ⏱️ INICIO CRONÓMETRO (Solo para el LLM)
    start_time = time.time()
    
    try:
        # 7. Invocación al LLM con manejo de errores interno (fallback a modelo backup)
        response_msg = llm_actual.invoke(mensajes_entrada)
        
        # ⏱️ CÁLCULO DE TIEMPO
        latency_ms = int((time.time() - start_time) * 1000)

        logger.success(f"Respuesta de llm_actual para {thread_id}: {response_msg.content[:200]}...")

        _lanzar_metricas_background(pool, response_msg, thread_id, latency_ms, isLlmPrimary=True)

        
        # 6. RETORNO CORRECTO: Debe ser un dict con la clave 'messages'
        # LangGraph tomará esto y hará un append a la lista de mensajes en la DB.
        return {"messages": [response_msg]}

    except Exception as e:
        start_time = time.time()
        logger.warning(f"⚠️ Fallo LLM primario para {thread_id} ({e}). Cambiando a respaldo...")
        try:
            response_msg = llm_backup_actual.invoke(mensajes_entrada)

            # ⏱️ CÁLCULO DE TIEMPO
            latency_ms = int((time.time() - start_time) * 1000)

            logger.success(f"Respuesta de llm_backup_actual para {thread_id}: {response_msg.content[:200]}...")

            _lanzar_metricas_background(pool, response_msg, thread_id, latency_ms, isLlmPrimary=False)
                
            return {"messages": [response_msg]}

        except Exception as e2:
            logger.error(f"🔺 Fallo total para {thread_id}: {e2}")
            # Devolvemos un mensaje de error encapsulado en AIMessage para no romper el flujo
            return {"messages": [AIMessage(content="Lo siento, tengo un problema técnico temporal.")]}


# ==============================================================================
# 3. DEFINICIÓN DE HERRAMIENTAS Y NODOS DE EJECUCIÓN
# ==============================================================================

def obtener_todas_las_tools() -> dict:
    """
    Retorna todas las herramientas únicas definidas en TOOLS_REGISTRY.
    """
    try:
        # Recolectar todos los nombres de tools_habilitadas de cada negocio
        avalilable_tools = set()
        config_actual = obtener_configuraciones() 
        for negocio_conf in config_actual.values():
            if not isinstance(negocio_conf, dict):
                continue
            tools_list = negocio_conf.get("tools_habilitadas", [])
            if isinstance(tools_list, list):
                for t in tools_list:
                    if isinstance(t, str):
                        avalilable_tools.add(t)

        avalilable_tools = sorted(list(avalilable_tools))
        logger.info(f"Herramientas configuradas en JSON (nombres únicos): {avalilable_tools}")

        if avalilable_tools:
            herramientas_filtradas = []
            for tool_nombre in avalilable_tools:
                if tool_nombre in TOOLS_REGISTRY:
                    herramientas_filtradas.append(TOOLS_REGISTRY[tool_nombre])

            logger.info(f"Total de herramientas únicas cargadas desde JSON: {len(herramientas_filtradas)}")
            for tool in herramientas_filtradas:
                logger.info(f"Tool registered from JSON: {tool.name}")
            return herramientas_filtradas
        else:
            logger.warning("⚠️ No hay herramientas específicas en JSON 'config_negocios.json'")
            return []    
    
    except Exception as e:
        logger.exception("🔴 Error cargando herramientas desde TOOLS_REGISTRY")
        return []


tool_node = ToolNode(obtener_todas_las_tools(), handle_tool_errors=True)

# Construcción del grafo. Se define la estructura del grafo una vez y es inmutable durante la ejecución.
workflow_builder = StateGraph(State)

workflow_builder.add_node("chatbot", nodo_chatbot)
workflow_builder.add_node("tools", tool_node) # Nodo ´tool_node´ es genérico de ejecución

workflow_builder.set_entry_point("chatbot")

# Lógica condicional (creación de aristas): Si el chatbot pide tool -> va a 'tools', si no -> END
workflow_builder.add_conditional_edges(
    "chatbot",
    tools_condition
)

workflow_builder.add_edge("tools", "chatbot") # Volver al chatbot con el resultado

# ==============================================================================
# 4. FUNCIÓN DE PROCESAMIENTO con LLM y Memoria Separada
# ==============================================================================
def procesar_mensaje(mensaje_usuario: str, config: dict) -> dict:
    try:
        if not mensaje_usuario: return {"status": "ERROR", "response": "Mensaje vacío"}

        conf_data = config.get('configurable', {})
        thread_id = conf_data.get('thread_id', 'unknown')
        business_id = conf_data.get('business_id', 'unknown')
        ttl_minutos = conf_data.get('ttl_minutos', 60)

        logger.info(f"Procesando msg. thread={thread_id}, business={business_id}, ttl_sesion={ttl_minutos}min")

        # 🧹 --- NUEVA LÓGICA DE LIMPIEZA ---
        # Si la sesión expiró, esto borra la DB y el bot arranca de cero.
        sesion_reseteada = gestionar_expiracion_sesion(pool, thread_id, ttl_minutos)
        
        if sesion_reseteada:
            logger.info(f"🧹 Sesión reiniciada para {thread_id} por inactividad.")

        with pool.connection() as conn:
            checkpointer = PostgresSaver(conn)
            app = workflow_builder.compile(checkpointer=checkpointer)        
            
            inputs = {"messages": [HumanMessage(content=mensaje_usuario)]}
            
            # Ejecución
            result = app.invoke(inputs, config=config)

            mensajes = result.get("messages", [])

            # 1. Validación básica de mensajes vacíos
            if not mensajes: 
                return {"status": "PAUSED", "response": ""}

            ultimo_mensaje = mensajes[-1]
            contenido_final = ultimo_mensaje.content

            # --- CORRECCIÓN AQUÍ ---
            # En lugar de mirar solo el último mensaje, miramos si la señal apareció 
            # en CUALQUIER parte de la ejecución reciente (en la Tool o en el AI).
            
            se_debe_silenciar = False
            
            for msg in reversed(mensajes):
                contenido = str(msg.content)
                
                # 1. Si encontramos la señal de REACTIVACIÓN primero, el bot está VIVO.
                # Rompemos el ciclo inmediatamente porque lo que pasó antes ya no importa.
                if "BOT_REACTIVADO" in contenido:
                    se_debe_silenciar = False
                    logger.info(f"🟢 Señal de reactivación encontrada para {thread_id}. Permitiendo respuesta.")
                    break 
                
                # 2. Si encontramos la señal de SILENCIO primero, el bot sigue PAUSADO.
                if "DERIVACION_EXITOSA_SILENCIO" in contenido:
                    se_debe_silenciar = True
                    logger.warning(f"⛔ Señal de silencio encontrada (y es la más reciente) para {thread_id}.")
                    break

            if se_debe_silenciar:
                return {"status": "PAUSED", "response": ""}
            
            # 4. Retorno normal
            return {
                "status": "COMPLETED",
                "response": contenido_final
            }

    except Exception as e:
        logger.exception(f"🔴 Error crítico en procesar_mensaje: {e}")
        return {
            "status": "ERROR",
            "response": "Error interno. Por favor, intenta nuevamente más tarde."
        }


# ==============================================================================
# 5. TRANSCRIPCIÓN DE AUDIO (Evolution Baileys WhatsApp)
# ==============================================================================
def transcribir_audio(audio_buffer: bytes, thread_id, audio_format: str = "ogg") -> Optional[str]:
    """
    Transcribe un mensaje de audio a texto usando OpenAI
    
    Args:
        audio_buffer: Bytes del archivo de audio
        audio_format: Formato del audio (ogg, mp4, mp3, wav, etc.)
    
    Returns:
        Texto transcrito o None si hay error
    """
    try:
        import io
        from pydub import AudioSegment
        
        TRANSCRIPTION_ENABLED = os.getenv("TRANSCRIPTION_ENABLED", "true").lower() == "true"
        TRANSCRIPTION_PROVIDER = os.getenv("TRANSCRIPTION_PROVIDER", "openai")
        OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

        if not TRANSCRIPTION_ENABLED:
            logger.warning("⚠️ [AUDIO] Transcripción deshabilitada")
            return None
        
        # Verificar duración del audio
        audio = AudioSegment.from_file(io.BytesIO(audio_buffer), format=audio_format)
        duration_seconds = len(audio) / 1000.0  # pydub da duración en ms
        duration_minutes = duration_seconds / 60.0
        logger.info(f"[AUDIO] Duración del audio: {duration_seconds:.2f} segundos")
        MAX_DURATION_VOICE_SEC = int(os.getenv("MAX_DURATION_VOICE_SEC", 60))  # Límite configurable en segundos

        if duration_seconds > MAX_DURATION_VOICE_SEC:
            return f"¡Hola! La nota de voz es muy larga (más de {MAX_DURATION_VOICE_SEC // 60} minutos). Por favor, envíala en partes más cortas o resumí lo principal. 😊 Gracias!"
        
        logger.info(f"[AUDIO] Iniciando transcripción de audio ({len(audio_buffer)} bytes)")
        
        # Transcribir según el proveedor
        transcription = None
        TRANSCRIPTION_MODEL = os.getenv("TRANSCRIPTION_MODEL", "whisper-1")
        
        if TRANSCRIPTION_PROVIDER == "openai":
            logger.debug(f"[AUDIO] Usando: {TRANSCRIPTION_MODEL} de OpenAI para transcripción")
            from openai import OpenAI
            
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            
            # Crear un BytesIO buffer con el audio
            ext_map = {"ogg": "ogg", "mp4": "mp4", "m4a": "mp4", "mp3": "mp3", "wav": "wav", "aac": "aac", "webm": "webm"}
            ext = ext_map.get(audio_format, audio_format)
            buffer = io.BytesIO(audio_buffer)
            buffer.name = f"audio.{ext}"  # OpenAI necesita un nombre con extensión
            start_time = time.time()

            response = openai_client.audio.transcriptions.create(
                model=TRANSCRIPTION_MODEL,
                file=buffer,
                language="es",          # Español
                response_format="text", # Texto plano
                temperature=0.0         # Transcripciones deterministas
            )
            # ⏱️ CÁLCULO DE TIEMPO
            latency_ms = int((time.time() - start_time) * 1000)
            transcription_metrics = {
                "response_metadata": {
                    "model_name": TRANSCRIPTION_MODEL,
                    "provider": "openai"
                },
                "usage_transcription": {
                    "duration_minutes": duration_minutes
                }
            }
            _lanzar_metricas_background(pool, transcription_metrics, thread_id, latency_ms, isLlmPrimary=True)

            transcription = response if isinstance(response, str) else response.text
        
        elif TRANSCRIPTION_PROVIDER == "whisper-local":
            logger.debug("[AUDIO] Usando Whisper local")
            import whisper
            import tempfile
            
            # Guardar temporalmente para Whisper local
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as temp_audio:
                temp_audio.write(audio_buffer)
                temp_audio_path = temp_audio.name
            
            try:
                model = whisper.load_model("base")
                result = model.transcribe(temp_audio_path, language="es")
                transcription = result["text"]
            finally:
                # Limpiar archivo temporal
                try:
                    os.unlink(temp_audio_path)
                except:
                    pass
        
        if transcription:
            logger.info(f"[AUDIO] Transcripción exitosa: {transcription[:100].replace('\n', ' ')}")
            return transcription
        else:
            logger.error("❌ [AUDIO] No se obtuvo transcripción")
            return None
            
    except Exception as e:
        logger.error(f"🔴 [AUDIO] Error transcribiendo audio: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def analizar_imagen_con_ai(image_buffer: bytes, thread_id: str, caption: str = None) -> Optional[str]:
    """
    Analiza una imagen usando un modelo multimodal (GPT-4 Vision, Gemini, etc.)
    
    Args:
        image_buffer: Bytes de la imagen
        thread_id: ID del thread para métricas
        caption: Texto que acompaña la imagen (opcional)
    
    Returns:
        Descripción/análisis de la imagen o None si hay error
    """
    try:
        import base64
        
        IMAGE_ANALYSIS_ENABLED = os.getenv("IMAGE_ANALYSIS_ENABLED", "true").lower() == "true"
        IMAGE_ANALYSIS_PROVIDER = os.getenv("IMAGE_ANALYSIS_PROVIDER", "openai")  # openai o gemini
        
        if not IMAGE_ANALYSIS_ENABLED:
            logger.warning("⚠️ [IMAGE] Análisis de imágenes deshabilitado")
            return None
        
        logger.info(f"[IMAGE] Iniciando análisis de imagen ({len(image_buffer)} bytes)")
        
        # Convertir imagen a base64
        image_base64 = base64.b64encode(image_buffer).decode('utf-8')
        
        # Crear el prompt
        prompt_text = """Analiza esta imagen y extrae TODA la información visible relacionada con citas, eventos o agendas.

Busca e identifica:
- Nombre completo de la persona
- Fecha (día, mes, año)
- Hora exacta (formato 24h si es posible)
- Motivo, tipo de cita o descripción del evento

Si encuentras esta información, preséntala de forma clara y estructurada.
Si NO hay información de citas en la imagen, describe lo que ves."""
        
        if caption:
            prompt_text = f"""El usuario envió esta imagen con el texto: '{caption}'.

Analiza la imagen y extrae TODA la información relacionada con citas o eventos:
- Nombre completo
- Fecha (formato: día/mes/año)
- Hora (formato 24h preferentemente)
- Motivo o descripción

Responde en relación al texto del usuario y estructura la información claramente."""
        
        start_time = time.time()
        
        if IMAGE_ANALYSIS_PROVIDER == "openai":
            logger.debug("[IMAGE] Usando OpenAI GPT-4o Vision")
            from openai import OpenAI
            from langchain_core.messages import HumanMessage
            
            OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
            openai_client = OpenAI(api_key=OPENAI_API_KEY)
            
            # Usar GPT-4o o GPT-4o-mini que soportan visión
            model = os.getenv("VISION_MODEL", "gpt-4o-mini")
            
            response = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_base64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=500,
                temperature=0.0
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            analysis = response.choices[0].message.content
            
            logger.info(f"📊 [IMAGE] Análisis completado en {latency_ms}ms")
            _lanzar_metricas_background(pool, response, thread_id, latency_ms, isLlmPrimary=True)
            
        elif IMAGE_ANALYSIS_PROVIDER == "gemini":
            logger.debug("[IMAGE] Usando Google Gemini Vision")
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_core.messages import HumanMessage
            
            model = os.getenv("VISION_MODEL", "gemini-2.0-flash-exp")
            llm = ChatGoogleGenerativeAI(model=model, temperature=0)
            
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{image_base64}"
                    }
                ]
            )
            
            response = llm.invoke([message])
            latency_ms = int((time.time() - start_time) * 1000)
            analysis = response.content
            
            logger.info(f"📊 [IMAGE] Análisis completado en {latency_ms}ms")
            _lanzar_metricas_background(pool, response, thread_id, latency_ms, isLlmPrimary=True)
        
        else:
            logger.error(f"❌ [IMAGE] Proveedor no soportado: {IMAGE_ANALYSIS_PROVIDER}")
            return None
        
        if analysis:
            logger.info(f"[IMAGE] Análisis exitoso: {analysis[:100].replace(chr(10), ' ')}...")
            return analysis
        else:
            logger.error("❌ [IMAGE] No se obtuvo análisis")
            return None
            
    except Exception as e:
        logger.error(f"🔴 [IMAGE] Error analizando imagen: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None