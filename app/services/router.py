from loguru import logger
from ..services.agent import procesar_msg_agente_ia
from ..services.evolution_multimedia import receipt_extractor_evolution, procesar_audio_evolution
from ..services.google_sheet_receipts.google_sheets import write_record_sheets


def route_text_message(business_id: str, user_id: str, mensaje: str, client_name: str = "", info_negocio: dict = None) -> str:
    """
        Procesa un mensaje usando Agente IA y devuelve el resultado como texto
    """
    try:
        # 1. Datos obligatorios      
        if not user_id or not business_id or not mensaje or info_negocio is None:
            logger.error("❌ Faltan IDs o mensaje en route_text_message: business_id={}, user_id={}, mensaje={}".format(business_id, user_id, mensaje))
            return None # Retorna None o un string vacío para que el worker sepa que falló

        # 2. Crear Thread ID Único (Aislamiento de Memoria). Esto asegura que Postgres guarde la conversación en un "cajón" único
        thread_id = f"{business_id}:{user_id}"

        logger.debug(f"Procesando mensaje para thread_id={thread_id}")
        
        # 3. Configuración para LangGraph
        # Pasamos dentro de 'configurable' toda la info de la conversación para que el nodo lo pueda leer
        config = {
            "configurable": {
                "thread_id": thread_id,
                "business_id": business_id,
                "client_name": client_name,
                "ttl_minutos": info_negocio.ttl_minutos if info_negocio and hasattr(info_negocio, 'ttl_minutos') else 60  # Valor por defecto si no se proporciona
            },
            "recursion_limit": 15
        }
        
        # ROUTER: Aquí es donde decidimos a qué ruta de procesamiento enviar el mensaje, dependiendo del negocio o cliente
        route_name, _ = router(thread_id, info_negocio)

        if route_name == "receipt_extractor":
            response = "Para procesar tu recibo, por favor envíame una foto del comprobante de transferencia. 📸"
            logger.info(f"🚏 Ruta personalizada 'receipt_extractor' para thread_id: {thread_id}. Respuesta simulada.")
        else:
            logger.info(f"📍 No se encontró ruta personalizada para thread_id: {thread_id}. Usando ruta por defecto.")
            response = procesar_mensaje_agente_ia(thread_id, mensaje, config)

        # Asegurar que siempre devolvemos un string (evita errores si response es dict/None)
        return str(response) if response is not None else "No pudimos procesar su solicitud."

    except Exception as e:
        logger.error(f"🔴 Error: {e}") 
        return  "No se pudo procesar su solicitud."


def route_image_message(business_id: str, user_id: str, mensaje: str, client_name: str = "", info_negocio: dict = None) -> str:
    """
        Procesa la imagen con IA vision y devuelve el resultado como texto
    """
    try:
        # 1. Datos obligatorios      
        if not user_id or not business_id or not mensaje or info_negocio is None:
            logger.error("❌ Faltan IDs o mensaje en route_image_message: business_id={}, user_id={}, mensaje={}".format(business_id, user_id, mensaje))
            return None # Retorna None o un string vacío para que el worker sepa que falló

        # 2. Crear Thread ID Único (Aislamiento de Memoria). Esto asegura que Postgres guarde la conversación en un "cajón" único
        thread_id = f"{business_id}:{user_id}"

        logger.debug(f"Procesando mensaje para thread_id={thread_id}")
        
        # 3. Configuración para LangGraph
        # Pasamos dentro de 'configurable' toda la info de la conversación para que el nodo lo pueda leer
        config = {
            "configurable": {
                "thread_id": thread_id,
                "business_id": business_id,
                "client_name": client_name,
                "ttl_minutos": info_negocio.ttl_minutos if info_negocio and hasattr(info_negocio, 'ttl_minutos') else 60  # Valor por defecto si no se proporciona
            },
            "recursion_limit": 15
        }
        
        route_name, extra = router(thread_id, info_negocio)

        out =  "⚠️ No se pudo registrar el recibo. Reintenta nuevamente. 📄"

        if route_name == "receipt_extractor":
            logger.info(f"🚏 Ruta personalizada 'receipt_extractor' para thread_id: {thread_id}.")
            ret, response = receipt_extractor_evolution(business_id, user_id, mensaje)
            logger.debug(f"Ret: {ret}, Response: {response}, Extra: {extra}")
            if ret:
                ret, response = write_record_sheets(response, extra, thread_id)
                if ret:
                    logger.info(f"✅ Recibo registrado en Google Sheets para thread_id: {thread_id}")
                    # Asegurar que siempre devolvemos un string (evita errores si response es dict/None)
                    out = str(response) if response is not None else "No pudimos procesar su solicitud."
                else:
                    logger.warning(f"🟡 Error registrando recibo en Google Sheets para thread_id: {thread_id}")
                    out = response
            else:
                logger.warning(f"🟡 No se pudo procesar la imagen como recibo para thread_id={thread_id}. Response: {response}")
                out = response
        
        return out

    except Exception as e:
        logger.error(f"🔴 Error: {e}") 
        return  "No se pudo procesar su solicitud."


