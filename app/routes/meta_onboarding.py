from flask import Blueprint, request, jsonify
from loguru import logger
import os
import base64
import io
import json
from pydantic import BaseModel
import asyncio
import requests
import httpx
from ..templates.onboarding_coexistence import onboarding_coexistence_html


meta_onboarding_bp = Blueprint('meta_onboarding', __name__)

META_APP_ID = os.getenv("META_APP_ID", "TU_APP_ID")  # ID de tu app en Meta for Developers
META_APP_SECRET = os.getenv("META_APP_SECRET", "TU_APP_SECRET")  # Si necesitás intercambiar code por token
REDIRECT_URI = f"{os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')}/callback/whatsapp"  # Debe coincidir con Meta

class EvolutionInstanceCreate(BaseModel):
    instanceName: str
    integration: str = "WHATSAPP-BUSINESS"
    token: str  # Permanent Access Token
    number: str  # Phone Number ID (ej: "123456789012345")
    qrcode: bool = False  # No QR para Cloud API


@meta_onboarding_bp.route("/callback/whatsapp", methods=['GET'])
def whatsapp_callback():
    code = request.args.get('code')
    waba_id = request.args.get('waba_id')
    phone_number_id = request.args.get('phone_number_id')
    error = request.args.get('error')
    error_description = request.args.get('error_description')

    if error:
        logger.error(f"Error en Embedded Signup: {error} - {error_description}")
        return f"<h1>Error: {error_description}</h1><p>Contacta soporte.</p>"

    # Caso 1: Embedded Signup envía datos directamente via params (común en v4+ con helper)
    if phone_number_id and waba_id:
        logger.info(f"Recibidos directamente: Phone ID={phone_number_id}, WABA ID={waba_id}")
        import asyncio
        asyncio.run(create_evolution_instance(phone_number_id, waba_id))
        return "<h1>¡Conexión exitosa!</h1><p>Tu WhatsApp está siendo configurado en Evolution. Redirigiendo...</p>"

    # Caso 2: Viene 'code' → intercambiar por token y obtener datos (OAuth flow manual)
    if code:
        try:
            token_url = "https://graph.facebook.com/v21.0/oauth/access_token"
            params = {
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "redirect_uri": REDIRECT_URI,
                "code": code
            }
            resp = requests.get(token_url, params=params)
            resp.raise_for_status()
            token_data = resp.json()
            access_token = token_data.get("access_token")

            graph_url = f"https://graph.facebook.com/v21.0/me?fields=whatsapp_business_accounts{{phone_numbers{{id,name}}}}&access_token={access_token}"
            graph_resp = requests.get(graph_url)
            graph_resp.raise_for_status()
            data = graph_resp.json()

            waba = data.get("whatsapp_business_accounts", {}).get("data", [{}])[0]
            phone = waba.get("phone_numbers", {}).get("data", [{}])[0]
            phone_number_id = phone.get("id")
            waba_id = waba.get("id")

            if not phone_number_id:
                raise ValueError("No se encontró Phone Number ID")

            logger.info(f"Obtenido via token: Phone ID={phone_number_id}, WABA ID={waba_id}")
           
            asyncio.run(create_evolution_instance(phone_number_id, waba_id, access_token))
            return "<h1>¡Éxito!</h1><p>Instancia creada en Evolution. Podés cerrar esta ventana.</p>"

        except Exception as e:
            logger.exception("Error procesando code")
            return jsonify({"error": str(e)}), 500

    return "<h1>Callback recibido, pero faltan parámetros. Intenta de nuevo.</h1>"


@meta_onboarding_bp.route("/onboard-whatsapp", methods=['GET'])
def onboard_page():
    logger.info("🔗 Página de onboarding solicitada")
    return onboarding_coexistence_html


