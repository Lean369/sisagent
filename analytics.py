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

        if not mensaje: return []

        # 2. Extracción de Tokens
        usage = None
        if hasattr(mensaje, 'usage_metadata') and mensaje.usage_metadata:
            usage = mensaje.usage_metadata
        elif metadata: # Fallback a metadata antigua
            usage = metadata.get('token_usage') or metadata.get('usage_metadata')

        if usage:
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
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
                str_costo = f"${costo_total:.6f} USD"
            else:
                logger.warning(f"⚠️ Modelo no reconocido para cálculo de costos: {model_name}")
                costo_input = (input_tokens / 1_000_000) * 0.15
                costo_output = (output_tokens / 1_000_000) * 0.60
                costo_total = costo_input + costo_output
                str_costo = f"${costo_total:.6f} USD"

            logger.info(
                f"💰 TOKEN USAGE [{thread_id}] ({model_name}): "
                f"In={input_tokens} | Out={output_tokens} | Total={total_tokens} | "
                f"Costo: {str_costo} | Latency: {latency_ms}ms"
            )
            # --- 🔍 DETECCIÓN DE TOOLS (NUEVO) ---
            if result.tool_calls:
                # El LLM decidió usar herramientas
                for tool in result.tool_calls:
                    tool_name = tool.get("name")
                    tool_args = tool.get("args")
                    logger.info(f"🛠️ LLM EJECUTANDO TOOL: '{tool_name}' | Args: {tool_args}")
            else:
                # El LLM respondió con texto normal
                logger.info("💬 LLM respondió con texto.")

            # 📝 REGISTRO EN DB (Fire and Forget)
            business_id = thread_id.split(':')[0] if ':' in thread_id else ""

            data = (
                business_id,
                thread_id,
                "llm_primary" if isLlmPrimary else "llm_fallback", 
                input_tokens,
                output_tokens,
                f"{model_name}", 
                costo_total,
                latency_ms,
                f"{tool_name}" if result.tool_calls else "text_resp",
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

    except Exception as e:
        logger.error(f"⚠️ Error calculando métricas de tokens: {e}")
        return None

