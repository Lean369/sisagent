"""
Sistema de protección contra ataques DDoS para el chatbot de WhatsApp
=====================================================================

Capas de protección:
1. Rate limiting global (total de requests por minuto)
2. Detección de nuevos números sospechosos (muchos números nuevos en poco tiempo)
3. Circuit breaker (detener procesamiento cuando hay sobrecarga)
4. Whitelist/Blacklist de números
5. Análisis de patrones de comportamiento
"""

import os
import time
from loguru import logger
from threading import Lock
from dotenv import load_dotenv
from collections import defaultdict, deque
from typing import Optional, Tuple, Set
from datetime import datetime, timedelta

load_dotenv()

class GlobalRateLimiter:
    """Rate limiter global para todo el sistema (no por usuario)"""
    
    def __init__(self, max_requests_per_minute=100):
        self.max_requests = max_requests_per_minute
        self.requests = deque()  # (timestamp, user_id)
        self.lock = Lock()
        logger.info(f"GlobalRateLimiter inicializado: max_requests_per_minute={max_requests_per_minute}")
    
    def puede_procesar(self) -> Tuple[bool, str]:
        """Verifica si el sistema puede procesar más requests"""
        with self.lock:
            now = time.time()
            
            # Limpiar requests antiguos (más de 1 minuto)
            while self.requests and now - self.requests[0][0] > 60:
                self.requests.popleft()
            
            # Verificar límite
            if len(self.requests) >= self.max_requests:
                logger.warning(f"⚠️ GlobalRateLimiter: límite alcanzado ({len(self.requests)}/{self.max_requests})")
                return False, "⚠️ El sistema está experimentando alta demanda. Por favor intenta en unos minutos."
            
            # Registrar request
            self.requests.append((now, None))
            return True, ""
    
    def get_stats(self) -> dict:
        """Obtiene estadísticas actuales"""
        with self.lock:
            now = time.time()
            # Contar requests en los últimos 60 segundos
            recent = sum(1 for ts, _ in self.requests if now - ts < 60)
            return {
                "requests_last_minute": recent,
                "max_requests": self.max_requests,
                "percentage": round((recent / self.max_requests) * 100, 1)
            }


class NewNumberDetector:
    """Detecta patrones anómalos de números nuevos (posible ataque)"""
    
    def __init__(self, max_new_numbers_per_minute=20, suspicious_threshold=10):
        self.max_new_numbers = max_new_numbers_per_minute
        self.suspicious_threshold = suspicious_threshold
        self.known_numbers: Set[str] = set()
        self.new_numbers = deque()  # (timestamp, number)
        self.lock = Lock()
        self.suspicious_mode = False
        self.suspicious_until = 0
        logger.info(f"NewNumberDetector inicializado: max_new={max_new_numbers_per_minute}, suspicious_threshold={suspicious_threshold}")
    
    def check_number(self, number: str) -> Tuple[bool, str]:
        """
        Verifica si un número puede procesar mensajes
        
        Returns:
            (puede_procesar, mensaje_error)
        """
        with self.lock:
            now = time.time()
            
            # Verificar si estamos en modo sospechoso
            if self.suspicious_mode:
                if now < self.suspicious_until:
                    if number not in self.known_numbers:
                        logger.warning(f"⚠️ NewNumberDetector: número bloqueado en modo sospechoso: {number}")
                        return False, "⚠️ Servicio temporalmente restringido. Intenta nuevamente en unos minutos."
                else:
                    # Salir del modo sospechoso
                    self.suspicious_mode = False
                    logger.info("NewNumberDetector: saliendo del modo sospechoso")
            
            # Si es un número conocido, permitir
            if number in self.known_numbers:
                return True, ""
            
            # Limpiar números nuevos antiguos (más de 1 minuto)
            while self.new_numbers and now - self.new_numbers[0][0] > 60:
                self.new_numbers.popleft()
            
            # Contar nuevos números en el último minuto
            new_count = len(self.new_numbers)
            
            # Si hay demasiados números nuevos, activar modo sospechoso
            if new_count >= self.suspicious_threshold:
                self.suspicious_mode = True
                self.suspicious_until = now + 300  # 5 minutos
                logger.warning(f"⚠️ NewNumberDetector: MODO SOSPECHOSO ACTIVADO - {new_count} números nuevos en 1 minuto")
                return False, "⚠️ Detectamos actividad inusual. Servicio temporalmente restringido."
            
            # Verificar límite de números nuevos
            if new_count >= self.max_new_numbers:
                logger.warning(f"⚠️ NewNumberDetector: límite de números nuevos alcanzado ({new_count}/{self.max_new_numbers})")
                return False, "⚠️ Demasiados números nuevos. Por favor intenta en unos minutos."
            
            # Registrar nuevo número
            self.new_numbers.append((now, number))
            self.known_numbers.add(number)
            logger.debug(f"NewNumberDetector: nuevo número registrado: {number} (total nuevos: {new_count + 1})")
            
            return True, ""
    
    def get_stats(self) -> dict:
        """Obtiene estadísticas"""
        with self.lock:
            now = time.time()
            recent_new = sum(1 for ts, _ in self.new_numbers if now - ts < 60)
            return {
                "known_numbers": len(self.known_numbers),
                "new_numbers_last_minute": recent_new,
                "suspicious_mode": self.suspicious_mode,
                "suspicious_until": datetime.fromtimestamp(self.suspicious_until).strftime("%H:%M:%S") if self.suspicious_mode else None
            }


