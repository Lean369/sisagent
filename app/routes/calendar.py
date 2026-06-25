from flask import Blueprint, request, jsonify
import os
import json
from loguru import logger
from ..tools.tools_calendar import authenticate_with_code

calendar_bp = Blueprint('calendar', __name__)


# Webhook para recibir código de autorización de Google Calendar OAuth
@calendar_bp.route('/oauth/calendar/callback', methods=['GET'])
def calendar_oauth_callback():
    """
    Recibe el código de autorización de Google OAuth y completa la autenticación automáticamente.
    Parámetros esperados: code, state (opcional), business_id (en state)
    """
    try:
        logger.info(f"📨 Callback OAuth recibido") #{request}")
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')
        
        logger.info(f"📨 Callback OAuth recibido - Code: {code[:20] if code else None}... State: {state}")
        
        if error:
            logger.error(f"❌ Error en OAuth: {error}")
            return f"""
            <html>
                <head><title>Error - Autorización</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>❌ Error en la autorización</h1>
                    <p>Hubo un problema: {error}</p>
                    <p>Por favor, vuelve a intentarlo desde WhatsApp.</p>
                </body>
            </html>
            """, 400
        
        if not code:
            logger.error("❌ No se recibió código de autorización")
            return """
            <html>
                <head><title>Error - Sin código</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>❌ Error</h1>
                    <p>No se recibió el código de autorización.</p>
                </body>
            </html>
            """, 400
        
        # Extraer business_id del state si está presente
        business_id = "cliente1"  # Default
        if state and ':' in state:
            parts = state.split(':')
            if len(parts) >= 2:
                business_id = parts[1]
        
        # Limpiar cualquier corrupción de caracteres (por si acaso)
        business_id = business_id.strip().rstrip(')*').strip()
        
        logger.info(f"🔐 Procesando autorización para business_id: {business_id}")

        # Autenticar y obtener credenciales
        creds = authenticate_with_code(code)
        
        # Guardar token
        if not os.path.exists("tokens_calendar"):
            os.makedirs("tokens_calendar")
        token_file = f"tokens_calendar/{business_id}_token.json"
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
        
        logger.info(f"✅ Token guardado exitosamente para {business_id}")
        
        return f"""
        <html>
            <head>
                <title>✅ Autorización Exitosa</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        margin: 0;
                        padding: 20px;
                        min-height: 100vh;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    }}
                    .container {{
                        background: white;
                        border-radius: 20px;
                        padding: 40px;
                        max-width: 500px;
                        box-shadow: 0 10px 50px rgba(0,0,0,0.3);
                        text-align: center;
                    }}
                    h1 {{
                        color: #10b981;
                        font-size: 2.5em;
                        margin: 0 0 20px 0;
                    }}
                    p {{
                        color: #64748b;
                        font-size: 1.1em;
                        line-height: 1.6;
                    }}
                    .success-icon {{
                        font-size: 5em;
                        margin-bottom: 20px;
                    }}
                    .button {{
                        background: #667eea;
                        color: white;
                        padding: 15px 30px;
                        border-radius: 10px;
                        text-decoration: none;
                        display: inline-block;
                        margin-top: 20px;
                        font-weight: bold;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="success-icon">✅</div>
                    <h1>¡Autorización Exitosa!</h1>
                    <p><strong>Tu Google Calendar está conectado.</strong></p>
                    <p>Ya puedes cerrar esta ventana y volver a WhatsApp para agendar tu cita.</p>
                    <p style="font-size: 0.9em; color: #94a3b8; margin-top: 30px;">
                        Business ID: {business_id}
                    </p>
                </div>
            </body>
        </html>
        """, 200
        
    except Exception as e:
        logger.error(f"❌ Error en callback OAuth: {e}")
        return f"""
        <html>
            <head><title>Error - Autorización</title></head>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1>❌ Error al procesar la autorización</h1>
                <p>{str(e)}</p>
                <p>Por favor, contacta con soporte.</p>
            </body>
        </html>
        """, 500