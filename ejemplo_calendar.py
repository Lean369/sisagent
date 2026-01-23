import urllib.parse
from datetime import datetime, timedelta

def generar_enlace_google_calendar(titulo, descripcion, inicio, duracion_minutos, ubicacion="Google Meet"):
    """
    Genera una URL para crear un evento en Google Calendar.
    
    Args:
        titulo (str): Título de la reunión.
        descripcion (str): Cuerpo del mensaje.
        inicio (datetime): Objeto datetime con la fecha y hora de inicio.
        duracion_minutos (int): Duración en minutos.
        ubicacion (str): Lugar o enlace de la videollamada.
    """
    
    # Calcular fin del evento
    fin = inicio + timedelta(minutes=duracion_minutos)
    
    # Formato de fecha requerido por Google: YYYYMMDDTHHMMSSZ (UTC es recomendable)
    # Nota: Aquí usamos el tiempo local del objeto para simplificar, pero idealmente usa UTC.
    fmt = "%Y%m%dT%H%M%S"
    fechas = f"{inicio.strftime(fmt)}/{fin.strftime(fmt)}"
    
    base_url = "https://calendar.google.com/calendar/render"
    
    parametros = {
        "action": "TEMPLATE",
        "text": titulo,
        "details": descripcion,
        "dates": fechas,
        "location": ubicacion,
        "ctz": "America/Argentina/Buenos_Aires" # Zona horaria importante
    }
    
    # Codificar los parámetros en la URL
    url_final = f"{base_url}?{urllib.parse.urlencode(parametros)}"
    
    return url_final

# --- Ejemplo de uso ---

# Datos de la reunión (como en tu imagen)
titulo_reunion = "Reunión con Sisnova"
desc_reunion = (
    "En esta reunión te contaremos cómo nuestra plataforma puede ayudarte "
    "a automatizar la atención al cliente."
)
fecha_inicio = datetime(2026, 1, 29, 14, 0, 0) # 29 de Enero 2026, 14:00hs
duracion = 55 

enlace = generar_enlace_google_calendar(
    titulo=titulo_reunion,
    descripcion=desc_reunion,
    inicio=fecha_inicio,
    duracion_minutos=duracion
)

print("Envía este enlace a tu cliente:")
print(enlace)