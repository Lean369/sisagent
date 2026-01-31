import os
import re
from typing import TypedDict, Annotated, List
from datetime import datetime, timezone, timedelta
import operator
from dotenv import load_dotenv
from loguru import logger
import sys

# --- Imports de LangChain y LangGraph ---
from langchain_core.runnables import RunnableConfig
from config_negocios import CONFIGURACIONES
from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.errors import GraphRecursionError
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.postgres import PostgresSaver

# --- Import de Base de Datos (Pool) ---
from psycopg_pool import ConnectionPool

# ==================== CONFIGURACIÓN ====================
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


# ==================== 1. CONFIGURACIÓN DE BASE DE DATOS Y POOL ====================
# Configuración de DB
DB_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Creamos el POOL DE CONEXIONES globalmente.
# Esto se hace una sola vez cuando arranca la aplicación Flask.
pool = ConnectionPool(
    conninfo=DB_URI,
    min_size=1,  # Mantiene al menos 1 conexión viva
    max_size=20, # Soporta hasta 20 usuarios simultáneos procesando
    kwargs={"autocommit": True, "prepare_threshold": 0}
)

# Inicializar tablas (Solo se ejecuta una vez al arrancar)
# Usamos una conexión temporal del pool para verificar que las tablas existan
with pool.connection() as conn:
    checkpointer_temp = PostgresSaver(conn=conn)
    checkpointer_temp.setup()

# ==================== 2. DEFINICIÓN DE HERRAMIENTAS ====================

@tool
def consultar_inventario(producto: str) -> str:
    """Consulta el stock disponible de un producto específico."""
    # Aquí iría tu lógica real de base de datos o API externa
    if "zapatilla" in producto.lower():
        return f"STOCK: Hay 15 pares de {producto} disponibles."
    return f"STOCK: No se encontró información sobre {producto}."

tools = [consultar_inventario]

@tool
def ver_menu() -> str:
    """Retorna el menú actual de Luigi's Pizza."""
    menu = (
        "Menú de Luigi's Pizza:\n"
        "1. Pizza Margherita - $10\n"
        "2. Pizza Pepperoni - $12\n"
        "3. Empanada de Carne - $5\n"
        "4. Empanada de Jamón y Queso - $5\n"
    )
    return menu

tools.append(ver_menu)

for tool in tools:
    logger.info(f"Tool name added: {tool.name}")

# ==================== 3. CONFIGURACIÓN DEL MODELO (LLM) ====================

# Patron factory para obtener el modelo LLM según configuración
def get_llm_model(provider_override=None):
    """Retorna el modelo LLM según la configuración
   
    Args:
        provider_override: Si se especifica, usa este provider en lugar del configurado
    """
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

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
LLM_PROVIDER_FALLBACK = os.getenv("LLM_PROVIDER_FALLBACK", "openai").lower()

llm_primary = get_llm_model(LLM_PROVIDER)
llm_backup = get_llm_model(LLM_PROVIDER_FALLBACK)

# Vincular herramientas a los modelos
llm_primary_with_tools = llm_primary.bind_tools(tools)
llm_backup_with_tools = llm_backup.bind_tools(tools)

logger.info(f"LLM Provider configurado: {LLM_PROVIDER}")
logger.info(f"LLM Provider fallback: {LLM_PROVIDER_FALLBACK}")

llm_universal = llm_primary_with_tools.with_fallbacks(
    [llm_backup_with_tools],
    exceptions_to_handle=(Exception,) # Captura cualquier error
)

# ==================== 4. DEFINICIÓN DEL GRAFO (WORKFLOW) ====================

# Definimos el estado del agente
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]


