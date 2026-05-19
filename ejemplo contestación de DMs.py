# ejemplo contestación de DMs
from flask import request, jsonify
import logging

logger = logging.getLogger(__name__)

@app.route('/webhook/instagram', methods=['POST'])
def webhook_instagram_receiver():
    data = request.json
    
    # 1. Validamos que el evento venga de Instagram
    if data.get("object") == "instagram":
        for entry in data.get("entry", []):
            page_id = entry.get("id") # Este es el ID de la cuenta receptora
            
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event.get("sender", {}).get("id")
                
                # 🚀 CASO A: Es un mensaje de texto real (Lo que tu bot necesita)
                if "message" in messaging_event:
                    mensaje_data = messaging_event["message"]
                    
                    # FILTRO CRÍTICO: Evitar que el bot se responda a sí mismo
                    if mensaje_data.get("is_echo"):
                        logger.debug("Mensaje ignorado: Es un echo (mensaje enviado por nosotros).")
                        continue
                        
                    texto = mensaje_data.get("text")
                    mid = mensaje_data.get("mid")
                    
                    if texto:
                        # ¡AQUÍ ES DONDE LLAMAS A TU FUNCIÓN!
                        # Ahora sí tienes la garantía de que 'texto' existe
                        procesar_y_responder_ig_dm(page_id, sender_id, texto, mid)
                    elif "attachments" in mensaje_data:
                        logger.info("El usuario envió una imagen o audio.")
                        # Aquí podrías derivar a una función que procese imágenes
                        
                # 🚀 CASO B: Es el payload que me compartiste (message_edit)
                elif "message_edit" in messaging_event:
                    logger.info(f"Evento ignorado: El usuario {sender_id} editó o eliminó un mensaje.")
                    continue
                    
                # 🚀 CASO C: Eventos de lectura (El usuario clavó el visto)
                elif "read" in messaging_event:
                    logger.debug(f"El usuario {sender_id} leyó nuestro mensaje.")
                    continue
                    
    # Meta siempre exige que le devuelvas un 200 OK rápido, 
    # o de lo contrario seguirá reintentando enviar el mismo webhook
    return "EVENT_RECEIVED", 200
    
def enviar_dm_instagram(recipient_id: str, mensaje: str, access_token: str = None):
    """Envía un mensaje directo de Instagram usando la Graph API de Meta"""
    try:
        # Para un SaaS multi-cliente, el token idealmente viene de tu BD, 
        # pero mantenemos tu fallback al .env
        token = access_token or os.getenv('INSTAGRAM_ACCESS_TOKEN')
        
        if not token:
            logger.error("❌ INSTAGRAM_ACCESS_TOKEN no configurado")
            return False

        # 🚀 CAMBIO CLAVE: Usamos 'me/messages' en lugar del ID explícito
        url = "https://graph.facebook.com/v18.0/me/messages"

        # Límite de 1000 caracteres para IG DM
        mensaje_truncado = mensaje[:1000]

        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": mensaje_truncado},
            "messaging_type": "RESPONSE" # Válido si respondes dentro de las 24hs
        }

        # Pasamos el token en los headers (es una mejor práctica que en la URL)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=payload, timeout=10)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"📨 DM IG enviado con éxito: {result.get('message_id')}")
            return True
        else:
            logger.error(f"❌ Error API Meta ({response.status_code}): {response.text}")
            return False

    except requests.exceptions.Timeout:
        logger.error(f"🔴 Timeout al intentar enviar DM IG a {recipient_id}")
        return False
    except Exception as e:
        logger.error(f"🔴 Error inesperado en enviar_dm_instagram: {e}")
        return False