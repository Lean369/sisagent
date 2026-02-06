import os
import time
from datetime import datetime, timedelta
from loguru import logger


def es_horario_laboral(horario_inicio, horario_fin, dias_laborales=[1, 2, 3, 4, 5]) -> bool:
    ahora = datetime.now()
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

    return (ahora.weekday() in allowed_weekdays) and (start_hour <= ahora.hour < end_hour)


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
        logger.warning(f"Error convirtiendo días laborales: {e}")
        return "días laborables"