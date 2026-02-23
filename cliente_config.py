class HorarioFueraServicio:
    def __init__(self, data):
        self.activo = data.get("activo", False)
        self.horario_inicio = data.get("horario_inicio")
        self.horario_fin = data.get("horario_fin")
        self.dias_laborales = data.get("dias_laborales", [])
        self.zona_horaria = data.get("zona_horaria")
        self.mensaje = data.get("mensaje", [])

class ClienteConfig:
    def __init__(self, id_cliente, data):
        self.id_cliente = id_cliente
        self.nombre = data.get("nombre")
        self.ttl_sesion_minutos = data.get("ttl_sesion_minutos")
        self.admin_phone = data.get("admin_phone")
        self.audio_transcripcion = data.get("audio_transcripcion")
        
        # Instanciamos la clase interna para el horario
        self.fuera_de_servicio = HorarioFueraServicio(data.get("fuera_de_servicio", {}))
        
        # Unimos el prompt si viene como lista de strings
        self.system_prompt = "".join(data.get("system_prompt", []))
        
        self.mensaje_hitl = data.get("mensaje_HITL")
        self.tools_habilitadas = data.get("tools_habilitadas", [])

    def esta_en_horario_laboral(self, hora_actual):
        """Ejemplo de método para lógica de negocio"""
        if not self.fuera_de_servicio.activo:
            return True
        # Aquí podrías agregar la lógica de comparación de horas
        return True