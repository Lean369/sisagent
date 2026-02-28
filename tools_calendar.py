# source .venv/bin/activate && python tools_calendar.py
import os.path
import json
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests
from google.oauth2 import id_token

from googleapiclient.discovery import build
import requests
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from loguru import logger
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Si modificas estos SCOPES, elimina el archivo token.json.
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid'
]

client_id = "cliente1"

def get_authorization_url(business_id="cliente1"):
    """
    Genera y devuelve la URL de autorizacion para que el cliente la use.
    Construye la URL manualmente para evitar problemas con parametros corruptos.
    Usa el webhook publico para recibir el codigo automaticamente.
    
    Args:
        business_id: ID del negocio que se está autenticando (se incluye en el state)
    """
    logger.info(f"Generando URL de autorizacion para Google Calendar (business: {business_id})...")

    # Leer credentials.json para obtener client_id
    with open('credentials.json', 'r') as f:
        creds_data = json.load(f)
        client_id = creds_data['web']['client_id']
    
    # Generar un state único que incluya el business_id
    import secrets
    random_state = secrets.token_urlsafe(16)
    state_with_business = f"{random_state}:{business_id}"
    
    # Construir URL manualmente con redirect_uri al webhook público
    import urllib.parse
    
    # Usar el webhook público en lugar de localhost
    APP_BASE_URL = os.getenv("APP_BASE_URL", "https://sisagent.sisnova.org")
    redirect_uri = f'{APP_BASE_URL}/oauth/calendar/callback'
    
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),  # Usar todos los scopes definidos
        'access_type': 'offline',
        'prompt': 'consent',  # Forzar refresh_token en cada autorización
        'state': state_with_business
    }
    
    base_url = 'https://accounts.google.com/o/oauth2/auth'
    auth_url = f"{base_url}?{urllib.parse.urlencode(params)}"
    
    logger.info(f"URL generada con redirect a webhook público")
    logger.info(f"State: {state_with_business}")
    return auth_url


def authenticate_with_code(auth_code):
    """
    Completa la autenticacion usando el codigo que el usuario proporciona.
    El codigo puede venir de la URL de redireccion o copiado directamente.
    """
    logger.info("Intercambiando codigo de autorizacion por token...")
    
    # Crear nuevo flow con el mismo redirect_uri usado en get_authorization_url
    flow = Flow.from_client_secrets_file('credentials.json', SCOPES)
    APP_BASE_URL = os.getenv("APP_BASE_URL", "https://sisagent.sisnova.org")
    flow.redirect_uri = f'{APP_BASE_URL}/oauth/calendar/callback'
    
    # Limpiar el codigo (puede venir de una URL completa o solo el codigo)
    auth_code = auth_code.strip()
    
    # Si el usuario pego la URL completa, extraer el codigo
    if 'code=' in auth_code or 'localhost' in auth_code or 'http' in auth_code:
        from urllib.parse import urlparse, parse_qs
        try:
            parsed = urlparse(auth_code)
            code_param = parse_qs(parsed.query).get('code', [None])[0]
            if code_param:
                auth_code = code_param
                logger.info(f"Codigo extraido de URL completa")
        except:
            pass
    
    auth_code = auth_code.strip()
    logger.info(f"Procesando codigo: {auth_code[:15]}...{auth_code[-10:] if len(auth_code) > 25 else ''}")
    logger.info(f"Redirect URI usado: {flow.redirect_uri}")
    
    # Intercambiar codigo por token
    flow.fetch_token(code=auth_code)
    return flow.credentials


# 2. Schema para completar autenticación
class AuthCodeSchema(BaseModel):
    auth_code: str = Field(
        description="El código de autorización que Google le mostró al cliente después de autorizar."
    )

