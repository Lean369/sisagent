from flask import Blueprint, request, jsonify, render_template_string, render_template
from ..db import get_pool
from loguru import logger
from ..logger_config import generar_resumen_auditoria
from datetime import datetime, timedelta
import os, json
from ..tools.tools_hitl import decodificar_token_reactivacion
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.postgres import PostgresSaver
from ..services.agent import workflow_builder # Importamos el builder, NO la app completa

hitl_tool_enable_bp = Blueprint('hitl_tool_enable', __name__)

logger.info("🚀 Starting HITL Tool Enable Blueprint...")


@hitl_tool_enable_bp.route('/reactivar_bot_web', methods=['GET'])
def reactivar_bot_web():
    """
        Reactiva al bot mediante Token Seguro (JWT) + Pantalla de Reactivación HTML
        Uso: /reactivar_bot?token=eyJ...
    """
    token = request.args.get('token')
    
    if not token:
        return "❌ Error: Falta el token de seguridad.", 400
    
    try:
        # 🤖 DETECTAR SI ES UN BOT/CRAWLER (WhatsApp, Facebook, etc.)
        user_agent = request.headers.get('User-Agent', '')
        
        # Log completo para debugging
        logger.info(f"🔍 Reactivación solicitada - User-Agent: {user_agent}")
        logger.info(f"🔍 Headers completos: {dict(request.headers)}")
        
        user_agent_lower = user_agent.lower()
        is_crawler = any([
            'whatsapp' in user_agent_lower,
            'facebookexternalhit' in user_agent_lower,
            'facebot' in user_agent_lower,
            'bot' in user_agent_lower and 'google' in user_agent_lower,
            'telegram' in user_agent_lower,
            'slackbot' in user_agent_lower,
            'preview' in user_agent_lower,
            'crawler' in user_agent_lower,
            'spider' in user_agent_lower,
            # Patrones adicionales comunes
            user_agent == '',  # User-Agent vacío suele ser crawler
            'curl' in user_agent_lower,
            'wget' in user_agent_lower,
            user_agent_lower == 'node',  # Evolution API / WhatsApp preview fetcher
            'read-aloud' in user_agent_lower,  # Google-Read-Aloud bot
            'googlebot' in user_agent_lower,  # Google crawler
        ])
        
        # Si es un crawler, devolver solo metadata (Open Graph) sin ejecutar la acción
        if is_crawler:
            logger.warning(f"🤖 CRAWLER DETECTADO: {user_agent[:150]} - Bloqueando reactivación automática")
            
            # URL de la imagen para el preview (puede ser personalizada por negocio)
            preview_image_url = f"{os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')}/static/og-preview.png"
                   
            return f"""
            <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    
                    <!-- Open Graph / WhatsApp Preview -->
                    <meta property="fb:app_id" content="{os.getenv('META_APP_ID', '')}" />
                    <meta property="og:title" content="🚨 *SOLICITUD DE ASISTENCIA*" />
                    <meta property="og:description" content="Toca aquí para reactivar la conversación con el bot" />
                    <meta property="og:type" content="website" />
                    <meta property="og:image" content="{preview_image_url}" />
                    <meta property="og:image:type" content="image/png" />
                    <meta property="og:image:width" content="1200" />
                    <meta property="og:image:height" content="630" />
                    <meta property="og:image:alt" content="Reactivar Bot" />
                    
                    <!-- Twitter Card (por si acaso) -->
                    <meta name="twitter:card" content="summary_large_image" />
                    <meta name="twitter:title" content="🚨 *SOLICITUD DE ASISTENCIA*" />
                    <meta name="twitter:description" content="Toca aquí para reactivar la conversación con el bot" />
                    <meta name="twitter:image" content="{preview_image_url}" />
                    
                    <!-- SEO -->
                    <meta name="robots" content="noindex, nofollow" />
                    <title>Reactivar Bot - SisAgent</title>
                </head>
                <body style="font-family: sans-serif; text-align: center; padding: 40px; background: #f5f5f5;">
                    <h1 style="color: #666;">⚠️ Preview Mode</h1>
                    <p style="color: #999;">Este enlace debe ser abierto manualmente para activar la acción.</p>
                    <p style="color: #ccc; font-size: 12px; margin-top: 40px;">Bot detection active</p>
                </body>
            </html>
            """, 200
        
        # 1. Decodificar y Validar (Si esto pasa, los datos son auténticos)
        logger.info(f"✅ Usuario real detectado (no crawler) - User-Agent: {user_agent[:100]}")
        business_id, user_id = decodificar_token_reactivacion(token)

        thread_id = f"{business_id}:{user_id}"
        
        # 2. Lógica de Reactivación (Igual que antes)
        logger.info(f"🔓 Token validado. Reactivando {thread_id}")

        if ejecutar_reactivar_bot(business_id, user_id):
            return f"""
            <html>
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Bot Reactivado</title>
                </head>
                <body style="font-family: sans-serif; text-align: center; padding: 80px;">
                    <h1 style="color: green;">✅ Bot Reactivado</h1>
                    <p>El cliente <b>{user_id.split('@')[0]}</b> ya puede hablar con el Bot nuevamente.</p>
                    <p style="color: #666;">Negocio: {thread_id.split(':')[0]}</p>
                    <p style="color: #666;"><b>Puedes cerrar esta ventana.</b></p>
                    <p id="message" style="color: #666; margin-top: 20px;"></p>
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


@hitl_tool_enable_bp.route('/reactivar_bot', methods=['POST'])
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
 
 
def ejecutar_reactivar_bot(business_id: str, user_id: str) -> bool:
    """
        Función para ejecutar la reactivación del bot. 
        Se puede llamar desde un script o tarea programada.
    """
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

        pool = get_pool()
        with pool.connection() as conn:
            checkpointer = PostgresSaver(conn)
            # Usamos update_state para inyectar el mensaje sin ejecutar el LLM
            # Esto simplemente agrega el mensaje al historial
            workflow_builder.compile(checkpointer=checkpointer).update_state(
                config,
                {"messages": [mensaje_reactivacion]},
                as_node="chatbot" # O el nodo que corresponda
            )
        
        client_id = thread_id.split(':')[1].split('@')[0] if thread_id else "unknown"
        msg = f"[---TOOL---] 🔧 ID: {client_id} - MSG: ACCIÓN ADMINISTRATIVA: BOT_REACTIVADO"
        generar_resumen_auditoria(business_id, msg)
        logger.info(f"Bot reactivado exitosamente para {thread_id}")
        return True

    except Exception as e:
        logger.error(f"🔴 Error ejecutando reactivación del bot: {e}")
        return False
