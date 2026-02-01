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
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage, RemoveMessage
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
    timeout=30,           # Esperar máx 30s por una conexión libre
    max_lifetime=600,     # (10 min) Matar conexiones viejas para forzar reconexión fresca
    max_idle=300,         # (5 min) Cerrar conexiones que no hacen nada
    reconnect_timeout=5,  # Si se cae la DB, intentar reconectar cada 5s

    kwargs={
        "autocommit": True, 
        "prepare_threshold": 0,
        
        # Opciones de TCP para mantener el canal despierto (Keepalive)
        "keepalives": 1,
        "keepalives_idle": 30,     # Ping cada 30 segundos
        "keepalives_interval": 10,
        "keepalives_count": 5
    }
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
# agente.py
def nodo_agente(state: AgentState, config: RunnableConfig):
    try:
        # --- 1. CONFIGURACIÓN ---
        configurable = config.get("configurable", {})
        business_id = configurable.get("business_id")
        thread_id = configurable.get("thread_id")
        nombre_cliente = configurable.get("client_name", "Cliente")
        
        info_negocio = CONFIGURACIONES.get(business_id)
        prompt_sistema = info_negocio['system_prompt'] if info_negocio else "Eres un asistente útil."
        
        # Enriquecer System Prompt
        prompt_final = (
            f"{prompt_sistema}\n\n"
            f"DATOS DE CONTEXTO:\n"
            f"- Estás hablando con: {nombre_cliente}.\n"
        )

        logger.info(f"Ejecutando agente para thread_id: {thread_id}, business_id: {business_id}")

        # --- 2. FILTRADO INTELIGENTE Y RECONSTRUCCIÓN 🛡️ ---
        mensajes_crudos = state["messages"]
        mensajes_validos = []
        
        TIPOS_CLASE_VALIDOS = (SystemMessage, HumanMessage, AIMessage, ToolMessage)

        for m in mensajes_crudos:
            # CASO A: Es un Objeto válido
            if isinstance(m, TIPOS_CLASE_VALIDOS):
                mensajes_validos.append(m)
            
            # CASO B: Es un Diccionario (Aquí estaba el problema)
            elif isinstance(m, dict):
                # Intentamos detectar qué es, mirando 'type' (LangChain) O 'role' (OpenAI)
                tipo = m.get('type')
                rol = m.get('role')
                contenido = m.get('content', '')
                
                # Mapeo universal
                if tipo == 'human' or rol == 'user':
                    mensajes_validos.append(HumanMessage(content=contenido))
                
                elif tipo == 'ai' or rol == 'assistant' or rol == 'model':
                    mensajes_validos.append(AIMessage(content=contenido))
                
                elif tipo == 'system' or rol == 'system':
                    mensajes_validos.append(SystemMessage(content=contenido))
                
                elif tipo == 'tool' or rol == 'tool':
                    t_id = m.get('tool_call_id') or m.get('id')
                    mensajes_validos.append(ToolMessage(content=contenido, tool_call_id=t_id))
                
                else:
                    logger.warning(f"🧹 Filtrando dict desconocido: type={tipo}, role={rol}")

            else:
                logger.warning(f"🧹 Filtrando objeto basura: {type(m)}")

        # Verificación de seguridad: ¿Hay algo más que el System Prompt?
        if not mensajes_validos:
            logger.warning("⚠️ La lista de mensajes válidos está vacía. El LLM podría no responder.")

        # Construimos el contexto final
        mensajes_con_contexto = [SystemMessage(content=prompt_final)] + mensajes_validos
        
        # ----------------------------------------------------

        logger.debug(f"Enviando {len(mensajes_con_contexto)} mensajes al LLM...")
        
        # Intento 1
        respuesta = llm_primary_with_tools.invoke(mensajes_con_contexto)
        
        # LOGS DE DIAGNÓSTICO
        logger.debug(f"Respuesta Raw LLM: {respuesta.content}...")  # Loguear solo los primeros 200 caracteres
        
        modelo_usado = respuesta.response_metadata.get('model_name', 'Desconocido')
        logger.success(f"🟩 Respuesta exitosa con modelo: {modelo_usado}.")
        
    except Exception as e:
        logger.warning(f"⚠️ Fallo LLM primario ({e}). Cambiando a respaldo...")
        try:
            respuesta = llm_backup_with_tools.invoke(mensajes_con_contexto)
        except Exception as e2:
            logger.error(f"🔺 Fallo total: {e2}")
            return {"messages": [AIMessage(content="Error técnico interno.")]}

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