@tool("completar_auth_calendar", args_schema=AuthCodeSchema)
def completar_auth_calendar(auth_code: str, config: RunnableConfig) -> str:
    """
    Completa la autenticación de Google Calendar usando el código que el cliente proporcionó.
    ÚSALA SOLO después de que el cliente haya visitado la URL de autorización y te haya dado el código.
    
    IMPORTANTE: Si el usuario NO tiene la URL todavía, NO uses esta herramienta.
    Primero debe intentar agendar con agendar_cita_calendar para obtener la URL.
    """
    try:
        # Recuperamos de qué cliente es este bot
        business_id = config.get("configurable", {}).get("business_id", "cliente1")
        token_file = f"tokens_calendar/{business_id}_token.json"
        
        logger.info(f"🔄 Procesando código de autorización para {business_id}...")
        logger.info(f"📝 Código recibido: {auth_code}")
        
        # Validar que el código tenga formato razonable
        auth_code_clean = auth_code.strip().replace(' ', '').replace('\n', '')
        
        if len(auth_code_clean) < 10:
            return json.dumps({
                "status": "error",
                "message": "El código parece demasiado corto. Asegúrate de copiar el código completo que Google te mostró."
            }, ensure_ascii=False)
        
        # Intercambiar código por token
        logger.info("🔄 Intercambiando código por token...")
        creds = authenticate_with_code(auth_code_clean)
        
        # Guardar las credenciales
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
        
        logger.info(f"✅ Autenticación completada para {business_id}")
        
        result = {
            "status": "success",
            "message": "✅ ¡Perfecto! La autenticación se completó exitosamente. Ahora puedo agendar citas en tu Google Calendar.",
            "business_id": business_id
        }
        
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Error al completar autenticación: {error_msg}")
        
        # Mensajes más amigables según el tipo de error
        if "invalid_grant" in error_msg.lower() or "malformed" in error_msg.lower():
            return json.dumps({
                "status": "error",
                "message": "❌ El código de autorización no es válido. Esto puede pasar si:\n1. El código expiró (válido solo por unos minutos)\n2. Ya fue usado antes\n3. Tiene espacios o caracteres extra\n\n👉 Necesito que hagas el proceso nuevamente para obtener un código NUEVO."
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "status": "error",
                "message": f"❌ Error al procesar la autorización: {error_msg}"
            }, ensure_ascii=False)

# 1. Definimos el Esquema Estricto
class CitaSchema(BaseModel):
    nombre: str = Field(
        default=None,
        description="El nombre completo del contacto. Ej: Juan Pérez"
    )
    email_cliente: str = Field(
        default=None,
        description="El correo electrónico del contacto (Opcional). Debe ser un formato válido."
    )
    fecha_hora_iso: str = Field(
        description="CRÍTICO: La fecha y hora exactas de la cita ESTRICTAMENTE en formato ISO 8601. Ejemplo: '2026-02-18T15:00:00'."
    )
    descripcion: str = Field(
        description="Descripción de la cita."
    )

