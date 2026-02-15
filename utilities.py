import os
import json
import time
from datetime import datetime, timezone, timedelta
from langgraph.checkpoint.postgres import PostgresSaver
from loguru import logger

# ==============================================================================
# 0. CARGAR CONFIGURACIONES DESDE JSON
# ==============================================================================
# Variables globales internas para caché
_CONFIG_CACHE = {}
_LAST_MTIME = 0
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config_negocios.json')

def obtener_configuraciones():
    """
    Retorna la configuración. Si el archivo cambió en disco, recarga automáticamente (hot reload).
    """
    global _CONFIG_CACHE, _LAST_MTIME

    try:
        # 1. Obtenemos la fecha de modificación actual del archivo
        current_mtime = os.path.getmtime(_CONFIG_PATH)

        # 2. Si la fecha es distinta a la última que leímos, recargamos
        if current_mtime != _LAST_MTIME:
            logger.info("🔄 Detectado cambio en config_negocios.json. Recargando...")
            
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                nuevas_configuraciones = json.load(f)
            
            # Validación simple (opcional)
            if not isinstance(nuevas_configuraciones, dict):
                raise ValueError("El JSON debe ser un diccionario.")

            # Actualizamos caché y timestamp
            _CONFIG_CACHE = nuevas_configuraciones
            _LAST_MTIME = current_mtime
            
            logger.info(f"✅ Configuración recargada: {len(_CONFIG_CACHE)} negocios.")
            
            # (Opcional) Regenerar herramientas si cambian dinámicamente
            # obtener_todas_las_tools() 

        return _CONFIG_CACHE

    except Exception as e:
        logger.exception(f"🔴 Error leyendo config en caliente: {e}")
        # En caso de error, devolvemos lo que teníamos antes para no romper la app
        return _CONFIG_CACHE


def es_horario_laboral(info_negocio) -> tuple[bool, str]:
    ahora = datetime.now()
    logger.debug(f"⏰ Verificando horario laboral para negocio: {info_negocio}")
    fuera_de_servicio_activo = info_negocio.get('fuera_de_servicio', {}).get('activo', False) if info_negocio else False
    horario_inicio = info_negocio.get('fuera_de_servicio', {}).get('horario_inicio', '09:00') if info_negocio else '09:00'
    horario_fin = info_negocio.get('fuera_de_servicio', {}).get('horario_fin', '18:00') if info_negocio else '18:00'
    dias_laborales = info_negocio.get('fuera_de_servicio', {}).get('dias_laborales', [1, 2, 3, 4, 5]) if info_negocio else [1, 2, 3, 4, 5]
    mensaje = info_negocio.get('fuera_de_servicio', {}).get('mensaje', []) if info_negocio else ''
    logger.info(f"💼 Horario comercial: de {horario_inicio} a {horario_fin}hs. ({obtener_nombres_dias(dias_laborales)})")

    if fuera_de_servicio_activo == False:
        return True, ""  # Si no está activo el fuera de servicio, siempre es horario laboral

    # Parsear horas configuradas (formato HH:MM) y días (lista de números)
    try:
        start_hour = int(horario_inicio.split(':')[0])
    except Exception:
        start_hour = 9
    try:
        end_hour = int(horario_fin.split(':')[0])
    except Exception:
        end_hour = 18

    try:
        # Convertir lista de números (1-7) a índices de weekday (0-6)
        if isinstance(dias_laborales, list):
            allowed_weekdays = [int(d) - 1 for d in dias_laborales if isinstance(d, (int, str)) and 1 <= int(d) <= 7]
        elif isinstance(dias_laborales, str):
            allowed_weekdays = [int(d.strip()) - 1 for d in dias_laborales.split(',') if d.strip().isdigit()]
        else:
            allowed_weekdays = [0, 1, 2, 3, 4]  # Lunes a Viernes por defecto
    except Exception:
        allowed_weekdays = [0, 1, 2, 3, 4]

    if isinstance(mensaje, list):
        mensaje_unido = ' '.join(mensaje)  # Une los strings con espacios
    else:
        mensaje_unido = mensaje

    if mensaje_unido:
        msg = mensaje_unido 
    else:
        msg = f"⏰ Actualmente estamos fuera de servicio. Por favor, contáctanos de {horario_inicio} a {horario_fin}hs. ({obtener_nombres_dias(dias_laborales)}). ¡Gracias por tu comprensión! 👋"
    
    return (ahora.weekday() in allowed_weekdays) and (start_hour <= ahora.hour < end_hour), msg


