import time
from psycopg_pool import ConnectionPool
from loguru import logger
from langchain_core.messages import BaseMessage
import os
import json


# ==============================================================================
# 2. MÉTRICAS
# ==============================================================================
def cargar_pricing():
    """Carga la configuración de precios desde config_pricing.json"""
    try:
        pricing_path = os.path.join(os.path.dirname(__file__), 'config_pricing.json')
        with open(pricing_path, 'r', encoding='utf-8') as f:
            pricing_data = json.load(f)
        logger.info("✅ Configuración de precios cargada.")
        return pricing_data['MODEL_PRICING']
    except Exception as e:
        logger.exception(f"🔴 Error cargando config_pricing.json: {e}")
        return {}


MODEL_PRICING = cargar_pricing()

def registrar_evento(pool: ConnectionPool, result, thread_id, latency_ms, isLlmPrimary=True):
    """
    1- Extrae tokens y calcula costo exacto según el modelo utilizado.
    2- Inserta un evento en la tabla de analytics de forma segura.
    No bloquea si falla (fire and forget lógico).
    """
    try:
        # 1. Normalización del objeto mensaje/result
        mensaje = None
        metadata = {}
        logger.debug(f"🔍 Analizando resultado para métricas para: {thread_id}")
        # Caso A: Result es un objeto AIMessage directo (invoke del LLM)
        if isinstance(result, BaseMessage):
            mensaje = result
            metadata = result.response_metadata
        # Caso B: Result es un dict de estado (invoke del grafo)
        elif isinstance(result, dict) and "messages" in result:
            mensaje = result["messages"][-1]
            if hasattr(mensaje, 'response_metadata'):
                metadata = mensaje.response_metadata
        # Caso C: Lista
        elif isinstance(result, list):
            mensaje = result[-1]
            if hasattr(mensaje, 'response_metadata'):
                metadata = mensaje.response_metadata
        # Caso D: Dict con clave 'response_metadata' (estructura de transcripción de audio)
        elif isinstance(result, dict) and "response_metadata" in result:
            metadata = result["response_metadata"]
            mensaje = result  # El diccionario completo es el "mensaje"
        
        # Caso E: ChatCompletion de OpenAI (análisis de imágenes con raw API)
        elif hasattr(result, 'choices') and hasattr(result, 'usage') and hasattr(result, 'model'):
            # Es un objeto ChatCompletion de OpenAI
            logger.debug(f"[METRICS] Detectado ChatCompletion de OpenAI: {result.model}")
            mensaje = result  # Usamos el objeto completo
            metadata = {
                'model_name': result.model,
                'token_usage': {
                    'prompt_tokens': result.usage.prompt_tokens,
                    'completion_tokens': result.usage.completion_tokens,
                    'total_tokens': result.usage.total_tokens
                }
            }

        if not mensaje: 
            logger.warning(f"⚠️ No se pudo identificar un mensaje válido para extraer métricas: {result}")
            return []

        # 2. Extracción de Tokens
        usage = None
        if hasattr(mensaje, 'response_metadata') and mensaje.response_metadata:
            # Extraer token_usage o usage_metadata del response_metadata
            usage = mensaje.response_metadata.get('token_usage') or mensaje.response_metadata.get('usage_metadata')
        elif metadata: # Fallback a metadata antigua
            usage = metadata.get('token_usage') or metadata.get('usage_metadata')

        # Manejo especial para métricas de transcripción (diccionarios)
        if isinstance(mensaje, dict) and 'usage_transcription' in mensaje:
            usage = mensaje.get('usage_transcription')
        elif hasattr(mensaje, 'usage_transcription') and mensaje.usage_transcription:
            usage = mensaje.usage_transcription

        if usage:
            # Verificar si es transcripción de audio o LLM normal
            is_transcription = 'duration_minutes' in usage
            
            if is_transcription:
                # Para transcripción de audio (Whisper)
                duration_minutes = usage.get('duration_minutes', 0)
                input_tokens = 0
                output_tokens = 0
                total_tokens = 0
                
                # Extraer model_name de metadata o del mismo usage
                if isinstance(mensaje, dict) and 'response_metadata' in mensaje:
                    model_name = mensaje['response_metadata'].get('model_name', 'whisper-1').lower()
                else:
                    model_name = metadata.get('model_name', 'whisper-1').lower()
                
                if model_name == "gpt-4o-mini-transcribe":
                    costo_total = duration_minutes * 0.003  
                elif model_name == "whisper-1":
                    costo_total = duration_minutes * 0.006  

                logger.info(
                    f"💰 TRANSCRIPTION USAGE [{thread_id}] ({model_name}): "
                    f"Duration={duration_minutes:.3f} min | "
                    f"Costo: ${costo_total:.6f} USD | "
                    f"Latency: {latency_ms}ms"
                )
            else:
                # Para LLM normal (tokens)
                # Diferentes proveedores usan diferentes nombres de claves
                input_tokens = usage.get('input_tokens') or usage.get('prompt_tokens', 0)
                output_tokens = usage.get('output_tokens') or usage.get('completion_tokens', 0)
                total_tokens = usage.get('total_tokens', 0)

                # 3. Detección de Modelo y Precio
                model_name = metadata.get('model_name', '').lower()
                
                # Buscamos el precio en el diccionario usando coincidencia parcial
                # (Ej: "gpt-4o-mini-2024" coincidirá con "gpt-4o-mini")
                costos = None
                for key, precios in MODEL_PRICING.items():
                    if key in model_name:
                        costos = precios
                        break
                
                # Cálculo del costo
                if costos:
                    costo_input = (input_tokens / 1_000_000) * costos["input"]
                    costo_output = (output_tokens / 1_000_000) * costos["output"]
                    costo_total = costo_input + costo_output
                else:
                    logger.warning(f"⚠️ Modelo no reconocido para cálculo de costos: {model_name}")
                    costo_input = (input_tokens / 1_000_000) * 0.15
                    costo_output = (output_tokens / 1_000_000) * 0.60
                    costo_total = costo_input + costo_output

                logger.info(
                    f"💰 TOKEN USAGE [{thread_id}] ({model_name}): "
                    f"In={input_tokens} | Out={output_tokens} | Total={total_tokens} | "
                    f"Costo: ${costo_total:.6f} USD | Latency: {latency_ms}ms"
                )
            
            # --- 🔍 DETECCIÓN DE TOOLS Y EVENT TYPE ---
            tool_name = None
            is_image_analysis = False
            
            # Detectar si es análisis de imagen (basado en modelo o provider)
            model_lower = model_name.lower() if isinstance(model_name, str) else ""
            provider = metadata.get('provider', '') if isinstance(metadata, dict) else ''
            
            if 'vision' in provider or 'gpt-4o' in model_lower or 'gemini' in model_lower:
                # Es posible que sea análisis de imagen
                # Verificar si los tokens de entrada son muy altos (indicativo de imagen)
                if input_tokens > 10000:  # Las imágenes generan muchos tokens de entrada
                    is_image_analysis = True
                    tool_name = "image_analysis"
                    logger.info("🖼️ Análisis de imagen completado.")
            
            if not tool_name:
                if hasattr(result, 'tool_calls') and result.tool_calls:
                    # El LLM decidió usar herramientas
                    for tool in result.tool_calls:
                        tool_name = tool.get("name")
                        tool_args = tool.get("args")
                        logger.info(f"🛠️ LLM EJECUTANDO TOOL: '{tool_name}' | Args: {tool_args}")
                elif is_transcription:
                    # Para transcripción, el "tool" es la transcripción misma
                    tool_name = "transcription"
                    logger.info("🎤 Transcripción de audio completada.")
                else:
                    # El LLM respondió con texto normal
                    tool_name = "text_resp"
                    logger.info("💬 LLM respondió con texto.")

            # 📝 REGISTRO EN DB (Fire and Forget)
            business_id = thread_id.split(':')[0] if ':' in thread_id else ""

            # Determinar event_type basado en el tipo de operación
            if is_transcription:
                event_type = "transcription"
            elif is_image_analysis:
                event_type = "image_analysis"
            else:
                event_type = "llm_primary" if isLlmPrimary else "llm_fallback"

            data = (
                business_id,
                thread_id,
                event_type,
                input_tokens,
                output_tokens,
                f"{model_name}", 
                costo_total,
                latency_ms,
                tool_name,
                None
            )

            sql = """
            INSERT INTO analytics_events 
            (business_id, thread_id, event_type, input_tokens, output_tokens, 
            model_name, estimated_cost, latency_ms, tool_name, sentiment_label)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            with pool.connection() as conn:
                conn.execute(sql, data)

            logger.info(f"✅ Evento de consumo de tokens registrado en DB para thread_id: {thread_id}")

            return usage
        else:
            logger.warning(f"⚠️ No se pudo extraer información de tokens para métricas del resultado: {result}")
            return None

    except Exception as e:
        logger.error(f"⚠️ Error calculando métricas de tokens: {e}")
        return None