@tool("agendar_cita_calendar", args_schema=CitaSchema)
def agendar_cita_calendar(nombre: str, email_cliente: str, fecha_hora_iso: str, config: RunnableConfig, descripcion: str) -> str:
    """
    HERRAMIENTA PRINCIPAL para agendar citas en Google Calendar.
    
    FLUJO CORRECTO:
    1. El usuario pide agendar una cita
    2. Llamas a esta herramienta con los datos
    3. Si devuelve "auth_required", tomas la URL del JSON y se la das al usuario
    4. El usuario visita la URL, autoriza, y te da el código
    5. ENTONCES llamas a completar_auth_calendar con ese código
    6. Una vez autenticado, vuelves a llamar a esta herramienta para crear la cita
    
    IMPORTANTE: SIEMPRE usa esta herramienta primero. NO llames a completar_auth_calendar
    si el usuario no tiene una URL de autorización todavía.
    """
    try:
        # Recuperamos de qué cliente es este bot para saber qué token usar
        business_id = config.get("configurable", {}).get("business_id", "cliente1")
        token_file = f"tokens_calendar/{business_id}_token.json"
        
        logger.info(f"📅 Intentando agendar cita para {nombre} ({email_cliente}) en {fecha_hora_iso}")
        
        # Verificar si el cliente está autenticado
        creds = None
        if os.path.exists(token_file):
            logger.info(f"🔑 Cargando credenciales desde {token_file}...")
            try:
                creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            except Exception as e:
                logger.warning(f"⚠️ Error al cargar credenciales: {e}")
                creds = None
        
        # Si no hay credenciales válidas, devolver URL de autorización
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.info("🔄 Refrescando credenciales...")
                    creds.refresh(Request())
                    # Guardar credenciales refrescadas
                    with open(token_file, 'w') as token:
                        token.write(creds.to_json())
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo refrescar token: {e}")
                    creds = None
            
            # Si aún no hay credenciales válidas, generar URL de autorización
            if not creds or not creds.valid:
                logger.info("🔑 Generando URL de autenticación...")
                auth_url = get_authorization_url(business_id)
                
                result = {
                    "status": "auth_required",
                    "message": f"Para agendar citas, necesito que autorices el acceso a tu Google Calendar.\n\n✅ Pasos:\n1. Abre esta URL en tu navegador (teléfono o PC)\n2. Selecciona tu cuenta de Google\n3. Haz clic en 'Permitir' para autorizar\n4. ¡Listo! El sistema se conectará automáticamente\n\n⚡ No necesitas copiar ningún código, todo es automático.",
                    "auth_url": auth_url,
                    "business_id": business_id
                }
                
                logger.info(f"📨 Devolviendo URL de autorización: {auth_url[:80]}...")
                return json.dumps(result, ensure_ascii=False)
        
        # Cliente autenticado - crear la cita
        logger.info("✅ Cliente autenticado. Creando cita en Calendar...")
        
        # Obtener el email del usuario autenticado desde el token
        email_usuario = None
        try:
            # Usar OAuth2 API para obtener info del usuario
            oauth2_service = build('oauth2', 'v2', credentials=creds)
            user_info = oauth2_service.userinfo().get().execute()
            email_usuario = user_info.get('email')
            logger.info(f"📧 Email del usuario autenticado: {email_usuario}")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo obtener email del token: {e}")
        
        service = build('calendar', 'v3', credentials=creds)
        
        # Parsear la fecha y calcular fin (1 hora después por defecto)
        try:
            fecha_inicio = datetime.fromisoformat(fecha_hora_iso.replace('Z', '+00:00'))
            fecha_fin = fecha_inicio + timedelta(hours=1)
        except Exception as e:
            logger.error(f"❌ Error al parsear fecha: {e}")
            return json.dumps({
                "status": "error",
                "message": f"Formato de fecha inválido. Usa ISO 8601, ejemplo: '2026-02-18T15:00:00'"
            }, ensure_ascii=False)
        
        # Crear el evento
        descripcion_completa = f"{descripcion}\n\nCliente: {nombre}"
        if email_cliente:
            descripcion_completa += f"\nEmail: {email_cliente}"
        
        # Construir attendees solo si hay email válido
        attendees = []
        if email_cliente:
            attendees.append({'email': email_cliente})
        elif email_usuario:
            attendees.append({'email': email_usuario})
        
        evento = {
            'summary': f'Cita: {nombre if nombre else descripcion}',
            'location': 'Por confirmar',
            'description': descripcion_completa,
            'start': {
                'dateTime': fecha_inicio.isoformat(),
                'timeZone': 'America/Argentina/Buenos_Aires',
            },
            'end': {
                'dateTime': fecha_fin.isoformat(),
                'timeZone': 'America/Argentina/Buenos_Aires',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 30},
                ],
            },
        }
        
        # Agregar attendees solo si existe
        if attendees:
            evento['attendees'] = attendees
        
        # Insertar el evento
        evento_creado = service.events().insert(calendarId='primary', body=evento, sendUpdates='all').execute()
        
        result = {
            "status": "success",
            "message": f"✅ ¡Cita agendada exitosamente para {nombre} el {fecha_inicio.strftime('%d/%m/%Y a las %H:%M')}!",
            "event_link": evento_creado.get('htmlLink'),
            "event_id": evento_creado.get('id')
        }
        
        logger.info(f"✅ Cita creada: {evento_creado.get('htmlLink')}")
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"❌ Error al agendar cita: {e}")
        return json.dumps({
            "status": "error",
            "message": f"Error al agendar la cita: {str(e)}"
        }, ensure_ascii=False)