def obtener_nombres_dias(dias_laborales=[1, 2, 3, 4, 5]) -> str:
    """
    Convierte una lista de números de días (1=Lunes, 2=Martes, etc.) a nombres legibles.
    
    Args:
        dias_laborales: String con números separados por coma (ej: "1,2,3,4,5") o lista de enteros
    
    Returns:
        String con nombres de días (ej: "Lunes a Viernes")
    """
    try:
        # Mapeo de números a nombres de días (1=Lunes, 7=Domingo)
        dias_nombres = {
            1: "Lunes",
            2: "Martes", 
            3: "Miércoles",
            4: "Jueves",
            5: "Viernes",
            6: "Sábado",
            7: "Domingo"
        }
        
        # Manejar tanto strings como listas
        if isinstance(dias_laborales, list):
            dias_nums = [int(d) for d in dias_laborales if isinstance(d, (int, str)) and str(d).isdigit()]
        elif isinstance(dias_laborales, str):
            # Parsear la lista de días desde string
            dias_nums = []
            for d in dias_laborales.split(','):
                d = d.strip()
                if d.isdigit():
                    num = int(d)
                    if 1 <= num <= 7:
                        dias_nums.append(num)
        else:
            # Si no es ni string ni lista, intentar convertir
            dias_nums = [int(dias_laborales)] if str(dias_laborales).isdigit() else []
        
        if not dias_nums:
            return "días laborables"
        
        # Ordenar los días
        dias_nums.sort()
        
        # Convertir a nombres
        dias_nombres_lista = [dias_nombres[num] for num in dias_nums]
        
        # Si son días consecutivos, mostrar como rango
        if len(dias_nums) > 1 and dias_nums == list(range(dias_nums[0], dias_nums[-1] + 1)):
            if len(dias_nums) == 5 and dias_nums == [1, 2, 3, 4, 5]:  # Lunes a Viernes
                return "de Lunes a Viernes"
            elif len(dias_nums) == 7:  # Todos los días
                return "todos los días"
            else:
                return f"de {dias_nombres_lista[0]} a {dias_nombres_lista[-1]}"
        
        # Si no son consecutivos, listar separados por coma
        if len(dias_nombres_lista) == 1:
            return dias_nombres_lista[0]
        elif len(dias_nombres_lista) == 2:
            return f"{dias_nombres_lista[0]} y {dias_nombres_lista[1]}"
        else:
            return ", ".join(dias_nombres_lista[:-1]) + f" y {dias_nombres_lista[-1]}"
            
    except Exception as e:
        logger.exception(f"Error convirtiendo días laborales: {e}")
        return "días laborables"


def extraer_datos_respuesta(respuesta):
    """
    Extrae datos de cualquier tipo de respuesta (Flask, Requests, Dict, String).
    SIN USO
    """
    try:
        logger.debug(f"🔍 Extrayendo datos de respuesta tipo: {type(respuesta)}")

        # TIPO 1: Diccionario directo
        if isinstance(respuesta, dict):
            return respuesta

        # TIPO 2: Objeto Response de Flask (El que te dio error)
        if hasattr(respuesta, 'get_data'):
            try:
                # Leemos el texto crudo del cuerpo de la respuesta
                texto_json = respuesta.get_data(as_text=True)
                if texto_json:
                    return json.loads(texto_json)
            except Exception as e:
                logger.exception(f"⚠️ Error leyendo data de Flask Response: {e}")

        # TIPO 3: Objeto Response de Requests (HTTP externo)
        if hasattr(respuesta, 'json'):
            try:
                if callable(respuesta.json):
                    return respuesta.json()
                else:
                    return respuesta.json
            except:
                pass

        # TIPO 4: Fallback genérico (Intentar leer atributo .text o .data)
        texto_crudo = None
        if hasattr(respuesta, 'text'): # Requests
            texto_crudo = respuesta.text
        elif hasattr(respuesta, 'data'): # Werkzeug bytes
            texto_crudo = respuesta.data.decode('utf-8')
            
        if texto_crudo:
            return json.loads(texto_crudo)

    except Exception as e:
        logger.exception(f"🔴 Error crítico extrayendo JSON: {e}")
        return None

    return None



def gestionar_expiracion_sesion(pool, thread_id: str, ttl_minutos: int):
    """
    Verifica si la última interacción fue hace más de 'ttl_minutos'.
    Si es así, BORRA la memoria (checkpoints) de ese thread.
    Retorna True si se reseteó la memoria, False si continúa la charla.
    """
    if ttl_minutos <= 0:
        return False # Si es 0, nunca expira

    # SQL para verificar la antigüedad
    sql_check = """
    SELECT created_at 
    FROM checkpoints 
    WHERE thread_id = %s 
    ORDER BY created_at DESC 
    LIMIT 1;
    """

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 1. Obtenemos la fecha del último checkpoint guardado
            cur.execute(sql_check, (thread_id,))
            resultado = cur.fetchone()
            
            if not resultado:
                return False # No hay historia previa, es un usuario nuevo

            # Procesamos la fecha
            last_seen = resultado[0]
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            
            # Hora actual en UTC
            ahora = datetime.now(timezone.utc)
            
            # Calculamos la diferencia
            diferencia = ahora - last_seen
            
            # 2. Comparamos
            if diferencia > timedelta(minutes=ttl_minutos):
                logger.info(f"🧹 Limpiando memoria de {thread_id}. Inactividad: {diferencia}")
                
                # A. Borrar writes
                cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
                
                # B. Borrar blobs
                cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
                
                # C. Borrar checkpoints principales
                cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
                
                return True
            
            return False