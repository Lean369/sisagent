import os
from typing import Annotated, TypedDict, List
import operator
from dotenv import load_dotenv
from loguru import logger
import sys
import json

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
from agente_metricas import loguear_consumo_tokens
from crm_tools import (
    trigger_booking_tool,
    consultar_stock,
    ver_menu
)

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

# Configuración única de Logger con Loguru
# Limpiar configuración por defecto para evitar duplicados
# El ID 0 es el default. Si lo quitamos, len() será 0 al inicio.
try:
    # Intentamos remover el default solo si es la primera vez
    logger.remove(0) 
except ValueError:
    pass # Ya estaba removido

# 1. Salida en Consola (Colorida y legible)
logger.add(
    sys.stderr,
    level="DEBUG",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

# 2. Archivo con ROTACIÓN (10 MB) y COMPRESIÓN (zip)
# Esto guardará en la carpeta 'logs', rotará al llegar a 10MB y borrará logs de más de 20 días.
logger.add(
    "logs/sisagent_verbose.log",
    rotation="10 MB",
    retention="20 days",
    compression="zip",
    level="DEBUG",
    encoding="utf-8"
)

logger.info("🚀 Iniciando la Agente AI...")

# ==============================================================================
# 0. CARGAR CONFIGURACIONES DESDE JSON
# ==============================================================================

def cargar_configuraciones():
    """Carga las configuraciones de negocios desde config_negocios.json"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config_negocios.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            configuraciones = json.load(f)
        logger.info(f"✅ Configuraciones cargadas: {len(configuraciones)} negocios")
        return configuraciones
    except Exception as e:
        logger.exception(f"🔴 Error cargando config_negocios.json: {e}")
        return {}

CONFIGURACIONES = cargar_configuraciones()


# ==============================================================================
# REGISTRO DE HERRAMIENTAS
# ==============================================================================
# Mapeo de nombres de herramientas a objetos tool
TOOLS_REGISTRY = {
    "consultar_stock": consultar_stock,
    "ver_menu": ver_menu,
    "trigger_booking_tool": trigger_booking_tool
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

pool = ConnectionPool(conninfo=DB_URI, min_size=1, max_size=10, kwargs={"autocommit": True})

with pool.connection() as conn:
    checkpointer_temp = PostgresSaver(conn)
    checkpointer_temp.setup()

# ==============================================================================
# 2. DEFINICIÓN DEL GRAFO MULTI-TENANT
# ==============================================================================
class State(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


# Prompting Dinámico "Zero-Storage". Se inyecta el SystemMessage al vuelo en la variable mensajes_entrada.
# NO lo agrego al state para ahorrar tokens en la DB.
# Si se cambia la configuración del negocio, se aplica inmediatamente.
def nodo_chatbot(state: State, config: RunnableConfig):
    # 1. Recuperar Configuración
    configurable = config.get("configurable", {})
    business_id = configurable.get("business_id", "default")
    nombre_cliente = configurable.get("client_name", "Cliente")
    thread_id = configurable.get("thread_id", "unknown_thread")
    
    # 2. Setup del Prompt y Tools según negocio
    info_negocio = CONFIGURACIONES.get(business_id)
    prompt_sistema = info_negocio['system_prompt'] if info_negocio else "Eres un asistente útil."
    tools_nombres = info_negocio.get('tools_habilitadas', []) if info_negocio else []
    
    #mis_tools = TOOLS_POR_NEGOCIO.get(business_id, [])

    # Convertir nombres de tools a objetos tool
    mis_tools = []
    for tool_nombre in tools_nombres:
        if isinstance(tool_nombre, str) and tool_nombre in TOOLS_REGISTRY:
            mis_tools.append(TOOLS_REGISTRY[tool_nombre])
        elif not isinstance(tool_nombre, str):
            mis_tools.append(tool_nombre) 

    prompt_final = (
        f"{prompt_sistema}\n\n"
        f"DATOS DE CONTEXTO:\n"
        f"- Estás hablando con: {nombre_cliente}.\n"
        #f"IMPORTANTE: Después de recibir el resultado de una herramienta, SIEMPRE genera una respuesta de texto explicativa."
        # f"REGLAS DE RESPUESTA:\n"
        # f"1. Si usas una herramienta, NO muestres el código Python ni tags como <tool_code>.\n"
        # f"2. Solo muestra la respuesta natural y amigable para el usuario final.\n"
        # f"3. IMPORTANTE: Después de recibir el resultado de una herramienta, SIEMPRE genera una respuesta de texto explicativa."
    )
    
    # 3. VINCULACIÓN DINÁMICA (Aquí ocurre la magia ✨)
    if mis_tools:
        # Creamos una instancia temporal del LLM que solo conoce estas tools
        llm_actual = llm_primary.bind_tools(mis_tools)
        llm_backup_actual = llm_backup.bind_tools(mis_tools)
        logger.info(f"🔧 Vinculadas {len(mis_tools)} herramientas para {business_id}")
        for tool in mis_tools:
            logger.info(f"Tool vinculada: {tool.name}")
    else:
        # Si no hay tools, usamos el modelo base sin capacidades extra
        llm_actual = llm_primary
        llm_backup_actual = llm_backup
        logger.info(f"ℹ️ No hay herramientas vinculadas para {business_id}")
    
    # 4. Construir mensajes (System + Historia)
    mensajes_entrada = [SystemMessage(content=prompt_final)] + state["messages"]

    logger.info(f"Ejecutando LLM para thread: {thread_id}")
    
    try:
        # 5. Invocación
        response_msg = llm_actual.invoke(mensajes_entrada)
        
        logger.success(f"Respuesta de llm_actual para {thread_id}: {response_msg.content[:200]}...")

        # Logging de tokens
        loguear_consumo_tokens(response_msg, thread_id)
        
        # 6. RETORNO CORRECTO: Debe ser un dict con la clave 'messages'
        # LangGraph tomará esto y hará un append a la lista de mensajes en la DB.
        return {"messages": [response_msg]}

    except Exception as e:
        #logger.exception(f"⚠️ Fallo LLM primario ({e}). Cambiando a respaldo...")
        logger.warning(f"⚠️ Fallo LLM primario para {thread_id} ({e}). Cambiando a respaldo...")
        try:
            response_msg = llm_backup_actual.invoke(mensajes_entrada)

            logger.success(f"Respuesta de llm_backup_actual para {thread_id}: {response_msg.content[:200]}...")

            loguear_consumo_tokens(response_msg, thread_id)
            
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
        for negocio_conf in CONFIGURACIONES.values():
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


#tool_node = ToolNode(TODAS_LAS_TOOLS)
tool_node = ToolNode(obtener_todas_las_tools(), handle_tool_errors=True)

# Construcción del grafo
workflow_builder = StateGraph(State)

workflow_builder.add_node("chatbot", nodo_chatbot)
workflow_builder.add_node("tools", tool_node) # Nodo ´tool_node´ es genérico de ejecución

workflow_builder.set_entry_point("chatbot")

# Lógica condicional: Si el chatbot pide tool -> va a 'tools', si no -> END
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
        
        logger.info(f"Procesando msg. thread={thread_id}, business={business_id}")

        with pool.connection() as conn:
            checkpointer = PostgresSaver(conn)
            app = workflow_builder.compile(checkpointer=checkpointer)        
            
            inputs = {"messages": [HumanMessage(content=mensaje_usuario)]}
            
            # Ejecución
            result = app.invoke(inputs, config=config)
            mensajes = result.get("messages", [])
            
            # --- LÓGICA DE RECUPERACIÓN DE RESPUESTA ---
            
            # 1. Definir el turno actual (lo que pasó después de que el humano habló)
            indices_humanos = [i for i, m in enumerate(mensajes) if isinstance(m, HumanMessage)]
            if indices_humanos:
                ultimo_humano = indices_humanos[-1]
                mensajes_turno = mensajes[ultimo_humano+1:]
            else:
                mensajes_turno = mensajes

            respuesta_final = ""

            # 2. Buscar hacia atrás el primer contenido útil
            for msg in reversed(mensajes_turno):
                
                # A. Mensaje de IA con texto (Ideal)
                if isinstance(msg, AIMessage) and msg.content and str(msg.content).strip():
                    respuesta_final = msg.content
                    break
                
                # B. Si la IA no habló, ¿hay un error explícito de tool?
                if isinstance(msg, ToolMessage) and "error" in str(msg.content).lower():
                    respuesta_final = f"Tuve un problema técnico al consultar: {msg.content}"
                    break

            # 3. Fallback: Si la IA ejecutó la tool pero devolvió vacío
            if not respuesta_final:
                hubo_tools = any(isinstance(m, ToolMessage) for m in mensajes_turno)
                if hubo_tools:
                    # Si hubo tools, significa que la acción se hizo.
                    # Asumimos éxito si no hubo error, pero avisamos que no hay texto.
                    respuesta_final = "✅ He consultado la información. (El asistente procesó la orden pero no generó texto de respuesta)."
                    logger.warning("⚠️ La IA ejecutó tools pero devolvió respuesta vacía.")
                else:
                    respuesta_final = "Lo siento, no pude generar una respuesta."

            return {
                "status": "COMPLETED",
                "response": respuesta_final
            }

    except Exception as e:
        logger.exception(f"🔴 Error crítico en procesar_mensaje: {e}")
        return {
            "status": "ERROR",
            "response": "Error interno. Por favor, intenta nuevamente más tarde."
        }