# 3. Schema para consultar citas
class ConsultarCitasSchema(BaseModel):
    fecha_iso: str = Field(
        description="Fecha a consultar en formato ISO 8601. Ejemplo: '2026-02-23' o '2026-02-23T00:00:00'"
    )

@tool("consultar_citas_calendar", args_schema=ConsultarCitasSchema)
def consultar_citas_calendar(fecha_iso: str, config: RunnableConfig) -> str:
    """
    Consulta todas las citas/eventos agendados en Google Calendar para una fecha específica.
    
    Devuelve la lista de citas con:
    - Título del evento
    - Hora de inicio y fin
    - Descripción
    - Asistentes
    - Enlace al evento
    
    Requiere que el usuario esté autenticado previamente.
    """
    try:
        # Recuperar business_id
        business_id = config.get("configurable", {}).get("business_id", "cliente1")
        token_file = f"tokens_calendar/{business_id}_token.json"
        
        logger.info(f"📅 Consultando citas para {business_id} en fecha: {fecha_iso}")
        
        # Verificar autenticación
        creds = None
        if os.path.exists(token_file):
            logger.info(f"🔑 Cargando credenciales desde {token_file}...")
            try:
                creds = Credentials.from_authorized_user_file(token_file, SCOPES)
            except Exception as e:
                logger.warning(f"⚠️ Error al cargar credenciales: {e}")
                creds = None
        
        # Si no hay credenciales válidas, devolver URL de autorización
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.info("🔄 Refrescando credenciales...")
                    creds.refresh(Request())
                    with open(token_file, 'w') as token:
                        token.write(creds.to_json())
                except Exception as e:
                    logger.warning(f"⚠️ No se pudo refrescar token: {e}")
                    creds = None
            
            if not creds or not creds.valid:
                logger.info("🔑 Generando URL de autenticación...")
                auth_url = get_authorization_url(business_id)
                
                result = {
                    "status": "auth_required",
                    "message": "Para consultar tus citas, necesito que autorices el acceso a tu Google Calendar primero.",
                    "auth_url": auth_url,
                    "business_id": business_id
                }
                
                return json.dumps(result, ensure_ascii=False)
        
        # Cliente autenticado - consultar eventos
        logger.info("✅ Cliente autenticado. Consultando eventos...")
        
        service = build('calendar', 'v3', credentials=creds)
        
        # Parsear fecha y calcular rango del día completo
        try:
            # Intentar parsear como fecha completa primero
            if 'T' in fecha_iso:
                fecha = datetime.fromisoformat(fecha_iso.replace('Z', '+00:00'))
            else:
                # Si es solo fecha (YYYY-MM-DD), agregar hora inicial
                fecha = datetime.fromisoformat(fecha_iso + 'T00:00:00')
            
            # Definir inicio y fin del día
            inicio_dia = fecha.replace(hour=0, minute=0, second=0, microsecond=0)
            fin_dia = fecha.replace(hour=23, minute=59, second=59, microsecond=999999)
            
        except Exception as e:
            logger.error(f"❌ Error al parsear fecha: {e}")
            return json.dumps({
                "status": "error",
                "message": f"Formato de fecha inválido. Usa ISO 8601, ejemplo: '2026-02-23'"
            }, ensure_ascii=False)
        
        # Consultar eventos en el rango de fechas
        logger.info(f"🔍 Buscando eventos entre {inicio_dia.isoformat()} y {fin_dia.isoformat()}")
        
        events_result = service.events().list(
            calendarId='primary',
            timeMin=inicio_dia.isoformat() + 'Z',
            timeMax=fin_dia.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime',
            timeZone='America/Argentina/Buenos_Aires'
        ).execute()
        
        events = events_result.get('items', [])
        
        if not events:
            result = {
                "status": "success",
                "message": f"No hay citas agendadas para el {fecha.strftime('%d/%m/%Y')}.",
                "total_eventos": 0,
                "eventos": []
            }
            logger.info("📭 No se encontraron eventos para esa fecha")
            return json.dumps(result, ensure_ascii=False)
        
        # Procesar eventos
        eventos_formateados = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            # Parsear fechas para formato legible
            try:
                if 'T' in start:
                    inicio_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    fin_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    hora_inicio = inicio_dt.strftime('%H:%M')
                    hora_fin = fin_dt.strftime('%H:%M')
                else:
                    hora_inicio = "Todo el día"
                    hora_fin = ""
            except:
                hora_inicio = start
                hora_fin = end
            
            # Obtener asistentes
            attendees = event.get('attendees', [])
            lista_asistentes = [att.get('email', 'Sin email') for att in attendees]
            
            evento_info = {
                "id": event.get('id'),
                "titulo": event.get('summary', 'Sin título'),
                "hora_inicio": hora_inicio,
                "hora_fin": hora_fin,
                "descripcion": event.get('description', 'Sin descripción'),
                "ubicacion": event.get('location', 'Sin ubicación'),
                "asistentes": lista_asistentes,
                "enlace": event.get('htmlLink'),
                "estado": event.get('status', 'confirmed')
            }
            
            eventos_formateados.append(evento_info)
        
        result = {
            "status": "success",
            "message": f"Encontré {len(eventos_formateados)} cita(s) para el {fecha.strftime('%d/%m/%Y')}:",
            "total_eventos": len(eventos_formateados),
            "fecha_consultada": fecha.strftime('%d/%m/%Y'),
            "eventos": eventos_formateados
        }
        
        logger.info(f"✅ Se encontraron {len(eventos_formateados)} eventos")
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        logger.error(f"❌ Error al consultar citas: {e}")
        return json.dumps({
            "status": "error",
            "message": f"Error al consultar las citas: {str(e)}"
        }, ensure_ascii=False)


