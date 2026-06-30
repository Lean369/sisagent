from flask import Blueprint, request, jsonify
from ..db import get_pool
import os, logging
import json
import psycopg
from datetime import datetime, timedelta
from loguru import logger
from ..utils.utilities import get_app_configs
from ..services.agent import get_agent_tools
from ..services.agent import workflow_builder # Importamos el builder para crear el grafico de grafo
from flask import Response
from ..utils.ddos_protection import ddos_protection

admin_bp = Blueprint('admin', __name__)

logger.info("🚀 Starting Admin Blueprint...")


# curl -sS http://localhost:5001/api/health
# curl -sS http://sisagent.sisnova.org/api/health
@admin_bp.route('/health', methods=['GET'])
def status():
    """Health check"""
    logger.info("🔍 Health check endpoint called")
    return jsonify({"status": "ok"}), 200


@admin_bp.route('/wipe-analytics', methods=['POST'])
def wipe_analytics():
    """Endpoint administrativo seguro para vaciar las tablas de analytics.

    ---
    tags:
      - admin
    parameters:
      - in: header
        name: X-Admin-Token
        type: string
        required: false
        description: Admin token header (si configurado)
      - in: body
        name: body
        schema:
          type: object
          properties:
            confirm:
              type: string
              example: "I UNDERSTAND"
    responses:
      200:
        description: analytics truncated
      400:
        description: Missing confirmation
      401:
        description: Unauthorized
      500:
        description: Server error
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if admin_token:
        token_header = request.headers.get("X-Admin-Token", "")
        if token_header != admin_token:
            logger.warning(f"[ADMIN] Intento no autorizado de wipe desde {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.get_json(silent=True) or {}
        if data.get("confirm") != "I UNDERSTAND":
            return jsonify({"error": "Missing explicit confirmation. Send JSON {\"confirm\":\"I UNDERSTAND\"}"}), 400

        # Ejecutar TRUNCATE de forma atómica
        pool = get_pool()
        with pool.connection() as conn:
            conn.execute("TRUNCATE TABLE analytics_events RESTART IDENTITY CASCADE")

        logger.info(f"[ADMIN] analytics_events truncated by {request.remote_addr} (user-agent: {request.headers.get('User-Agent')})")
        return jsonify({"status": "ok", "message": "analytics_events truncated"}), 200

    except Exception as e:
        logger.exception(f"🔴 [ADMIN] Error truncating analytics_events: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/dashboard', methods=['GET'])
def get_dashboard():
    """Devuelve datos analíticos agregados para el dashboard.

    ---
    tags:
      - admin
    parameters:
      - in: query
        name: start_date
        type: string
        description: Fecha de inicio (YYYY-MM-DD)
      - in: query
        name: end_date
        type: string
        description: Fecha de fin (YYYY-MM-DD)
      - in: query
        name: business_id
        type: string
        description: Filtrar por negocio
    responses:
      200:
        description: Dashboard data
      400:
        description: Invalid date format
      503:
        description: DB not configured
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if admin_token:
        token_header = request.headers.get("X-Admin-Token", "")
        if token_header != admin_token:
            logger.warning(f"[DASHBOARD] Acceso no autorizado desde {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        business_id = request.args.get('business_id')

        end_date = (
            datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
            if end_date_str else datetime.utcnow()
        )
        start_date = (
            datetime.strptime(start_date_str, '%Y-%m-%d')
            if start_date_str else end_date - timedelta(days=30)
        )

        biz_filter = "AND business_id = %s" if business_id else ""
        biz_params_pre = (business_id,) if business_id else ()

        logger.info(f"[DASHBOARD] Consulta: {start_date.date()} → {end_date.date()} | negocio: {business_id or 'todos'}")

        # Check DB pool availability early and return a clear 503 if not configured
        pool = get_pool()
        if not pool:
            logger.warning("[DASHBOARD] Base de datos no configurada; get_pool() devolvió None")
            return jsonify({"error": "Database not configured"}), 503

        dashboard = {
            "period": {"start": start_date.strftime('%Y-%m-%d'), "end": (end_date - timedelta(days=1)).strftime('%Y-%m-%d')},
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "filters": {"business_id": business_id or "all"},
            "kpis": {},
            "performance": {},
            "costs": {},
            "security": {},
            "usage": {},
            "businesses": [],
        }

        pool = get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                # KPIs
                cur.execute(f"""
                    SELECT
                        COUNT(*)                                            AS total_events,
                        COUNT(DISTINCT thread_id)                           AS unique_conversations,
                        COUNT(DISTINCT business_id)                         AS active_businesses,
                        COALESCE(SUM(input_tokens + output_tokens), 0)      AS total_tokens,
                        COALESCE(SUM(estimated_cost), 0.0)                  AS total_cost_usd,
                        COALESCE(AVG(latency_ms), 0)::INT                   AS avg_latency_ms,
                        COUNT(*) FILTER (WHERE event_type = 'llm_fallback') AS fallback_count,
                        COUNT(*) FILTER (WHERE event_type = 'transcription') AS transcription_count,
                        COUNT(*) FILTER (WHERE event_type = 'image_analysis') AS image_count
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                """, (start_date, end_date) + biz_params_pre)
                row = cur.fetchone()
                total_events = (row[0] or 1)
                fallback_count = row[6] or 0
                dashboard["kpis"] = {
                    "total_events": row[0],
                    "unique_conversations": row[1],
                    "active_businesses": row[2],
                    "total_tokens": row[3],
                    "total_cost_usd": round(row[4], 6),
                    "avg_latency_ms": row[5],
                    "fallback_rate_pct": round(fallback_count / total_events * 100, 2),
                    "transcription_events": row[7],
                    "image_analysis_events": row[8],
                }

                # Performance: latencies, by tool, events per hour, fallback daily
                cur.execute(f"""
                    SELECT
                        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms)::INT AS p50,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::INT AS p95,
                        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms)::INT AS p99,
                        MAX(latency_ms)                                                 AS max_ms
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                """, (start_date, end_date) + biz_params_pre)
                p = cur.fetchone()
                dashboard["performance"]["latency_percentiles_ms"] = {"p50": p[0], "p95": p[1], "p99": p[2], "max": p[3]}

                cur.execute(f"""
                    SELECT tool_name, AVG(latency_ms)::INT AS avg_ms, COUNT(*) AS calls
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                      AND tool_name IS NOT NULL
                    {biz_filter}
                    GROUP BY tool_name
                    ORDER BY avg_ms DESC
                """, (start_date, end_date) + biz_params_pre)
                dashboard["performance"]["latency_by_tool"] = [
                    {"tool": r[0], "avg_latency_ms": r[1], "calls": r[2]} for r in cur.fetchall()
                ]

                cur.execute(f"""
                    SELECT DATE_TRUNC('hour', timestamp) AS hour, COUNT(*) AS events
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                    GROUP BY hour
                    ORDER BY hour
                """, (start_date, end_date) + biz_params_pre)
                dashboard["performance"]["events_per_hour"] = [{"hour": r[0].isoformat(), "events": r[1]} for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT
                        DATE(timestamp) AS day,
                        COUNT(*) FILTER (WHERE event_type = 'llm_fallback') AS fallbacks,
                        COUNT(*) AS total
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                    GROUP BY day ORDER BY day
                """, (start_date, end_date) + biz_params_pre)
                dashboard["performance"]["fallback_rate_daily"] = [
                    {"date": str(r[0]), "fallbacks": r[1], "total": r[2], "rate_pct": round(r[1] / max(r[2], 1) * 100, 2)}
                    for r in cur.fetchall()
                ]

                # Costs
                cur.execute(f"""
                    SELECT DATE(timestamp) AS day,
                           SUM(estimated_cost)             AS cost,
                           SUM(input_tokens + output_tokens) AS tokens
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                    GROUP BY day ORDER BY day
                """, (start_date, end_date) + biz_params_pre)
                rows_daily = cur.fetchall()
                dashboard["costs"]["daily"] = [{"date": str(r[0]), "cost_usd": round(r[1] or 0, 6), "tokens": r[2] or 0} for r in rows_daily]
                if rows_daily:
                    avg_daily_cost = sum(r[1] or 0 for r in rows_daily) / len(rows_daily)
                    dashboard["costs"]["monthly_projection_usd"] = round(avg_daily_cost * 30, 4)
                else:
                    dashboard["costs"]["monthly_projection_usd"] = 0.0

                cur.execute(f"""
                    SELECT model_name,
                           SUM(estimated_cost)               AS cost,
                           SUM(input_tokens)                  AS input_t,
                           SUM(output_tokens)                 AS output_t,
                           COUNT(*)                           AS calls
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                      AND model_name IS NOT NULL
                    {biz_filter}
                    GROUP BY model_name
                    ORDER BY cost DESC
                """, (start_date, end_date) + biz_params_pre)
                dashboard["costs"]["by_model"] = [{"model": r[0], "cost_usd": round(r[1] or 0, 6), "input_tokens": r[2] or 0, "output_tokens": r[3] or 0, "calls": r[4]} for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT event_type, SUM(estimated_cost) AS cost, COUNT(*) AS calls
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                    GROUP BY event_type ORDER BY cost DESC
                """, (start_date, end_date) + biz_params_pre)
                dashboard["costs"]["by_event_type"] = [{"type": r[0], "cost_usd": round(r[1] or 0, 6), "calls": r[2]} for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT COALESCE(AVG(output_tokens::float / NULLIF(input_tokens, 0)), 0)
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                      AND event_type NOT IN ('transcription', 'image_analysis')
                    {biz_filter}
                """, (start_date, end_date) + biz_params_pre)
                dashboard["costs"]["avg_output_input_ratio"] = round((cur.fetchone()[0] or 0), 3)

                # Security
                cur.execute(f"""
                    SELECT COUNT(*) FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                      AND tool_name = 'solicitar_atencion_humana'
                    {biz_filter}
                """, (start_date, end_date) + biz_params_pre)
                hitl_count = cur.fetchone()[0] or 0
                dashboard["security"]["hitl_escalations"] = hitl_count
                dashboard["security"]["hitl_rate_pct"] = round(hitl_count / total_events * 100, 2)

                try:
                    config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config_negocios.json')
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                    enabled_count = sum(1 for v in config_data.values() if isinstance(v, dict) and v.get('enabled', True))
                    disabled_count = len(config_data) - enabled_count
                    dashboard["security"]["businesses_enabled"] = enabled_count
                    dashboard["security"]["businesses_disabled"] = disabled_count
                except Exception:
                    dashboard["security"]["businesses_enabled"] = None
                    dashboard["security"]["businesses_disabled"] = None

                cur.execute(f"""
                    SELECT tool_name, COUNT(*) AS errors
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                      AND event_type = 'tool_error'
                    {biz_filter}
                    GROUP BY tool_name ORDER BY errors DESC
                    LIMIT 10
                """, (start_date, end_date) + biz_params_pre)
                dashboard["security"]["tool_errors"] = [{"tool": r[0], "errors": r[1]} for r in cur.fetchall()]

                # Usage
                cur.execute(f"""
                    SELECT DATE(timestamp) AS day, COUNT(DISTINCT thread_id) AS users
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                    GROUP BY day ORDER BY day
                """, (start_date, end_date) + biz_params_pre)
                dashboard["usage"]["daily_unique_users"] = [{"date": str(r[0]), "users": r[1]} for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT tool_name, COUNT(*) AS calls
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                      AND tool_name IS NOT NULL
                    {biz_filter}
                    GROUP BY tool_name ORDER BY calls DESC
                    LIMIT 15
                """, (start_date, end_date) + biz_params_pre)
                dashboard["usage"]["top_tools"] = [{"tool": r[0], "calls": r[1]} for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT event_type, COUNT(*) AS count
                    FROM analytics_events
                    WHERE timestamp >= %s AND timestamp < %s
                    {biz_filter}
                    GROUP BY event_type ORDER BY count DESC
                """, (start_date, end_date) + biz_params_pre)
                dashboard["usage"]["event_type_distribution"] = [{"type": r[0], "count": r[1]} for r in cur.fetchall()]

                if not business_id:
                    cur.execute("""
                        SELECT
                            business_id,
                            COUNT(*)                                            AS events,
                            COUNT(DISTINCT thread_id)                           AS conversations,
                            COALESCE(SUM(estimated_cost), 0)                    AS cost_usd,
                            COALESCE(AVG(latency_ms), 0)::INT                   AS avg_latency_ms,
                            COUNT(*) FILTER (WHERE event_type = 'llm_fallback') AS fallbacks
                        FROM analytics_events
                        WHERE timestamp >= %s AND timestamp < %s
                        GROUP BY business_id
                        ORDER BY cost_usd DESC
                    """, (start_date, end_date))
                    dashboard["businesses"] = [
                        {
                            "business_id": r[0],
                            "events": r[1],
                            "conversations": r[2],
                            "cost_usd": round(r[3], 6),
                            "avg_latency_ms": r[4],
                            "fallback_rate_pct": round(r[5] / max(r[1], 1) * 100, 2),
                        }
                        for r in cur.fetchall()
                    ]

        logger.info(f"[DASHBOARD] Respuesta generada exitosamente para periodo {start_date.date()} → {end_date.date()}")
        return jsonify(dashboard), 200

    except ValueError:
        return jsonify({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}), 400
    except psycopg.errors.UndefinedTable as e:
        logger.warning(f"[DASHBOARD] Tabla no encontrada: {e}")
        dashboard["notice"] = "No analytics data available (table missing)"
        return jsonify(dashboard), 200
    except Exception as e:
        logger.exception(f"🔴 [DASHBOARD] Error generando dashboard: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/borrar_memoria', methods=['DELETE'])
def borrar_memoria():
    """Borra la memoria (checkpoints/blobs) de un usuario en un negocio."""

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

        pool = get_pool()
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


# ==============================================================================
# ENDPOINTS DE GESTIÓN DE CLIENTES (config_negocios.json)
# ==============================================================================

@admin_bp.route('/get-tools', methods=['GET'])
def listar_tools():
    """Lista las herramientas disponibles y los clientes que las usan.

    ---
    tags:
      - admin
    responses:
      200:
        description: List of tools
      500:
        description: Server error
    """

    try:
        tools = get_agent_tools()
        logger.info(f"📋 Listando {len(tools)} herramientas (raw objects)")

        # Obtener clientes que usan cada tool (desde config hot-reload)
        config = get_app_configs()
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


@admin_bp.route('/config/clientes', methods=['GET'])
def listar_clientes():
    """Obtiene la lista de clientes (config_negocios.json).

    ---
    tags:
      - admin
    responses:
      200:
        description: Clients config
      500:
        description: Server error
    """
    try:

        config = get_app_configs()

        logger.info(f"📋 Listando {len(config)} clientes")
        return jsonify(config), 200
        
    except Exception as e:
        logger.exception(f"🔴 Error listando clientes: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/config/clientes/<business_id>', methods=['GET'])
def obtener_cliente(business_id):
    """Obtiene la configuración de un cliente específico.

    ---
    tags:
      - admin
    parameters:
      - in: path
        name: business_id
        type: string
        required: true
    responses:
      200:
        description: Client config
      404:
        description: Client not found
    """
    try:

        config = get_app_configs()
        
        if business_id not in config:
            logger.warning(f"⚠️ Cliente {business_id} no encontrado")
            return jsonify({"error": f"Cliente {business_id} no existe"}), 404
        
        logger.info(f"📄 Obteniendo configuración de cliente {business_id}")
        return jsonify(config[business_id]), 200
        
    except Exception as e:
        logger.exception(f"🔴 Error obteniendo cliente {business_id}: {e}")
        return jsonify({"error": str(e)}), 500


@admin_bp.route('/config/clientes/<business_id>', methods=['PUT'])
def actualizar_cliente_completo(business_id):
    """Reemplaza completamente la configuración de un cliente.

    ---
    tags:
      - admin
    parameters:
      - in: path
        name: business_id
        type: string
        required: true
      - in: body
        name: body
        schema:
          type: object
          example:
            nombre: "Nueva Tienda Actualizada"
            ttl_sesion_minutos: 120
            admin_phone: "549112223334"
            system_prompt:
              - "Eres un asistente virtual..."
    responses:
      200:
        description: Updated
      400:
        description: Missing data
      404:
        description: Client not found
    """
    try:
        config = get_app_configs()
        
        if business_id not in config:
            logger.warning(f"⚠️ Cliente {business_id} no encontrado")
            return jsonify({"error": f"Cliente {business_id} no existe"}), 404
        
        # Obtener datos del request
        nuevos_datos = request.json
        if not nuevos_datos:
            return jsonify({"error": "No se enviaron datos"}), 400
        
        # Validar campos requeridos
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
        
        config_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'config_negocios.json')

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


@admin_bp.route('/config/clientes/<business_id>', methods=['PATCH'])
def actualizar_cliente_parcial(business_id):
    """Actualiza parcialmente la configuración de un cliente.

    ---
    tags:
      - admin
    parameters:
      - in: path
        name: business_id
        type: string
        required: true
      - in: body
        name: body
        schema:
          type: object
          example:
            nombre: "cliente-test-renovado"
            ttl_sesion_minutos: 15
    responses:
      200:
        description: Updated
      400:
        description: Missing data
      404:
        description: Client not found
    """
    try:
        config = get_app_configs()
        
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
        
        config_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'config_negocios.json')

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


@admin_bp.route('/config/clientes/<business_id>', methods=['DELETE'])
def eliminar_cliente(business_id):
    """Elimina un cliente de la configuración.

    ---
    tags:
      - admin
    parameters:
      - in: path
        name: business_id
        type: string
        required: true
    responses:
      200:
        description: Deleted
      404:
        description: Client not found
    """
    try:
        config = get_app_configs()
        
        if business_id not in config:
            logger.warning(f"⚠️ Cliente {business_id} no encontrado")
            return jsonify({"error": f"Cliente {business_id} no existe"}), 404
        
        # Guardar copia antes de eliminar
        cliente_eliminado = config[business_id]
        
        # Eliminar
        del config[business_id]
        
        config_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'config_negocios.json')

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


@admin_bp.route('/config/clientes', methods=['POST'])
def crear_cliente():
    """Crea un nuevo cliente en la configuración.

    ---
    tags:
      - admin
    parameters:
      - in: body
        name: body
        schema:
          type: object
          required:
            - business_id
            - nombre
            - ttl_sesion_minutos
            - admin_phone
          example:
            business_id: "cliente-test"
            nombre: "Nueva Tienda"
            ttl_sesion_minutos: 60
            admin_phone: "5491134567890"
            system_prompt:
              - "Eres un asistente virtual..."
    responses:
      201:
        description: Created
      400:
        description: Missing data
      409:
        description: Already exists
    """
    try:
        config = get_app_configs()
        
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
            "tools_habilitadas": nuevos_datos.get('tools_habilitadas', []),
			"thread_id_router": {"default": {"route": "lang_graph", "priority": 1}}
        }
        
        # Agregar a la configuración
        config[business_id] = nuevo_cliente

        config_path = os.path.join(os.path.dirname(__file__), '..', 'services', 'config_negocios.json')

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


@admin_bp.route('/ver-grafo', methods=['GET'])
def ver_grafo_png():
    """Obtiene el grafo de estados del agente en formato PNG para visualización.

    ---
    tags:
      - admin
    produces:
      - image/png
    responses:
      200:
        description: PNG image
      500:
        description: Error generating graph
    """
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
        logger.exception(f"🔴 Error generando grafo: {e}")
        return jsonify({"error": str(e)}), 500



@admin_bp.route("/ddos-stats", methods=['GET'])
def ddos_stats():
    """Endpoint de estadísticas de protección DDoS

    ---
    tags:
      - admin
    produces:
      - application/json
    responses:
      200:
        description: JSON response with DDoS stats
      500:
        description: Error generating DDoS stats
    """
    DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"
    if not DDOS_PROTECTION_ENABLED or not ddos_protection:
        return jsonify({"enabled": False, "message": "DDoS protection disabled"})
    return jsonify({"enabled": True, "stats": ddos_protection.get_stats()})