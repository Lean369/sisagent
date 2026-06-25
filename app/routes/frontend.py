from flask import Blueprint, request, jsonify, render_template_string, render_template
from ..db import get_pool
from loguru import logger
from datetime import datetime, timedelta
import os, json
from ..templates.politica_privacidad import politica_privacidad_html

frontend_bp = Blueprint('frontend', __name__)

logger.info("🚀 Starting Frontend Blueprint...")


@frontend_bp.route('/dashboard', methods=['GET'])
def ops_dashboard():
    """
        Sirve el dashboard de operaciones de la plataforma.
        Requiere header X-Admin-Token o query param ?token=<ADMIN_TOKEN> si está configurado.
        curl -sS http://localhost:5001/dashboard
    """
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if admin_token:
        token = (
            request.headers.get("X-Admin-Token", "") or
            request.args.get("token", "")
        )
        if token != admin_token:
            logger.warning(f"[DASHBOARD] Acceso no autorizado desde {request.remote_addr}")
            return jsonify({"error": "Unauthorized"}), 401

    logger.info(f"[DASHBOARD] Acceso al dashboard desde {request.remote_addr}")
    return render_template("dashboard.html")


@frontend_bp.route('/politica-privacidad')
@frontend_bp.route('/privacy')
@frontend_bp.route('/politica-de-privacidad')
def privacy_policy():
    logger.info("📄 Política de privacidad solicitada")
    return render_template_string(politica_privacidad_html)


@frontend_bp.route('/')
def home():
    base_url = os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SisAgent _ Asistente Virtual</title>
  <!-- Open Graph / WhatsApp link preview -->
  <meta property="fb:app_id"       content="{os.getenv('META_APP_ID', '')}" />
  <meta property="og:type"        content="website" />
  <meta property="og:url"         content="{base_url}/" />
  <meta property="og:title"       content="SisAgent Asistente Virtual" />
  <meta property="og:description" content="Descubrí la nueva forma de interactuar con tu negocio a través de WhatsApp" />
  <meta property="og:image"        content="{base_url}/static/og-preview.png" />
  <meta property="og:image:type"   content="image/png" />
  <meta property="og:image:width"  content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt"    content="SisAgent" />
</head>
<body style="font-family:sans-serif;text-align:center;padding:60px;">
  <img src="{base_url}/static/og-preview.png" alt="SisAgent Logo" style="width:200px;margin-bottom:30px;">
  <h1>Bienvenido a SisAgent</h1>
  <p>Política de privacidad: <a href='{base_url}/politica-privacidad'>/politica-privacidad</a></p>
</body>
</html>"""