class CircuitBreaker:
    """Circuit breaker para detener procesamiento cuando hay sobrecarga"""
    
    def __init__(self, failure_threshold=10, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.lock = Lock()
        logger.info(f"CircuitBreaker inicializado: failure_threshold={failure_threshold}, recovery_timeout={recovery_timeout}s")
    
    def puede_procesar(self) -> Tuple[bool, str]:
        """Verifica si el sistema puede procesar"""
        with self.lock:
            now = time.time()
            
            if self.state == "OPEN":
                # Verificar si es tiempo de intentar recuperación
                if now - self.last_failure_time >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    self.failures = 0
                    logger.info("CircuitBreaker: cambiando a HALF_OPEN para intentar recuperación")
                    return True, ""
                else:
                    remaining = int(self.recovery_timeout - (now - self.last_failure_time))
                    logger.warning(f"CircuitBreaker: OPEN - bloqueando requests (recovery en {remaining}s)")
                    return False, f"⚠️ Sistema temporalmente no disponible. Intenta en {remaining} segundos."
            
            # CLOSED o HALF_OPEN: permitir
            return True, ""
    
    def registrar_exito(self):
        """Registra una operación exitosa"""
        with self.lock:
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failures = 0
                logger.info("CircuitBreaker: recuperación exitosa - estado CLOSED")
    
    def registrar_fallo(self):
        """Registra una operación fallida"""
        with self.lock:
            self.failures += 1
            self.last_failure_time = time.time()
            
            if self.failures >= self.failure_threshold:
                self.state = "OPEN"
                logger.error(f"❌CircuitBreaker: ABRIENDO CIRCUITO - {self.failures} fallos consecutivos")
            else:
                logger.warning(f"⚠️CircuitBreaker: fallo registrado ({self.failures}/{self.failure_threshold})")
    
    def get_stats(self) -> dict:
        """Obtiene estadísticas"""
        with self.lock:
            return {
                "state": self.state,
                "failures": self.failures,
                "failure_threshold": self.failure_threshold
            }


class NumberBlacklist:
    """Sistema de blacklist/whitelist de números"""
    
    def __init__(self):
        self.blacklist: Set[str] = set()
        self.whitelist: Set[str] = set()
        self.auto_blacklist = defaultdict(int)  # contador de comportamiento sospechoso
        self.lock = Lock()
        logger.info("NumberBlacklist inicializado")
    
    def is_blocked(self, number: str) -> Tuple[bool, str]:
        """Verifica si un número está bloqueado"""
        with self.lock:
            if number in self.whitelist:
                return False, ""
            
            if number in self.blacklist:
                logger.warning(f"⚠️ NumberBlacklist: número bloqueado: {number}")
                return True, "⚠️ Número bloqueado. Contacta con soporte."
            
            return False, ""
    
    def add_to_blacklist(self, number: str, reason: str = "manual"):
        """Agrega un número a la blacklist"""
        with self.lock:
            self.blacklist.add(number)
            logger.warning(f"⚠️ NumberBlacklist: número agregado a blacklist: {number} (razón: {reason})")
    
    def add_to_whitelist(self, number: str):
        """Agrega un número a la whitelist"""
        with self.lock:
            self.whitelist.add(number)
            # Remover de blacklist si estaba
            self.blacklist.discard(number)
            logger.info(f"NumberWhitelist: número agregado a whitelist: {number}")
    
    def report_suspicious_behavior(self, number: str):
        """Reporta comportamiento sospechoso de un número"""
        with self.lock:
            self.auto_blacklist[number] += 1
            
            # Auto-blacklist después de 3 reportes
            if self.auto_blacklist[number] >= 3:
                self.add_to_blacklist(number, reason="auto-suspicious-behavior")
    
    def get_stats(self) -> dict:
        """Obtiene estadísticas"""
        with self.lock:
            return {
                "blacklist_count": len(self.blacklist),
                "whitelist_count": len(self.whitelist),
                "suspicious_count": len(self.auto_blacklist)
            }


class DDoSProtection:
    """Sistema completo de protección contra DDoS"""
    
    def __init__(self, 
                 global_max_rpm=100,
                 max_new_numbers_pm=20,
                 suspicious_threshold=10,
                 owner_numbers=None):
        
        self.global_limiter = GlobalRateLimiter(global_max_rpm)
        self.new_number_detector = NewNumberDetector(max_new_numbers_pm, suspicious_threshold)
        self.circuit_breaker = CircuitBreaker(failure_threshold=10, recovery_timeout=60)
        self.blacklist = NumberBlacklist()
        
        # Agregar números del propietario a whitelist automáticamente
        if owner_numbers:
            for number in owner_numbers:
                self.blacklist.add_to_whitelist(number)
                logger.info(f"DDoSProtection: número del propietario en whitelist: {number}")
        
        logger.info("🛡️ DDoSProtection inicializado con todas las capas de protección")
    
    def puede_procesar(self, number: str) -> Tuple[bool, str]:
        """
        Verifica todas las capas de protección
        
        Returns:
            (puede_procesar, mensaje_error)
        """
        # 1. Verificar blacklist
        blocked, msg = self.blacklist.is_blocked(number)
        if blocked:
            return False, msg
        
        # 2. Verificar circuit breaker
        puede, msg = self.circuit_breaker.puede_procesar()
        if not puede:
            return False, msg
        
        # 3. Verificar rate limit global
        puede, msg = self.global_limiter.puede_procesar()
        if not puede:
            return False, msg
        
        # 4. Verificar detector de números nuevos
        puede, msg = self.new_number_detector.check_number(number)
        if not puede:
            return False, msg
        
        return True, ""
    
    def registrar_exito(self):
        """Registra una operación exitosa"""
        self.circuit_breaker.registrar_exito()
    
    def registrar_fallo(self):
        """Registra una operación fallida"""
        self.circuit_breaker.registrar_fallo()
    
    def reportar_sospechoso(self, number: str):
        """Reporta comportamiento sospechoso"""
        self.blacklist.report_suspicious_behavior(number)
    
    def agregar_a_whitelist(self, number: str):
        """Agrega un número a la whitelist"""
        self.blacklist.add_to_whitelist(number)
        logger.info(f"DDoSProtection: número agregado a whitelist: {number}")
    
    def get_stats(self) -> dict:
        """Obtiene estadísticas completas"""
        return {
            "global_limiter": self.global_limiter.get_stats(),
            "new_numbers": self.new_number_detector.get_stats(),
            "circuit_breaker": self.circuit_breaker.get_stats(),
            "blacklist": self.blacklist.get_stats()
        }


# Instancia global (condicional según la variable de entorno DDOS_PROTECTION_ENABLED)
_enabled = os.getenv('DDOS_PROTECTION_ENABLED', 'true').lower() == 'true'
if _enabled:
    try:
        _global = int(os.getenv('DDOS_GLOBAL_MAX_RPM', '100'))
    except Exception:
        _global = 100

    try:
        _max_new = int(os.getenv('DDOS_MAX_NEW_NUMBERS_PM', '20'))
    except Exception:
        _max_new = 20

    try:
        _suspicious = int(os.getenv('DDOS_SUSPICIOUS_THRESHOLD', '10'))
    except Exception:
        _suspicious = 10

    _owners_env = os.getenv('DDOS_OWNER_NUMBERS', '')
    _owners = [n.strip() for n in _owners_env.split(',') if n.strip()]

    ddos_protection = DDoSProtection(
        global_max_rpm=_global,
        max_new_numbers_pm=_max_new,
        suspicious_threshold=_suspicious,
        owner_numbers=_owners if _owners else None
    )
else:
    ddos_protection = None
    logger.warning('⚠️ DDoSProtection deshabilitado por DDOS_PROTECTION_ENABLED=false')