# Esta función extrae los contadores de tokens consumidos de forma segura y los imprime en el log.
def _loguear_consumo_tokens(mensaje, thread_id):
    """
    Extrae y loguea el consumo de tokens de la respuesta del LLM.
    """
    try:
        usage = None
        
        # 1. Intento estándar de LangChain (La mayoría de modelos actuales)
        if hasattr(mensaje, 'usage_metadata') and mensaje.usage_metadata:
            usage = mensaje.usage_metadata
            
        # 2. Intento específico para versiones viejas de Gemini/Vertex
        elif hasattr(mensaje, 'response_metadata') and mensaje.response_metadata:
            usage = mensaje.response_metadata.get('token_usage') or mensaje.response_metadata.get('usage_metadata')

        if usage:
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
            total_tokens = usage.get('total_tokens', 0)
            
            # Costo estimado para Gemini 1.5 Flash (aprox $0.075 / 1M input, $0.30 / 1M output)
            # Ajusta estos valores según tu modelo exacto (Flash-Lite es aún más barato)
            costo_estimado = (input_tokens * 0.000000075) + (output_tokens * 0.00000030)
            
            logger.info(
                f"💰 TOKEN USAGE [{thread_id}]: "
                f"In={input_tokens} | Out={output_tokens} | Total={total_tokens} | "
                f"Costo Est: ${costo_estimado:.6f} USD"
            )
            return usage
            
    except Exception as e:
        logger.warning(f"⚠️ No se pudo extraer métricas de tokens: {e}")
    
    return None

# Tiempo máximo de espera de ejecucion de tool (ej: 5 minutos)
TIEMPO_EXPIRACION_MINUTOS = 2

# BANDERA DE COMPORTAMIENTO:
# True  = Si el usuario habla, cancela la tool anterior y atiende lo nuevo.
# False = Si el usuario habla, le dice "Espera" y bloquea el nuevo mensaje.
PERMITIR_INTERRUPCION_USUARIO = True