# Endpoint principal de onboarding: recibe code + phone_number_id + waba_id desde el frontend
# El frontend los obtiene: code via FB.login() callback, phone_number_id/waba_id via postMessage
@meta_onboarding_bp.route("/api/onboard-whatsapp", methods=['POST'])
def receive_embedded_data():
    data = request.json or {}
    code = data.get('code')
    phone_number_id = data.get('phone_number_id')
    waba_id = data.get('waba_id')
    business_id = data.get('business_id')

    if not code or not phone_number_id or not waba_id:
        return jsonify({"status": "error", "error": "Faltan datos requeridos (code, phone_number_id, waba_id)"}), 400

    logger.info(f"📨 Onboarding iniciado: Phone ID={phone_number_id}, WABA ID={waba_id}")

    try:
        # Paso 1: Intercambiar el código de autorización por un access token
        # El code tiene TTL de 30s, hacerlo de inmediato
        token_resp = requests.get(
            f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION','v21.0')}/oauth/access_token",
            params={
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "code": code
                # Nota: NO incluir redirect_uri para el flow iniciado por FB.login()
            },
            timeout=15
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError(f"No se obtuvo access_token: {token_data}")
        logger.info(f"✅ Token intercambiado para phone {phone_number_id}")

        graph_headers = {"Authorization": f"Bearer {access_token}"}

        # Paso 2: Registrar el número de teléfono para usar Cloud API
        # Esto es obligatorio para que el número pueda enviar/recibir mensajes via Cloud API
        register_resp = requests.post(
            f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION','v21.0')}/{phone_number_id}/register",
            headers=graph_headers,
            json={"messaging_product": "whatsapp", "pin": "000000"},
            timeout=15
        )
        if register_resp.status_code not in (200, 201):
            logger.warning(f"⚠️ Registro de teléfono respondió {register_resp.status_code}: {register_resp.text}")
        else:
            logger.info(f"✅ Número {phone_number_id} registrado en Cloud API")

        # Paso 3: Suscribir la app a los webhooks del WABA del cliente
        # Necesario para recibir mensajes entrantes en nuestro webhook
        subscribe_resp = requests.post(
            f"https://graph.facebook.com/{os.getenv('GRAPH_VERSION','v21.0')}/{waba_id}/subscribed_apps",
            headers=graph_headers,
            timeout=15
        )
        if subscribe_resp.status_code not in (200, 201):
            logger.warning(f"⚠️ Suscripción webhooks respondió {subscribe_resp.status_code}: {subscribe_resp.text}")
        else:
            logger.info(f"✅ App suscrita a webhooks del WABA {waba_id}")

        # Paso 4: Crear instancia en Evolution API con los datos del cliente
        import asyncio
        asyncio.run(create_evolution_instance(phone_number_id, waba_id, access_token))

        return jsonify({
            "status": "ok",
            "message": "WhatsApp onboardeado exitosamente",
            "phone_number_id": phone_number_id,
            "waba_id": waba_id
        })

    except requests.HTTPError as e:
        logger.exception(f"HTTP error en onboarding: {e.response.text if e.response else e}")
        return jsonify({"status": "error", "error": str(e)}), 500
    except Exception as e:
        logger.exception("Error en onboarding completo")
        return jsonify({"status": "error", "error": str(e)}), 500


async def create_evolution_instance(phone_number_id: str, waba_id: str, access_token: str = None):
    """
    Crea instancia en Evolution API con WHATSAPP-BUSINESS.
    Usa el permanent token (generado antes o aquí via System User).
    """
    # En producción: genera o usa un permanent token por cliente (mejor práctica)
    # Por simplicidad, asumimos que usás un token permanente de System User con acceso al WABA
    permanent_token = access_token or "TU_PERMANENT_TOKEN_CON_PERMISOS_AL_WABA_DEL_CLIENTE"

    payload = {
        "instanceName": f"cliente-{phone_number_id[-6:]}",  # Nombre único
        "integration": "WHATSAPP-BUSINESS",
        "token": permanent_token,
        "number": phone_number_id,  # ¡Este es el Phone Number ID!
        "qrcode": False,            # No QR para Cloud API
        "webhook": {
            "url": f"{os.getenv('APP_BASE_URL', 'https://sisagent.sisnova.org')}/webhook/evoapi",
            "enabled": True,
            "events": ["MESSAGES_UPSERT"]
            }
    }

    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{EVOLUTION_API_URL}/instance/create",
                json=payload,
                headers=headers,
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Instancia creada en Evolution: {data}")
            # Aquí podés guardar en tu DB: cliente → instanceName, instanceKey, etc.
        except httpx.HTTPStatusError as e:
            logger.error(f"Error creando instancia: {e.response.text}")
            raise

