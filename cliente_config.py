import os
import json
import time
from datetime import datetime, timezone, timedelta
from langgraph.checkpoint.postgres import PostgresSaver
from loguru import logger
from utilities import obtener_nombres_dias, obtener_configuraciones


class HorarioFueraServicio:
    def __init__(self, data):
        self.activo = data.get("activo", False)
        self.horario_inicio = data.get("horario_inicio")
        self.horario_fin = data.get("horario_fin")
        self.dias_laborales = data.get("dias_laborales", [])
        self.zona_horaria = data.get("zona_horaria")
        self.mensaje = data.get("mensaje", [])

class ClienteConfig:
    def __init__(self, id_cliente):
        config_actual = obtener_configuraciones() 
        data = config_actual.get(id_cliente)
        self.id_cliente = id_cliente
        self.nombre = data.get("nombre")
        self.enabled = data.get("enabled", True)
        self.ttl_sesion_minutos = data.get("ttl_sesion_minutos")
        self.admin_phone = data.get("admin_phone")
        self.audio_transcripcion = data.get("audio_transcripcion")
        
        # Instanciamos la clase interna para el horario
        self.fuera_de_servicio = HorarioFueraServicio(data.get("fuera_de_servicio", {}))
        
        # Unimos el prompt si viene como lista de strings
        self.system_prompt = "".join(data.get("system_prompt", []))
        
        self.mensaje_hitl = data.get("mensaje_HITL")
        self.tools_habilitadas = data.get("tools_habilitadas", [])

    def es_horario_laboral(self) -> tuple[bool, str]:
        if not self.fuera_de_servicio.activo:
            return True, "Verificación de horario laboral: Inactivo"  # Si no está activo el fuera de servicio, siempre es horario laboral
        ahora = datetime.now()

        logger.debug(f"⏰ Verificando horario laboral para negocio: {self.nombre}")
        logger.info(f"💼 Horario comercial: de {self.fuera_de_servicio.horario_inicio} a {self.fuera_de_servicio.horario_fin}hs. ({obtener_nombres_dias(self.fuera_de_servicio.dias_laborales)})")

        # Parsear horas configuradas (formato HH:MM) y días (lista de números)
        try:
            start_hour = int(self.fuera_de_servicio.horario_inicio.split(':')[0])
        except Exception:
            start_hour = 9
        try:
            end_hour = int(self.fuera_de_servicio.horario_fin.split(':')[0])
        except Exception:
            end_hour = 18

        try:
            # Convertir lista de números (1-7) a índices de weekday (0-6)
            if isinstance(self.fuera_de_servicio.dias_laborales, list):
                allowed_weekdays = [int(d) - 1 for d in self.fuera_de_servicio.dias_laborales if isinstance(d, (int, str)) and 1 <= int(d) <= 7]
            elif isinstance(self.fuera_de_servicio.dias_laborales, str):
                allowed_weekdays = [int(d.strip()) - 1 for d in self.fuera_de_servicio.dias_laborales.split(',') if d.strip().isdigit()]
            else:
                allowed_weekdays = [0, 1, 2, 3, 4]  # Lunes a Viernes por defecto
        except Exception:
            allowed_weekdays = [0, 1, 2, 3, 4]

        if isinstance(self.fuera_de_servicio.mensaje, list):
            mensaje_unido = ' '.join(self.fuera_de_servicio.mensaje)  # Une los strings con espacios
        else:
            mensaje_unido = self.fuera_de_servicio.mensaje

        if mensaje_unido:
            msg = mensaje_unido 
        else:
            msg = f"⏰ Actualmente estamos fuera de servicio. Por favor, contáctanos de {self.fuera_de_servicio.horario_inicio} a {self.fuera_de_servicio.horario_fin}hs. ({obtener_nombres_dias(self.fuera_de_servicio.dias_laborales)}). ¡Gracias por tu comprensión! 👋"
        
        return (ahora.weekday() in allowed_weekdays) and (start_hour <= ahora.hour < end_hour), msg