# ==================== 5. FUNCIÓN PÚBLICA (PARA FLASK) ====================
def procesar_mensaje(mensaje_usuario: str, config: dict) -> dict:
    """
    Maneja el ciclo completo: Conexión -> Invocación -> Detección de Estado.
    """
    try:
        conf_data = config.get('configurable', {})
        thread_id = conf_data.get('thread_id', 'unknown')
        business_id = conf_data.get('business_id', 'unknown')
        
        logger.info(f"Procesando msg. thread={thread_id}, business={business_id}")

        aviso_timeout = ""

        with pool.connection() as conn:
            app = _obtener_app_activa(conn)
            
            # --- 1. OBTENER ESTADO ACTUAL ---
            snapshot = app.get_state(config)
        
            # --- 2. EL PORTERO 🛡️ (Gestión de Interrupciones) ---
            if snapshot.next and "tools" in snapshot.next:
                
                # CASO A: TIMEOUT (La espera caducó -> Limpiamos siempre)
                if _es_estado_vencido(snapshot):
                    logger.info(f"🧹 Limpiando estado vencido para {thread_id}...")
                    try:
                        last_msg = snapshot.values["messages"][-1]
                        if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                            tool_call_id = last_msg.tool_calls[0]['id']
                            from langchain_core.messages import ToolMessage
                            
                            app.update_state(
                                config,
                                {"messages": [ToolMessage(tool_call_id=tool_call_id, content="Error: Timeout. El usuario tardó en responder.")]},
                                as_node="tools"
                            )
                            aviso_timeout = "⚠️ *Aviso:* La solicitud anterior caducó. He procesado tu nuevo mensaje:\n\n"
                    except Exception as e:
                        logger.error(f"🔴 No se pudo limpiar timeout: {e}")
                
                # CASO B: NO EXPIRÓ (El usuario interrumpe)
                else:
                    # AQUÍ USAMOS TU BANDERA 🚩
                    if PERMITIR_INTERRUPCION_USUARIO:
                        # OPCIÓN 1: Flexible (Cancela lo viejo, atiende lo nuevo)
                        logger.info(f"🔄 Interrupción permitida en {thread_id}. Cancelando acción anterior...")
                        try:
                            last_msg = snapshot.values["messages"][-1]
                            if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                                tool_call_id = last_msg.tool_calls[0]['id']
                                from langchain_core.messages import ToolMessage
                                
                                app.update_state(
                                    config,
                                    {"messages": [ToolMessage(tool_call_id=tool_call_id, content=f"El usuario interrumpió la espera con: '{mensaje_usuario}'. CANCELA la acción anterior.")]},
                                    as_node="tools"
                                )
                                # Dejamos fluir hacia abajo para que el invoke procese el nuevo mensaje
                        except Exception as e:
                            logger.error(f"🔴 Error gestionando interrupción: {e}")

                    else:
                        # OPCIÓN 2: Estricta (Bloquea al usuario)
                        logger.info(f"⛔ Bloqueo estricto para {thread_id}: Hay aprobación pendiente.")
                        return {
                            "status": "EN_ESPERA",
                            "response": "⏳ Todavía estoy esperando la confirmación de la acción anterior. Por favor, aguarda un momento o espera a que expire."
                        }

            # --- 3. INVOCAR AL AGENTE ---
            # Si estaba en modo estricto, ya retornamos arriba y no llegamos aquí.
            result = app.invoke(
                {"messages": [{"role": "user", "content": mensaje_usuario}]}, 
                config=config
            )
            
            # --- 4. VERIFICAR ESTADO FINAL ---
            snapshot = app.get_state(config)
            
            # CASO HITL
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

            # CASO RESPUESTA FINAL
            last_message = result["messages"][-1]
            _loguear_consumo_tokens(last_message, thread_id)
            texto_final = _extraer_contenido_limpio(last_message) 

            if aviso_timeout:
                texto_final = aviso_timeout + texto_final

            return {
                "status": "COMPLETADO",
                "response": texto_final
            }

    except GraphRecursionError:
        logger.error("🔴 Límite de recursión.")
        return {"status": "ERROR", "response": "Lo siento, me confundí. ¿Puedes preguntar de otra forma?"}
    except Exception as e:
        logger.error(f"🔴 Error CRÍTICO: {e}")
        import traceback
        traceback.print_exc() 
        return {"status": "ERROR", "response": "Ocurrió un error interno."}


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
                "status": "ACCION_TIMEOUT",
                "response": "⚠️ La solicitud de aprobación ha caducado por seguridad. Por favor, solicita la acción nuevamente."
            }

        # 3. REANUDAR SEGÚN DECISIÓN
        if decision == "approve":
            logger.info(f"🚀 Reanudando ejecución para {thread_id}...")
            
            # Reanudamos el grafo
            result = app.invoke(None, config=config)
            
            last_message = result["messages"][-1]
            
            _loguear_consumo_tokens(last_message, thread_id)

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
            
            # 3. Fallback final MEJORADO
            if not texto_respuesta:
                logger.warning("⚠️ LLM mudo. Buscando output de la tool...")
                # Buscamos el último ToolMessage en el historial reciente
                for msg in reversed(result["messages"]):
                    if isinstance(msg, ToolMessage):
                        texto_respuesta = f"✅ Acción completada. Resultado:\n{msg.content}"
                        break
                
            # Si aún así falla
            if not texto_respuesta:
                texto_respuesta = "✅ Acción completada exitosamente."

            return {
                "status": "ACCION_EJECUTADA", 
                "response": texto_respuesta
            }
            
        # --- RECHAZO CON BORRADO DE MEMORIA (MEN IN BLACK 🕶️) ---
        else:
            logger.info(f"🚫 Rechazando ejecución para {thread_id}...")
            
            # 1. Obtener el historial completo actual
            snapshot = app.get_state(config)
            mensajes_existentes = snapshot.values.get("messages", [])
            
            if mensajes_existentes:
                logger.info(f"🧹 Iniciando borrado de {len(mensajes_existentes)} mensajes para reiniciar contexto...")
                
                instrucciones_borrado = []
                
                # 2. Iterar detectando si es Objeto o Diccionario
                for m in mensajes_existentes:
                    msg_id = None
                    
                    # CASO A: Es un Objeto (tiene atributo .id)
                    if hasattr(m, 'id'):
                        msg_id = m.id
                    
                    # CASO B: Es un Diccionario (tiene clave 'id')
                    elif isinstance(m, dict):
                        msg_id = m.get('id')
                    
                    # Solo agregamos la orden de borrado si encontramos un ID válido
                    if msg_id:
                        instrucciones_borrado.append(RemoveMessage(id=msg_id))
                
                # 3. Ejecutar el borrado masivo
                if instrucciones_borrado:
                    app.update_state(config, {"messages": instrucciones_borrado})
                    logger.success("✨ Memoria reiniciada exitosamente.")
                else:
                    logger.warning("⚠️ No se encontraron IDs válidos para borrar.")

            # 4. Retornar respuesta final
            return {
                "status": "ACCION_RECHAZADA", 
                "response": "⛔ Solicitud cancelada. He reiniciado nuestra conversación. ¿En qué más puedo ayudarte?"
            }


# ==================== EJEMPLO DE USO LOCAL (TEST) ====================

#if __name__ == "__main__":
    # Simulación de lo que haría Flask
    # print("--- Iniciando Chat ---")
    
    # usuario_id = "cliente_99"
    
    # resp1 = procesar_mensaje("Hola, busco zapatillas nike", usuario_id)
    # print(f"🤖: {resp1}")
    
    # resp2 = procesar_mensaje("¿Cuántas quedan?", usuario_id) 
    # print(f"🤖: {resp2}")