# Nodo del Agente (Cerebro)
def nodo_agente(state: AgentState, config: RunnableConfig):
    try:
        # LangGraph guarda tus datos personalizados dentro de la clave 'configurable'
        configurable = config.get("configurable", {})
    
        business_id = configurable.get("business_id")
        thread_id = configurable.get("thread_id")
        nombre_cliente = configurable.get("client_name", "Cliente")
        logger.debug(f"Negocio ID: {business_id}, Thread ID: {thread_id}, Nombre Cliente: {nombre_cliente}")
        
        # Buscamos la configuración de ese negocio
        info_negocio = CONFIGURACIONES.get(business_id)
        
        if not info_negocio:
            logger.error(f"🔴 Configuración no encontrada para business_id: {business_id}")
            prompt_sistema = "Eres un asistente útil."
        else:
            logger.debug(f"Configuración cargada para business_id: {business_id} - nombre de negocio: {info_negocio['nombre']}")
            logger.debug(f"Tools habilitadas: {info_negocio['tools_habilitadas']}")
            # 3. ENRIQUECIMIENTO DEL PROMPT
            prompt_final = (
                f"{info_negocio['system_prompt']}\n\n"
                f"DATOS DE CONTEXTO:\n"
                f"- Estás hablando con: {nombre_cliente}.\n"
                f"- Usa su nombre ocasionalmente para que la conversación sea cercana, pero no en cada frase."
            )
            prompt_sistema = prompt_final

        logger.info(f"Ejecutando agente para thread_id: {thread_id}, business_id: {business_id}")

        # Verificamos si ya existe un mensaje de sistema, si no, lo agregamos al inicio
        mensajes = state["messages"]
        
        # Opción A: Agregar siempre el System Prompt al principio de la lista para el LLM
        # (No lo guardamos en la DB para no duplicarlo, solo lo usamos para invocar)
        mensajes_con_contexto = [SystemMessage(content=prompt_sistema)] + mensajes
        #logger.debug(f"contexto: {mensajes_con_contexto}")
        # Intento 1: LLM primario
        logger.debug("Intentando con LLM primario...")
        respuesta = llm_primary_with_tools.invoke(mensajes_con_contexto)
        modelo_usado = respuesta.response_metadata.get('model_name', 'Desconocido')
        logger.success(f"🟩 Respuesta exitosa con modelo: {modelo_usado}.")
    except Exception as e:
        logger.warning(f"⚠️ Fallo LLM primario ({e}). Cambiando a LLM de respaldo...")
        try:
            # Intento 2: LLM de respaldo
            respuesta = llm_backup_with_tools.invoke(mensajes_con_contexto)
            modelo_usado = respuesta.response_metadata.get('model_name', 'Desconocido')
            logger.success(f"▲ Recuperado exitosamente con modelo: {modelo_usado}.")
            
        except Exception as e2:
            logger.error(f"🔺 Fallo total del sistema: {e2}")
            return {"status": "ERROR", "response": "No se pudo procesar su solicitud en este momento."}
    return {"messages": [respuesta]}


# Construcción del Grafo (Blueprint)
# Nota: Aún NO lo compilamos con memoria, eso se hace en tiempo de ejecución.
workflow_builder = StateGraph(AgentState)

workflow_builder.add_node("agente", nodo_agente)
workflow_builder.add_node("tools", ToolNode(tools))

workflow_builder.set_entry_point("agente")

workflow_builder.add_conditional_edges(
    "agente",
    tools_condition, # Decide si ir a 'tools' o terminar
)

workflow_builder.add_edge("tools", "agente") # Volver al agente después de usar herramienta

# Función auxiliar para compilar (DRY - Don't Repeat Yourself)
def _obtener_app_activa(conn):
    """Compila el grafo con la conexión actual y la configuración de interrupción."""
    checkpointer = PostgresSaver(conn=conn)
    # Aquí activamos el "Freno de Mano" antes de las herramientas
    return workflow_builder.compile(
        checkpointer=checkpointer, 
        interrupt_before=["tools"] 
    )

# --- 1. NUEVA FUNCIÓN AUXILIAR PARA EXTRAER CONTENIDO DE LA RESPUESTA DEL LLM  ---
def _extraer_contenido_limpio(mensaje) -> str:
    """
    Extrae texto puro de cualquier formato de mensaje (Dict, AIMessage, List, None).
    """
    contenido_crudo = ""

    logger.debug(f"Extrayendo contenido de mensaje: {str(mensaje)[:200]}...")  # Loguear solo los primeros 200 caracteres

    # A. Extracción segura del contenido crudo
    if hasattr(mensaje, 'content'):
        contenido_crudo = mensaje.content
    elif isinstance(mensaje, dict):
        contenido_crudo = mensaje.get('content', '')
    else:
        contenido_crudo = str(mensaje)

    # B. Procesamiento de formatos específicos (Gemini/Llama)
    texto_final = ""
    
    # Caso Gemini (Lista de diccionarios)
    if isinstance(contenido_crudo, list):
        texto_final = "".join([b.get("text", "") for b in contenido_crudo if isinstance(b, dict) and b.get("type") == "text"])
        # Fallback por si la lista es de strings simples
        if not texto_final and contenido_crudo:
             texto_final = " ".join([str(x) for x in contenido_crudo])
    
    # Caso None
    elif contenido_crudo is None:
        texto_final = ""
    
    # Caso String estándar
    else:
        texto_final = str(contenido_crudo)

    # C. Limpieza de artefactos (Llama 3 XML Leaking)
    texto_final = re.sub(r'<function=.*?>.*?</function>', '', texto_final, flags=re.DOTALL)
    
    logger.debug(f"Contenido extraído limpio: {texto_final[:200]}...")  # Loguear solo los primeros 200 caracteres
    return texto_final.strip()