def route_audio_message(business_id: str, user_id: str, mensaje: str, client_name: str = "", info_negocio: dict = None) -> str:
    """
        Procesa el audio con transcripción IA y devuelve el resultado como texto
    """
    try:
        # 1. Datos obligatorios      
        if not user_id or not business_id or not mensaje or info_negocio is None:
            logger.error("❌ Faltan IDs o mensaje en route_audio_message: business_id={}, user_id={}, mensaje={}".format(business_id, user_id, mensaje))
            return None # Retorna None o un string vacío para que el worker sepa que falló

        # 2. Crear Thread ID Único (Aislamiento de Memoria). Esto asegura que Postgres guarde la conversación en un "cajón" único
        thread_id = f"{business_id}:{user_id}"

        logger.debug(f"Procesando mensaje para thread_id={thread_id}")
        
        # 3. Configuración para LangGraph
        # Pasamos dentro de 'configurable' toda la info de la conversación para que el nodo lo pueda leer
        config = {
            "configurable": {
                "thread_id": thread_id,
                "business_id": business_id,
                "client_name": client_name,
                "ttl_minutos": info_negocio.ttl_minutos if info_negocio and hasattr(info_negocio, 'ttl_minutos') else 60  # Valor por defecto si no se proporciona
            },
            "recursion_limit": 15
        }
        
        route_name, _ = router(thread_id, info_negocio)

        if route_name == "receipt_extractor":
            response = "Para procesar tu recibo, por favor envíame una foto del comprobante de transferencia. 📸"
            logger.info(f"🚏 Ruta personalizada 'receipt_extractor' para thread_id: {thread_id}. Respuesta simulada.")
        else:
            logger.info(f"📍 No se encontró ruta personalizada para thread_id: {thread_id}. Usando ruta por defecto.")
            transcript = procesar_audio_evolution(business_id, user_id, mensaje)
            response = procesar_mensaje_agente_ia(thread_id, transcript, config)

        # Asegurar que siempre devolvemos un string (evita errores si response es dict/None)
        return str(response) if response is not None else "No pudimos procesar su solicitud."

    except Exception as e:
        logger.error(f"🔴 Error: {e}") 
        return  "No se pudo procesar su solicitud."


def router(thread_id: str, info_negocio: dict = None) -> tuple:
    # ROUTER: Aquí es donde decidimos a qué ruta de procesamiento enviar el mensaje, dependiendo del negocio o cliente
    thread_id_router = None

    thread_id_router = getattr(info_negocio, 'thread_id_router')

    # Si no hay configuración, usamos un valor por defecto compatible
    if thread_id_router is None:
        thread_id_router = {"default": {"route": "default", "priority": 1, "extra": []}}

    if not isinstance(thread_id_router, dict):
        thread_id_router = {"default": {"route": "default", "priority": 1, "extra": []}}

    route = thread_id_router.get(thread_id, "default")

    route_name = route.get('route', 'default')
    extra = route.get('extra', [])

    return route_name, extra


def procesar_mensaje_agente_ia(thread_id, mensaje: str, config: dict) -> str:
    """
        Función de procesamiento de mensaje con el agente IA
    """
    try:
        resultado = procesar_msg_agente_ia(mensaje, config)     

        response = resultado.get("response")
        status = resultado.get("status")

        logger.debug(f"Respuesta recibida para {thread_id}: status={status}, response={str(response)[:50]}")

        if status == "COMPLETED" or status == "ERROR":
            logger.success(f"✅ Respuesta generada para {thread_id}: {str(response)[:50]}")
            return response
        elif status == "PAUSED":
            logger.warning(f"⏸️ Bot pausado para {thread_id}. No se generará respuesta.")
            return ""  # Retornamos cadena vacía para indicar que no se debe enviar nada al cliente
        else:
            logger.warning(f"⚠️ Respuesta desconocida con status {status} para {thread_id}: {str(response)[:50]}")
            return  "⚠️ En este momento no puedo procesar su solicitud."

    except Exception as e:
        logger.exception(f"🔴 Error crítico en procesar_msg_agente_ia: {e}")
        return "Error interno. Por favor, intenta nuevamente más tarde."