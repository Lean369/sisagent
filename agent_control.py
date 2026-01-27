from collections import defaultdict
from datetime import datetime, timedelta
import time
from threading import Lock
from typing import Optional
import logging
import os

# Configuración
RATE_LIMITER_MAX_MENSAJES = int(os.getenv("RATE_LIMITER_MAX_MENSAJES", 15))          # Mensajes permitidos
RATE_LIMITER_WINDOWS_MINUTES = int(os.getenv("RATE_LIMITER_WINDOWS_MINUTES", 1))       # Ventana de tiempo en minutos
RATE_LIMITER_COOLDOWN_MINUTES = int(os.getenv("RATE_LIMITER_COOLDOWN_MINUTES", 5))      # Tiempo de bloqueo en minutos

# Usar el logger principal configurado en agent.py
logger = logging.getLogger(os.getenv('LOGGER_NAME', 'agent'))

try:
    from external_instructions import SALUDO, DESPEDIDA, CONSULTA_PRECIOS
    if not SALUDO or not DESPEDIDA or not CONSULTA_PRECIOS:
        raise ValueError("Faltan instrucciones en external_instructions.py")
except Exception as e:
    logger.error(f"❌ Error importando external_instructions: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    # Definiciones por defecto si falla la importación
    
    SALUDO = """
¡Gracias por escribirnos!
Soy el agente automático de Sisnova 🤖

📈 ¿A qué se dedica tu empresa o emprendimiento y cuántos mensajes reciben por día??
"""
    DESPEDIDA = """
Si tienes más preguntas, no dudes en escribirme.
¡Que tengas un excelente día!! 👋
"""
    CONSULTA_PRECIOS = """
    Los planes se personalizan según tu volumen de mensajes y necesidades específicas.
En la consulta gratuita de 30 minutos analizamos tu caso particular y te armamos una propuesta a medida con precios transparentes.
¿Te gustaría agendar una reunión para que podamos darte números concretos para tu negocio?? 🎯
"""

# ==========================================
# 1. RATE LIMITING (Prevenir spam y abuso)
# ==========================================

class RateLimiter:
    """Limita mensajes por usuario para prevenir abuso"""
    
    def __init__(self, max_mensajes=10, ventana_minutos=1, cooldown_minutos=5):
        self.max_mensajes = max_mensajes
        self.ventana_segundos = ventana_minutos * 60
        self.cooldown_segundos = cooldown_minutos * 60
        self.usuarios = defaultdict(list)
        self.bloqueados = {}
        self.lock = Lock()
        logger.debug("RateLimiter inicializado: max=%s ventana_minutos=%s cooldown_minutos=%s", max_mensajes, ventana_minutos, cooldown_minutos)
    
    def puede_procesar(self, user_id: str) -> tuple[bool, str]:
        """
        Verifica si el usuario puede enviar mensajes
        
        Returns:
            (puede_procesar, mensaje_error)
        """
        with self.lock:
            ahora = time.time()
            ahora_str = datetime.fromtimestamp(ahora).strftime("%Y-%m-%d %H:%M:%S")
            logger.debug("RateLimiter check for user_id=%s at %s", user_id, ahora_str)
            
            # Verificar si está bloqueado por spam
            if user_id in self.bloqueados:
                tiempo_bloqueado = self.bloqueados[user_id]
                if ahora - tiempo_bloqueado < self.cooldown_segundos:
                    tiempo_restante = int((self.cooldown_segundos - (ahora - tiempo_bloqueado)) / 60)
                    msg = f"⚠️ Has enviado muchos mensajes seguidos. Podrás escribir nuevamente en {tiempo_restante} minutos."
                    logger.info("RateLimiter: user_id=%s blocked, remaining_minutes=%s", user_id, tiempo_restante)
                    return False, msg
                else:
                    # Desbloquear usuario
                    del self.bloqueados[user_id]
            
            # Limpiar mensajes antiguos
            self.usuarios[user_id] = [
                t for t in self.usuarios[user_id]
                if ahora - t < self.ventana_segundos
            ]
            
            # Verificar límite
            logger.debug("RateLimiter: user_id=%s has %s messages in window max_messages=%s", user_id, len(self.usuarios[user_id]), self.max_mensajes)
            if len(self.usuarios[user_id]) >= self.max_mensajes:
                self.bloqueados[user_id] = ahora
                msg = f"⚠️ Por favor espera {self.cooldown_segundos // 60} minutos."
                logger.info("RateLimiter: user_id=%s reached limit=%s", user_id, self.max_mensajes)
                return False, msg
            
            # Registrar mensaje
            self.usuarios[user_id].append(ahora)
            logger.debug("RateLimiter: user_id=%s message registered at %s", user_id, ahora_str)
            return True, ""

# Instancia global
rate_limiter = RateLimiter(max_mensajes=RATE_LIMITER_MAX_MENSAJES, ventana_minutos=RATE_LIMITER_WINDOWS_MINUTES, cooldown_minutos=RATE_LIMITER_COOLDOWN_MINUTES)


# ==========================================
# 2. CACHÉ DE RESPUESTAS (Ahorro de costos API)
# ==========================================

import hashlib
import json
from functools import lru_cache

class CacheRespuestas:
    """Cachea respuestas a preguntas frecuentes"""
    
    def __init__(self, ttl_segundos=3600):  # 1 hora
        self.cache = {}
        self.ttl = ttl_segundos
        self.lock = Lock()
    
    def _generar_key(self, mensaje: str) -> str:
        """Genera key hash del mensaje normalizado"""
        # Normalizar mensaje (minúsculas, sin espacios extra)
        normalizado = ' '.join(mensaje.lower().split())
        return hashlib.md5(normalizado.encode()).hexdigest()
    
    def obtener(self, mensaje: str) -> Optional[str]:
        """Obtiene respuesta cacheada si existe y es válida"""
        with self.lock:
            key = self._generar_key(mensaje)
            
            if key in self.cache:
                respuesta, timestamp = self.cache[key]
                # Verificar si no expiró
                if time.time() - timestamp < self.ttl:
                    logger.debug("Cache hit for key=%s mensaje_snippet=%s", key, mensaje[:50])
                    return respuesta
                else:
                    # Eliminar entrada expirada
                    logger.debug("Cache expired for key=%s", key)
                    del self.cache[key]
            
            return None
    
    def guardar(self, mensaje: str, respuesta: str):
        """Guarda respuesta en cache"""
        logger.debug("Cache guardar llamada para mensaje_snippet=%s", mensaje[:50])
        with self.lock:
            key = self._generar_key(mensaje)
            self.cache[key] = (respuesta, time.time())
            logger.debug("Cache guardar key=%s mensaje_snippet=%s", key, mensaje[:50])
            # Limpiar cache si es muy grande (max 1000 entradas)
            if len(self.cache) > 1000:
                self._limpiar_viejos()
    
    def _limpiar_viejos(self):
        """Elimina entradas más antiguas"""
        ahora = time.time()
        self.cache = {
            k: v for k, v in self.cache.items()
            if ahora - v[1] < self.ttl
        }

# Instancia global
cache_respuestas = CacheRespuestas(ttl_segundos=3600)


# ==========================================
# 3. DETECCIÓN DE INTENCIÓN RÁPIDA (Sin LLM)
# ==========================================

import re

class DetectorIntenciones:
    """Detecta intenciones comunes sin llamar al LLM"""
    
    PATRONES = {
        'saludo': [
            r'\b(hola|buenas|buenos dias|buen dia|buenas tardes|buenas noches)\b',
            r'^(hola|hi|hey)$'
        ],
        'despedida': [
            r'\b(chau|adios|hasta luego|nos vemos|gracias|bye)\b'
        ],
        'afirmacion': [
            r'^(si|sí|dale|ok|okay|perfecto|genial|bueno|claro)$',
            r'\b(me interesa|quiero|agend|si por favor)\b'
        ],
        'negacion': [
            r'^(no|nop|nope|no gracias)$',
            r'\b(no me interesa|no quiero|ahora no)\b'
        ],
        'consulta_precio': [
            r'\b(cuanto|precio|costo|vale|cotiz|presupuesto)\b'
        ],
        'consulta_horario': [
            r'\b(horario|disponibilidad|cuando|que dia|hora)\b'
        ],
        'frustracion': [
            r'\b(enojado|frustrado|molesto|decepcionado|insatisfecho|no funciona|mal servicio|no entiendo|desastre)\b'
        ]
    }
    
    @classmethod
    def detectar(cls, mensaje: str) -> Optional[str]:
        """
        Detecta intención del mensaje
        
        Returns:
            intención detectada o None
        """
        mensaje_lower = mensaje.lower().strip()
        
        for intencion, patrones in cls.PATRONES.items():
            for patron in patrones:
                if re.search(patron, mensaje_lower):
                    logger.debug("DetectorIntenciones: detected %s for mensaje=%s", intencion, mensaje_lower[:60])
                    return intencion
        
        return None
    
    @classmethod
    def respuesta_rapida(cls, intencion: str, nombre_usuario: str = "") -> Optional[str]:
        """Genera respuesta rápida sin LLM"""
        saludo = f"Hola {nombre_usuario}! 👋" if nombre_usuario else "Hola! 👋"
        despedida = f"¡Hasta luego {nombre_usuario}! 👋" if nombre_usuario else "¡Hasta luego! 👋"

        respuestas = {
            'saludo': f"""{saludo}{SALUDO}""",
            
            'despedida': f"""{despedida}{DESPEDIDA}""",
            
            'consulta_precio': f"""{CONSULTA_PRECIOS}""",
        }
        
        return respuestas.get(intencion)

# Instancia
detector_intenciones = DetectorIntenciones()


# ==========================================
# 4. SISTEMA DE MÉTRICAS Y MONITOREO
# ==========================================

from dataclasses import dataclass
from typing import List
import statistics

@dataclass
class MetricaMensaje:
    timestamp: float
    user_id: str
    tiempo_procesamiento: float
    tokens_usados: int
    fue_cache: bool
    error: bool

class SistemaMetricas:
    """Sistema completo de métricas para monitoreo"""
    
    def __init__(self):
        self.metricas: List[MetricaMensaje] = []
        self.mensajes_procesados = 0
        self.mensajes_en_proceso = 0
        self.errores = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.lock = Lock()
        self.usuarios_activos = set()
        self.inicio_sistema = time.time()
    
    def registrar_inicio(self, user_id: str):
        """Registra inicio de procesamiento"""
        with self.lock:
            self.mensajes_en_proceso += 1
            self.usuarios_activos.add(user_id)
            logger.debug("Metricas: registrar_inicio user_id=%s en_proceso=%s", user_id, self.mensajes_en_proceso)
    
    def registrar_fin(self, user_id: str, tiempo: float, tokens: int = 0, 
                     fue_cache: bool = False, error: bool = False):
        """Registra fin de procesamiento"""
        with self.lock:
            self.mensajes_en_proceso -= 1
            self.mensajes_procesados += 1
            
            if error:
                self.errores += 1
            
            if fue_cache:
                self.cache_hits += 1
            else:
                self.cache_misses += 1
            
            # Guardar métrica
            metrica = MetricaMensaje(
                timestamp=time.time(),
                user_id=user_id,
                tiempo_procesamiento=tiempo,
                tokens_usados=tokens,
                fue_cache=fue_cache,
                error=error
            )
            self.metricas.append(metrica)
            
            # Mantener solo últimas 1000 métricas
            if len(self.metricas) > 1000:
                self.metricas = self.metricas[-1000:]
            # Log con timestamp legible
            try:
                ts = datetime.fromtimestamp(metrica.timestamp).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ts = str(metrica.timestamp)
            logger.debug("Metricas: registrar_fin user_id=%s ts=%s tiempo=%s tokens=%s fue_cache=%s error=%s", user_id, ts, tiempo, tokens, fue_cache, error)
    
    def obtener_estadisticas(self) -> dict:
        """Obtiene estadísticas completas"""
        with self.lock:
            if not self.metricas:
                return {"status": "Sin datos"}
            
            tiempos = [m.tiempo_procesamiento for m in self.metricas if not m.error]
            tiempo_uptime = time.time() - self.inicio_sistema
            
            return {
                "sistema": {
                    "uptime_horas": round(tiempo_uptime / 3600, 2),
                    "mensajes_procesados": self.mensajes_procesados,
                    "mensajes_en_proceso": self.mensajes_en_proceso,
                    "usuarios_unicos": len(self.usuarios_activos),
                },
                "rendimiento": {
                    "tiempo_promedio_segundos": round(statistics.mean(tiempos), 2) if tiempos else 0,
                    "tiempo_minimo": round(min(tiempos), 2) if tiempos else 0,
                    "tiempo_maximo": round(max(tiempos), 2) if tiempos else 0,
                    "mensajes_por_minuto": round(self.mensajes_procesados / (tiempo_uptime / 60), 2),
                },
                "cache": {
                    "hits": self.cache_hits,
                    "misses": self.cache_misses,
                    "tasa_acierto_porcentaje": round(
                        (self.cache_hits / (self.cache_hits + self.cache_misses) * 100), 2
                    ) if (self.cache_hits + self.cache_misses) > 0 else 0
                },
                "errores": {
                    "total": self.errores,
                    "tasa_error_porcentaje": round(
                        (self.errores / self.mensajes_procesados * 100), 2
                    ) if self.mensajes_procesados > 0 else 0
                }
            }

# Instancia global
metricas = SistemaMetricas()


# ==========================================
# 5. TIMEOUT PROTECTION (Prevenir bloqueos) SIN USO
# ==========================================

from threading import Timer
import signal

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Operación excedió tiempo límite")

def ejecutar_con_timeout(func, args=(), kwargs={}, timeout_segundos=30):
    """
    Ejecuta función con timeout
    
    Args:
        func: Función a ejecutar
        args: Argumentos posicionales
        kwargs: Argumentos con nombre
        timeout_segundos: Tiempo máximo de ejecución
    
    Returns:
        Resultado de la función o None si timeout
    """
    resultado = [None]
    excepcion = [None]
    
    def target():
        try:
            resultado[0] = func(*args, **kwargs)
        except Exception as e:
            excepcion[0] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout_segundos)
    
    if thread.is_alive():
        print(f"⏰ Timeout: Operación excedió {timeout_segundos} segundos")
        return None
    
    if excepcion[0]:
        raise excepcion[0]
    
    return resultado[0]