# ==================== 5. FUNCIÓN PÚBLICA (PARA FLASK) ====================
def procesar_mensaje(mensaje_usuario: str, config: dict) -> dict:
    """
    Maneja el ciclo completo: Conexión -> Invocación -> Detección de Estado.
    """
    try:
        conf_data = config.get('configurable', {})
        thread_id = conf_data.get('thread_id', 'unknown')
        business_id = conf_data.get('business_id', 'unknown')
        client_name = conf_data.get('client_name', 'unknown')
        
        logger.info(f"Procesando msg. thread={thread_id}, business={business_id}")

        aviso_timeout = ""  # <--- 1. Variable para guardar el aviso

        with pool.connection() as conn:
            app = _obtener_app_activa(conn)
            
            # --- LIMPIEZA DE ESTADOS VIEJOS ---
            snapshot = app.get_state(config)
        
            # 2. VERIFICAR SI HAY UNA TOOL PENDIENTE (EL PORTERO 🛡️)
            if snapshot.next and "tools" in snapshot.next:
                
                # A. Verificamos si ya expiró (Tu lógica de timeout)
                if snapshot.next and "tools" in snapshot.next and _es_estado_vencido(snapshot):
                    logger.info(f"🧹 Limpiando estado vencido para {thread_id}...")
                    try:
                        last_msg = snapshot.values["messages"][-1]
                        if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                            tool_call_id = last_msg.tool_calls[0]['id']
                            from langchain_core.messages import ToolMessage
                            
                            app.update_state(
                                config,
                                {"messages": [ToolMessage(tool_call_id=tool_call_id, content="Error: Timeout.")]},
                                as_node="tools"
                            )
                            # <--- 2. Guardamos el aviso
                            aviso_timeout = "⚠️ *Aviso:* La solicitud anterior caducó por inactividad.\n\n" 
                            
                    except Exception as e:
                        logger.error(f"No se pudo limpiar: {e}")
                
                # B. Si NO ha expirado, BLOQUEAMOS al usuario
                else:
                    logger.info(f"⛔ Bloqueando mensaje de {thread_id}: Hay una aprobación pendiente vigente.")
                    return {
                        "status": "EN_ESPERA", # Un status nuevo para que no se mande a WhatsApp o se mande un aviso
                        "response": "⏳ Todavía estoy esperando la confirmación de la acción anterior. Por favor, aguarda un momento."
                    }
            
            # --- 2. INVOCAR AL AGENTE (DENTRO DEL WITH) ---
            # El invoke debe ocurrir mientras la conexión sigue viva
            result = app.invoke(
                {"messages": [{"role": "user", "content": mensaje_usuario}]}, 
                config=config
            )
            
            # --- 3. VERIFICAR ESTADO FINAL (DENTRO DEL WITH) ---
            snapshot = app.get_state(config)
            
            # CASO A: HITL (Requiere aprobación)
            if snapshot.next and "tools" in snapshot.next:
                if snapshot.values.get("messages"):
                    ultimo_mensaje = snapshot.values["messages"][-1]
                    if hasattr(ultimo_mensaje, 'tool_calls') and ultimo_mensaje.tool_calls:
                        tool_call = ultimo_mensaje.tool_calls[0]
                        return {
                            "status": "REQUIERE_APROBACION",
                            "tool_name": tool_call["name"],
                            "tool_args": tool_call["args"],
                            "message": f"Solicitando permiso para: {tool_call['name']}"
                        }

            # CASO B: Respuesta final
            last_message = result["messages"][-1]
            
            # Usamos la función auxiliar que definimos antes
            # (Asegúrate de que se llame igual que arriba, con o sin guion bajo)
            texto_final = _extraer_contenido_limpio(last_message) 
        
            return {
                "status": "COMPLETADO",
                "response": texto_final
            }

    except GraphRecursionError:
        logger.error("Se alcanzó el límite de recursión.")
        return {"status": "ERROR", "response": "Lo siento, me confundí. ¿Puedes preguntar de otra forma?"}
        
    except Exception as e:
        logger.error(f"Error CRÍTICO en procesar_mensaje: {e}")
        return {"status": "ERROR", "response": "Ocurrió un error interno."}

    except GraphRecursionError:
        logger.error("🔴 Se alcanzó el límite de recursión.")
        return {
            "status": "ERROR",
            "response": "Lo siento, me quedé pensando en un bucle. ¿Podrías reformular tu pregunta?"
        }
    except Exception as e:
        logger.error(f"🔴 Error CRÍTICO en procesar_mensaje: {e}")
        # Es útil imprimir el traceback en desarrollo
        import traceback
        traceback.print_exc() 
        return {
            "status": "ERROR", 
            "response": "Ocurrió un error interno."
        }


# Tiempo máximo de espera de ejecucion de tool (ej: 5 minutos)
TIEMPO_EXPIRACION_MINUTOS = 2