def main():
    """
    Función de prueba para autenticación manual (solo para testing).
    """
    creds = None
    # El archivo token.json guarda los tokens de acceso del usuario.
    if not os.path.exists("tokens_calendar"):
        os.makedirs("tokens_calendar")
    if os.path.exists(f'tokens_calendar/{client_id}_token.json'):
        logger.info("🔑 Cargando credenciales desde token.json...")
        creds = Credentials.from_authorized_user_file(f'tokens_calendar/{client_id}_token.json', SCOPES)
    
    # Si no hay credenciales válidas, deja que el usuario inicie sesión.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("🔄 Refrescando credenciales...")
            creds.refresh(Request())
        else:
            logger.info("🔑 Generando URL de autenticación para el cliente...")
            
            # Generar URL de autorización (función de prueba - usar client_id por defecto)
            auth_url = get_authorization_url(client_id)
            
            logger.info("=" * 80)
            logger.info("📨 ENVÍA ESTA URL AL CLIENTE PARA AUTENTICACIÓN:")
            logger.info(f"\n{auth_url}\n")
            logger.info("=" * 80)
            
            # Esperar que el usuario ingrese el código de autorización
            print("\n👉 Después de que el cliente autorice, Google mostrará un código.")
            auth_code = input("📝 Ingresa el código de autorización aquí: ").strip()
            
            logger.info("🔄 Intercambiando código por token...")
            creds = authenticate_with_code(auth_code)
        # Guarda las credenciales para la próxima vez
        with open(f'tokens_calendar/{client_id}_token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)

    # Definir la cita
    evento = {
        'summary': 'Nueva Cita con Cliente',
        'location': 'Videollamada / Oficina',
        'description': 'Consulta técnica sobre el proyecto Python.',
        'start': {
            'dateTime': '2026-03-25T10:00:00Z',
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': '2026-03-25T11:00:00Z',
            'timeZone': 'UTC',
        },
    }

    # Insertar el evento
    evento_creado = service.events().insert(calendarId='primary', body=evento).execute()
    
    logger.info("✅ ¡Cita creada con éxito!")
    logger.info(f"🔗 Enlace al evento: {evento_creado.get('htmlLink')}")


if __name__ == '__main__':
    main()