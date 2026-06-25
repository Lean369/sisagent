from loguru import logger
from evolutionapi.client import EvolutionClient  # del paquete oficial
from ..logger_config import generar_resumen_auditoria
import base64
import io
import os
from ..services.agent import transcribir_audio, analizar_imagen_con_ai, extract_transfer_receipt_data

DDOS_PROTECTION_ENABLED = os.getenv("DDOS_PROTECTION_ENABLED", "true").lower() == "true"
EVOLUTION_URL = os.environ.get("EVOLUTION_API_URL", "https://evoapi.sisnova.com.ar")
EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY")

client = EvolutionClient(base_url=EVOLUTION_URL, api_token=EVOLUTION_API_KEY)



def receipt_extractor_evolution(business_id, user_id, mensaje) -> tuple:
    """
        Procesa imágenes enviadas por Evolution API - WhatsApp SOLO Baileys:
        1. Descarga la imagen desde Evolution API
        2. Analiza la imagen con AI multimodal
        3. Responde al usuario con el análisis
    """
    try:
        logger.debug(f"[IMAGE] Procesando imagen para {user_id}, instance={business_id}")
        telefono = user_id.split("@")[0]
        
        # Usar el cliente evolutionapi para obtener la imagen en base64
        endpoint = f"chat/getBase64FromMediaMessage/{business_id}"
        payload_media = {
            "message": {
                "key": mensaje.get("key"),
                "message": mensaje.get("message")
            },
            "convertToMp4": False
        }
        
        logger.debug(f"[IMAGE] Solicitando descarga de imagen usando evolutionapi client...")
        
        try:
            response = client.post(endpoint, data=payload_media)
            
            if not response or not isinstance(response, dict):
                logger.error(f"❌ [IMAGE] Respuesta inválida del cliente: {response}")
                msg = "Disculpa, tuve problemas para procesar tu imagen. ¿Podrías describir qué necesitas? 📝"
                return False, msg
            
            base64_image = response.get("base64")
            
            if not base64_image:
                logger.error(f"❌ [IMAGE] No se recibió base64 en la respuesta: {response}")
                msg = "Disculpa, no pude procesar tu imagen. ¿Podrías describir qué necesitas? 📝"
                return False, msg
            
            # Decodificar el base64 a bytes
            image_buffer = base64.b64decode(base64_image)
            logger.info(f"[IMAGE] Imagen descargada: {len(image_buffer)} bytes")
            
            # Extraer caption si existe
            caption = mensaje.get("message", {}).get("imageMessage", {}).get("caption")
            
            # Analizar la imagen con AI
            thread_id = f"{business_id}:{user_id}"
            
            mime_type = mensaje.get("message", {}).get("documentMessage", {}).get("mimetype", "image/jpeg")
            logger.debug(f"[IMAGE] Analizando imagen con AI. thread_id={thread_id}, caption='{caption}', mime_type='{mime_type}'")
            
            ret, analisis = extract_transfer_receipt_data(image_buffer, thread_id, caption, mime_type)
            
            if ret:
                msg = f"[RCV <- EVO] 🖼️ ID: {telefono} - IMG: {caption[:50] if caption else 'sin texto'}"
                generar_resumen_auditoria(business_id, msg)
                
                # # Enviar el análisis como respuesta
                # respuesta = f"📸 He analizado tu imagen:\n\n{analisis}"
                # if caption:
                #     respuesta = f"📸 Vi tu imagen y el texto '{caption}'.\n\n{analisis}"
                
                return True, analisis
            else:
                logger.warning(f"🟡 No se pudo analizar la imagen con AI para thread_id={thread_id}."  )
                return False, analisis
                
        except Exception as api_error:
            logger.error(f"❌ [IMAGE] Error llamando API Evolution: {api_error}")
            msg = "Disculpa, tuve problemas procesando tu imagen. ¿Podrías describir qué necesitas? 📝"
            return False, msg

    except Exception as e:
        logger.error(f"🔴 Error procesando imagen background: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            msg = "Disculpa, tuve un error procesando tu imagen. ¿Podrías escribir tu consulta? 📝"
            return False, msg
        except:
            pass  # Evitar errores en cascada


def procesar_audio_evolution(business_id, user_id, mensaje) -> str:
    """
        Procesa audios enviados por Evolution API - WhatsApp SOLO Baileys:
        1. Descarga el audio desde Evolution API
        2. Decodifica el audio de base64 a bytes
        3. Transcribe el audio a texto
        4. Procesa el texto con IA
    """
    try:
        logger.debug(f"[AUDIO] Procesando audio para {user_id}, instance={business_id}")
        telefono = user_id.split("@")[0]    
        # Usar el cliente evolutionapi para obtener el audio en base64
        # https://doc.evolution-api.com/v2/en/endpoints/messages#get-media
        endpoint = f"chat/getBase64FromMediaMessage/{business_id}"
        # Evolution necesita el objeto data completo (key + message + metadata)
        payload_media = {
            "message": {
                "key": mensaje.get("key"),
                "message": mensaje.get("message")
            },
            "convertToMp4": False  # Mantener formato original (ogg opus)
        }
        
        logger.debug(f"[AUDIO] Solicitando descarga de media usando evolutionapi client...")
        
        try:
            response = client.post(endpoint, data=payload_media)
            
            if not response or not isinstance(response, dict):
                logger.error(f"❌ [AUDIO] Respuesta inválida del cliente: {response}")
                msg = "Disculpa, tuve problemas para procesar tu audio. ¿Podrías escribirlo? 📝"
                return msg
            
            base64_audio = response.get("base64")
            
            if not base64_audio:
                logger.error(f"❌ [AUDIO] No se recibió base64 en la respuesta: {response}")
                msg = "Disculpa, no pude procesar tu audio. ¿Podrías escribirlo? 📝"
                return msg
            
            # Decodificar el base64 a bytes PRIMERO
            audio_buffer = base64.b64decode(base64_audio)
            logger.info(f"[AUDIO] Audio descargado: {len(audio_buffer)} bytes")

            # 1. Transcribir (Lento)
            texto_transcrito = transcribir_audio(audio_buffer, thread_id=f"{business_id}:{user_id}")
            
            if not texto_transcrito or (isinstance(texto_transcrito, str) and not texto_transcrito.strip()):
                logger.warning("🟡 No se obtuvo transcripción válida")
                return "Disculpa, no pude entender tu audio. ¿Podrías escribir tu consulta? 📝"
            else:
                # logger.info(f"🗣️ Audio transcrito: {texto_transcrito[:50].replace('\n', ' ')}")
                msg = f"[RCV <- EVO] 🔊 ID: {telefono} - MSG: {texto_transcrito[:100].replace('\n', ' ')}"
                generar_resumen_auditoria(business_id, msg)
                return texto_transcrito
                
        except Exception as api_error:
            logger.error(f"❌ [AUDIO] Error llamando API Evolution: {api_error}")
            msg = "Disculpa, tuve problemas descargando tu audio. ¿Podrías escribirlo? 📝"
            return msg

    except Exception as e:
        logger.error(f"🔴 Error procesando audio background: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            msg = "Disculpa, tuve un error procesando tu audio. ¿Podrías escribirlo? 📝"
            return msg
        except:
            pass  # Evitar errores en cascada