# Se encarga de mirar el reloj y decidir si el estado actual es viejo.
def _es_estado_vencido(snapshot) -> bool:
    """Verifica si el checkpoint actual tiene más antigüedad que el límite."""
    if not snapshot or not snapshot.created_at:
        return False
        
    # LangGraph devuelve created_at como string ISO o datetime UTC
    fecha_creacion = snapshot.created_at
    
    # Normalización a datetime con zona horaria UTC
    if isinstance(fecha_creacion, str):
        fecha_creacion = datetime.fromisoformat(fecha_creacion).replace(tzinfo=timezone.utc)
    elif isinstance(fecha_creacion, datetime) and fecha_creacion.tzinfo is None:
        fecha_creacion = fecha_creacion.replace(tzinfo=timezone.utc)

    ahora = datetime.now(timezone.utc)
    diferencia = ahora - fecha_creacion
    
    return diferencia > timedelta(minutes=TIEMPO_EXPIRACION_MINUTOS)


# ==================== 6. FUNCIÓN DE APROBACIÓN HUMANA ====================
def ejecutar_aprobacion(thread_id: str, decision: str) -> dict:
    """
    Función dedicada a reanudar el grafo después de una intervención humana.
    """
    # 1. RECUPERACIÓN DE DATOS PERDIDOS
    # Como thread_id = "negocio:usuario", podemos recuperar el negocio separando el string.
    try:
        business_id_recuperado = thread_id.split(':')[0]
    except IndexError:
        business_id_recuperado = "default" # Fallback por seguridad

    # LangGraph necesita estos datos de nuevo para inyectarlos en nodo_agente
    config = {
        "configurable": {
            "thread_id": thread_id,
            "business_id": business_id_recuperado,
            # El nombre del cliente se pierde si no lo guardaste en el Estado.
            # Puedes poner un genérico o pasarlo como argumento extra a esta función.
            "client_name": "Cliente" 
        },
        "recursion_limit": 10
    }

    logger.info(f"Reanudando aprobación para {thread_id}...")

    with pool.connection() as conn:
        app = _obtener_app_activa(conn)
        
        # 1. Obtenemos el estado ANTES de hacer nada
        snapshot = app.get_state(config)
        
        # 2. VERIFICACIÓN DE TIMEOUT
        if _es_estado_vencido(snapshot):
            logger.warning(f"⏳ Intento de aprobación vencido para {thread_id}")
            
            # Opcional: Inyectamos un mensaje de error al historial para limpiar el estado
            # Esto le dice al bot "La herramienta falló por timeout"
            # app.update_state(config, {"messages": [ToolMessage(..., content="Error: Timeout")]}, as_node="tools")
            
            return {
                "status": "ACCION_RECHAZADA",
                "response": "⚠️ La solicitud de aprobación ha caducado por seguridad. Por favor, solicita la acción nuevamente."
            }

        # 3. REANUDAR SEGÚN DECISIÓN
        if decision == "approve":
            logger.info(f"🚀 Reanudando ejecución para {thread_id}...")
            
            # Reanudamos el grafo
            result = app.invoke(None, config=config)
            
            last_message = result["messages"][-1]
            
            # --- CORRECCIÓN CRÍTICA AQUÍ ---
            
            # 1. Verificar si el bot quiere ejecutar OTRA herramienta (Tool Chaining)
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                nueva_tool = last_message.tool_calls[0]
                tool_name = nueva_tool['name']
                tool_args = nueva_tool['args']
                
                logger.warning(f"🔄 El bot encadenó otra herramienta: {tool_name}")
                
                # Devolvemos el estado de aprobación DE NUEVO para la nueva tool
                return {
                    "status": "REQUIERE_APROBACION",
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "message": f"He completado el paso anterior. Ahora necesito ejecutar: {tool_name}"
                }

            # 2. Si no es tool, intentamos extraer texto
            texto_respuesta = _extraer_contenido_limpio(last_message)
            
            # 3. Fallback final si realmente vino vacío y sin tools
            if not texto_respuesta:
                texto_respuesta = "✅ Acción completada exitosamente (El sistema no generó comentarios adicionales)."

            return {
                "status": "ACCION_EJECUTADA", 
                "response": texto_respuesta
            }
            
        else:
            return {"status": "ACCION_RECHAZADA", "response": "Acción cancelada."}


# ==================== EJEMPLO DE USO LOCAL (TEST) ====================

#if __name__ == "__main__":
    # Simulación de lo que haría Flask
    # print("--- Iniciando Chat ---")
    
    # usuario_id = "cliente_99"
    
    # resp1 = procesar_mensaje("Hola, busco zapatillas nike", usuario_id)
    # print(f"🤖: {resp1}")
    
    # resp2 = procesar_mensaje("¿Cuántas quedan?", usuario_id) 
    # print(f"🤖: {resp2}")