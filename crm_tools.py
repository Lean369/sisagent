"""
Herramientas del agente IA para gestión de reservas y CRM
"""
import os
import json
from loguru import logger
import sys
import requests
from typing import Dict, Optional
from datetime import datetime
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
import threading
import time
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Variables de configuración
GOOGLE_BOOKING_URL = os.getenv('GOOGLE_BOOKING_URL', '')
KRAYIN_API_URL = os.getenv('KRAYIN_API_URL', '')
KRAYIN_API_TOKEN = os.getenv('KRAYIN_API_TOKEN', '')
KRAYIN_LEAD_SOURCE_ID = os.getenv('KRAYIN_LEAD_SOURCE_ID', '1')
KRAYIN_LEAD_TYPE_ID = os.getenv('KRAYIN_LEAD_TYPE_ID', '1')
KRAYIN_USER_ID = os.getenv('KRAYIN_USER_ID', '1')
KRAYIN_PIPELINE_ID = os.getenv('KRAYIN_PIPELINE_ID', '1')
KRAYIN_STAGE_ID = os.getenv('KRAYIN_STAGE_ID', '1')

# Configuración de CRM
CRM_AUTO_REGISTER = os.getenv('CRM_AUTO_REGISTER', 'true').lower() == 'true'

# Configuración de Google Sheets (opcional)
GOOGLE_SHEETS_ENABLED = os.getenv('GOOGLE_SHEETS_ENABLED', 'false').lower() == 'true'
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID', '')
GOOGLE_CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

try:
    from external_instructions import BOOKING_MESSAGE
    if  not BOOKING_MESSAGE:
        raise ValueError("Faltan BOOKING_MESSAGE en external_instructions.py")
except Exception as e:
    logger.error(f"❌ Error importando external_instructions: {type(e).__name__}: {e}")

    # Definiciones por defecto si falla la importación
    BOOKING_MESSAGE = f"""
    📅 *Agenda tu cita aquí* 
    
    Para reservar tu cita, haz clic en el siguiente enlace:
    {GOOGLE_BOOKING_URL}
    """


def enviar_link_reserva(motivo: str = "") -> str:
    logger.info(f"[BOOKING] Generando link de reserva - Motivo: {motivo or 'No especificado'}")
    
    mensaje = BOOKING_MESSAGE
    
    logger.info(f"[BOOKING] Link de reserva generado exitosamente")
    return mensaje


def enviar_link_reserva_botones(motivo: str = "") -> dict:
    """
    Genera el payload con botón para enviar link de reserva (No funciona con Baileys)
    
    Args:
        motivo: Motivo de la cita (opcional, solo para contexto)
    
    Returns:
        Diccionario con el payload para Evolution API
    """
    logger.info(f"[BOOKING] Generando link de reserva - Motivo: {motivo or 'No especificado'}")
    
    return {
        "type": "button",
        "content": {
            "text": """📅 *Agenda tu cita aquí*

✅ Podrás ver los horarios disponibles
✅ Elegir la fecha y hora que prefieras
✅ Confirmar tu reserva al instante

Haz clic en el link para acceder al calendario:""",
            "buttons": [
                {
                    "type": "url",
                    "displayText": "📅 Reservar Cita",
                    "url": GOOGLE_BOOKING_URL
                }
            ],
            "footer": "Sisnova - Atención 24/7"
        }
    }


def registrar_lead_en_crm(user_lead_info: dict) -> str:
    """
    Registra el lead en Krayin CRM usando la información recopilada
    
    Args:
        user_id: ID del usuario
        telefono: Teléfono del usuario
    
    Returns:
        Mensaje de confirmación
    """
    # Obtener información del lead
    thread_id = user_lead_info.get('thread_id')    
    logger.info(f"[CRM] Iniciando registro de lead para thread_id={thread_id}")

    # Crear el lead en Krayin
    resultado = crear_lead_krayin(
        nombre=user_lead_info.get('nombre'),
        telefono=user_lead_info.get('telefono'),
        email=user_lead_info.get('email'),
        empresa=user_lead_info.get('empresa'),
        rubro=user_lead_info.get('rubro'),
        volumen_mensajes=user_lead_info.get('volumen_mensajes'),
        notas=f"Lead interesado - Solicitó cita de consultoría Goggle Meet"
    )
    
    return resultado


def crear_lead_krayin(
    nombre: str,
    telefono: str,
    email: str = "",
    empresa: str = "",
    rubro: str = "",
    volumen_mensajes: str = "",
    notas: str = ""
) -> Dict:
    """
    Crea un lead en Krayin CRM siguiendo la estructura correcta
    
    Args:
        nombre: Nombre del lead
        telefono: Teléfono del lead
        email: Email del lead (opcional)
        empresa: Nombre de la empresa (opcional)
        rubro: Rubro del negocio (opcional)
        volumen_mensajes: Cantidad de mensajes que recibe (opcional)
        notas: Notas adicionales (opcional)
    
    Returns:
        Respuesta de la API de Krayin
    """
    try:
        logger.info(f"[CRM] Creando lead en Krayin - Nombre: {nombre}, Telefono: {telefono}")
        
        headers = {
            "Authorization": f"Bearer {KRAYIN_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Paso 1: Crear la persona primero
        logger.debug(f"[CRM] Paso 1: Creando persona en Krayin")
        person_id = crear_persona_krayin(nombre, telefono, email)
        
        if not person_id:
            logger.error(f"❌ [CRM] No se pudo crear la persona para {nombre}")
            return {
                "success": False,
                "error": "No se pudo crear la persona",
                "message": "❌ Error al crear contacto en Krayin CRM"
            }
        
        logger.info(f"[CRM] Persona creada exitosamente - person_id={person_id}")
        
        # Paso 2: Construir el título y descripción del lead
        titulo = f"{nombre}"
        if empresa:
            titulo += f" - {empresa}"
        
        descripcion_partes = []
        if rubro:
            descripcion_partes.append(f"📊 Rubro: {rubro}")
        if volumen_mensajes:
            descripcion_partes.append(f"📈 Volumen de mensajes: {volumen_mensajes} diarios")
        if empresa:
            descripcion_partes.append(f"🏢 Empresa: {empresa}")
        if notas:
            descripcion_partes.append(f"📝 {notas}")
        
        descripcion = "\n".join(descripcion_partes) if descripcion_partes else "Lead generado desde WhatsApp Bot - Sisnova"
        
        # Paso 3: Calcular valor estimado del lead
        # Puedes ajustar esta lógica según tus criterios
        lead_value = 0
        if volumen_mensajes:
            try:
                mensajes = float(volumen_mensajes)
                # Ejemplo: $10 por mensaje automatizado, mínimo $500
                lead_value = max(mensajes * 10, 500)
                logger.debug(f"[CRM] Valor del lead calculado: ${lead_value} (basado en {mensajes} mensajes)")
            except:
                lead_value = 500
                logger.debug(f"[CRM] Valor del lead por defecto: ${lead_value}")
        
        # Paso 4: Crear el lead con la estructura correcta
        lead_data = {
            "title": titulo,
            "description": descripcion,
            "lead_value": lead_value,
            "person_id": person_id,
            "lead_source_id": int(KRAYIN_LEAD_SOURCE_ID),
            "lead_type_id": int(KRAYIN_LEAD_TYPE_ID),
            "user_id": int(KRAYIN_USER_ID),
            "lead_pipeline_id": int(KRAYIN_PIPELINE_ID),
            "lead_pipeline_stage_id": int(KRAYIN_STAGE_ID)
        }
        
        logger.debug(f"[CRM] Paso 2: Creando lead con datos: {lead_data}")
        
        # Crear el lead
        response = requests.post(
            f"{KRAYIN_API_URL}/leads",
            headers=headers,
            json=lead_data
        )
        
        logger.debug(f"[CRM] Respuesta de API: status={response.status_code}")
        
        if response.status_code in [200, 201]:
            lead_id = response.json().get('data', {}).get('id')
            logger.info(f"[CRM] Lead creado exitosamente - lead_id={lead_id}, valor=${lead_value}")
            return {
                "success": True,
                "lead_id": lead_id,
                "person_id": person_id,
                "message": f"Lead creado en Krayin CRM (ID: {lead_id}, Valor: ${lead_value})"
            }
        else:
            error_detail = response.json() if response.text else response.text
            logger.error(f"❌ [CRM] Error al crear lead: status={response.status_code}, error={error_detail}")
            return {
                "success": False,
                "error": error_detail,
                "message": f"❌ Error al crear lead: {response.status_code}"
            }
    
    except Exception as e:
        logger.exception(f"🔴 [CRM] Excepción al crear lead: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ Error al crear lead: {str(e)}"
        }


def crear_persona_krayin(nombre: str, telefono: str, email: str = "") -> Optional[int]:
    """
    Crea una persona en Krayin CRM y retorna el person_id.
    Si la persona ya existe (por teléfono), retorna el person_id existente.
    
    Args:
        nombre: Nombre de la persona
        telefono: Teléfono
        email: Email (opcional)
    
    Returns:
        person_id si se creó o encontró exitosamente, None si hubo error
    """
    try:
        logger.info(f"[CRM] Creando persona - Nombre: {nombre}, Telefono: {telefono}")
        
        headers = {
            "Authorization": f"Bearer {KRAYIN_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Primero intentar listar todas las personas y buscar por teléfono
        logger.debug(f"[CRM] Buscando persona existente con teléfono {telefono}")
        
        try:
            # Listar todas las personas (con paginación si es necesario)
            list_response = requests.get(
                f"{KRAYIN_API_URL}/contacts/persons",
                headers=headers,
                params={"limit": 100}  # Limitar a 100 resultados
            )
            
            logger.debug(f"[CRM] Listado - status={list_response.status_code}")
            
            if list_response.status_code == 200:
                list_data = list_response.json()
                persons = list_data.get('data', [])
                logger.debug(f"[CRM] Listado - encontradas {len(persons)} personas")
                
                # Buscar persona con el teléfono exacto
                for person in persons:
                    contact_numbers = person.get('contact_numbers', [])
                    for contact in contact_numbers:
                        if contact.get('value') == telefono:
                            person_id = person.get('id')
                            logger.info(f"[CRM] Persona ya existe - person_id={person_id}")
                            return person_id
                
                logger.debug(f"[CRM] No se encontró persona con teléfono {telefono}")
        except Exception as e:
            logger.warning(f"[CRM] Error al buscar persona existente: {e}")
        
        # Si no existe, crear nueva persona
        logger.debug(f"[CRM] Persona no existe, creando nueva")
        
        person_data = {
            "name": nombre,
            "contact_numbers": [{"value": telefono, "label": "work"}]
        }
        
        if email:
            person_data["emails"] = [{"value": email, "label": "work"}]
            logger.debug(f"[CRM] Email incluido: {email}")
        
        logger.debug(f"[CRM] Datos de persona: {person_data}")
        
        url = f"{KRAYIN_API_URL}/contacts/persons"
        logger.debug(f"[CRM] URL: {url}")
        logger.debug(f"[CRM] Headers: Authorization=Bearer {KRAYIN_API_TOKEN[:20]}..., Content-Type={headers.get('Content-Type')}")
        
        response = requests.post(
            url,
            headers=headers,
            json=person_data
        )
        
        logger.debug(f"[CRM] Respuesta crear persona: status={response.status_code}")
        logger.debug(f"[CRM] Response headers: {dict(response.headers)}")
        
        # Si la respuesta parece ser HTML en lugar de JSON, es un problema de autenticación
        if response.text.strip().startswith('<!DOCTYPE') or response.text.strip().startswith('<html'):
            logger.error(f"❌ [CRM] La API devolvió HTML en lugar de JSON - Token inválido o expirado")
            logger.error(f"[CRM] Response (primeros 500 chars): {response.text[:500]}")
            return None
        
        if response.status_code in [200, 201]:
            try:
                # Verificar que hay contenido antes de parsear
                if not response.text:
                    logger.error(f"❌ [CRM] Error: respuesta vacía de la API")
                    return None
                
                response_data = response.json()
                person_id = response_data.get('data', {}).get('id')
                
                if person_id:
                    logger.info(f"[CRM] Persona creada exitosamente - person_id={person_id}")
                    return person_id
                else:
                    logger.error(f"❌ [CRM] No se recibió person_id en la respuesta: {response_data}")
                    return None
                    
            except json.JSONDecodeError as je:
                logger.error(f"❌ [CRM] Error parseando JSON de respuesta: {je}, response.text={response.text[:200]}")
                return None
        else:
            logger.error(f"❌ [CRM] Error creando persona: status={response.status_code}, response={response.text[:500]}")
            return None
    
    except Exception as e:
        logger.exception(f"🔴 [CRM] Excepción creando persona: {e}")
        return None


def actualizar_lead_krayin(lead_id: str, stage_id: str, notas: str = "") -> Dict:
    """
    Actualiza un lead en Krayin CRM
    
    Args:
        lead_id: ID del lead
        stage_id: ID de la nueva etapa
        notas: Notas adicionales
    
    Returns:
        Respuesta de la API
    """
    try:
        logger.info(f"[CRM] Actualizando lead - lead_id={lead_id}, stage_id={stage_id}")
        
        headers = {
            "Authorization": f"Bearer {KRAYIN_API_TOKEN}",
            "Content-Type": "application/json"
        }
        
        update_data = {
            "lead_pipeline_stage_id": stage_id
        }
        
        if notas:
            logger.debug(f"[CRM] Agregando notas al lead: {notas}")
            # Obtener lead actual para agregar notas
            get_response = requests.get(
                f"{KRAYIN_API_URL}/leads/{lead_id}",
                headers=headers
            )
            
            if get_response.status_code == 200:
                lead_actual = get_response.json().get('data', {})
                descripcion_actual = lead_actual.get('description', '')
                update_data['description'] = f"{descripcion_actual}\n\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {notas}"
                logger.debug(f"[CRM] Descripción actualizada")
            else:
                logger.warning(f"[CRM] No se pudo obtener lead actual: status={get_response.status_code}")
        
        response = requests.put(
            f"{KRAYIN_API_URL}/leads/{lead_id}",
            headers=headers,
            json=update_data
        )
        
        logger.debug(f"[CRM] Respuesta actualizar lead: status={response.status_code}")
        
        if response.status_code == 200:
            logger.info(f"[CRM] Lead actualizado exitosamente - lead_id={lead_id}")
            return {
                "success": True,
                "message": "Lead actualizado en Krayin CRM"
            }
        else:
            logger.error(f"❌ [CRM] Error al actualizar lead: status={response.status_code}, response={response.text}")
            return {
                "success": False,
                "error": response.text,
                "message": "❌ Error al actualizar lead"
            }
    
    except Exception as e:
        logger.exception(f"🔴 [CRM] Excepción al actualizar lead: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ Error al actualizar lead: {str(e)}"
        }


def actualizar_estado_lead_sheets(lead_id: str, nuevo_estado: str) -> Dict:
    """
    Actualiza el estado de un lead en Google Sheets
    
    Args:
        lead_id: ID del lead 
        nuevo_estado: Nuevo estado (ej: "Cita Agendada", "Contactado", "Cerrado")
    
    Returns:
        Dict con resultado
    """
    try:
        if not GOOGLE_SHEET_ID:
            return {"success": False, "message": "No hay hoja de cálculo configurada"}
        
        sheets_service = get_sheets_service()
        
        # Obtener todos los datos
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Leads!A:K'
        ).execute()
        
        valores = result.get('values', [])
        
        # Buscar la fila del lead
        for i, fila in enumerate(valores):
            if len(fila) > 9 and fila[9] == lead_id:  # Columna J (índice 9) = Lead ID
                # Actualizar estado en columna K (índice 10)
                rango = f'Leads!K{i+1}'
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=GOOGLE_SHEET_ID,
                    range=rango,
                    valueInputOption='USER_ENTERED',
                    body={'values': [[nuevo_estado]]}
                ).execute()
                
                return {
                    "success": True,
                    "message": f"Estado actualizado a '{nuevo_estado}' en Google Sheets"
                }
        
        return {
            "success": False,
            "message": f"❌ No se encontró el lead {lead_id} en Google Sheets"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ Error al actualizar estado: {str(e)}"
        }


def get_sheets_service():
    """
    Autentica y retorna el servicio de Google Sheets API
    Soporta tanto OAuth2 como Service Account
    
    Returns:
        Servicio de Google Sheets autenticado
    """
    try:
        from googleapiclient.discovery import build
        import json
        
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        
        # Verificar qué tipo de credenciales tenemos
        with open(GOOGLE_CREDENTIALS_FILE, 'r') as f:
            creds_data = json.load(f)
        
        # Si es Service Account
        if 'type' in creds_data and creds_data['type'] == 'service_account':
            logger.debug(f"[SHEETS] Usando Service Account")
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
            )
        
        # Si es OAuth2 (web o installed)
        else:
            logger.debug(f"[SHEETS] Usando OAuth2")
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            import pickle
            
            creds = None
            token_file = 'sheets_token.pickle'
            
            # Intentar cargar token existente
            if os.path.exists(token_file):
                with open(token_file, 'rb') as token:
                    creds = pickle.load(token)
            
            # Si no hay credenciales válidas
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    logger.debug(f"[SHEETS] Refrescando token expirado")
                    creds.refresh(Request())
                else:
                    logger.warning(f"[SHEETS] Se requiere autorización manual. Google Sheets deshabilitado temporalmente.")
                    logger.warning(f"[SHEETS] Ejecuta: python3 -c \"from agent_tools import authorize_sheets; authorize_sheets()\" para autorizar")
                    return None
                
                # Guardar credenciales refrescadas
                with open(token_file, 'wb') as token:
                    pickle.dump(creds, token)
        
        service = build('sheets', 'v4', credentials=creds)
        logger.debug(f"[SHEETS] Servicio de Google Sheets autenticado exitosamente")
        return service
        
    except FileNotFoundError:
        logger.exception(f"🔴 [SHEETS] Archivo {GOOGLE_CREDENTIALS_FILE} no encontrado")
        return None
    except Exception as e:
        logger.exception(f"🔴 [SHEETS] Error autenticando Google Sheets: {e}")
        return None


def authorize_sheets():
    """
    Función helper para autorizar Google Sheets manualmente (solo OAuth2)
    Ejecutar desde terminal: python3 -c "from agent_tools import authorize_sheets; authorize_sheets()"
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    import pickle
    
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    flow = InstalledAppFlow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_FILE, SCOPES)
    
    logger.info("\n🔐 Autorización de Google Sheets")
    logger.info("=" * 50)
    logger.info("\nSe abrirá una ventana del navegador para autorizar.")
    logger.info("Si no se abre automáticamente, copia y pega la URL en tu navegador.\n")
    
    creds = flow.run_local_server(port=8080, open_browser=True)
    
    # Guardar credenciales
    with open('sheets_token.pickle', 'wb') as token:
        pickle.dump(creds, token)
    
    logger.info("\n✅ Autorización exitosa!")
    logger.info(f"Token guardado en: sheets_token.pickle")
    logger.info("\nAhora puedes reiniciar el agente: ./agent-manager.sh restart\n")


def registrar_lead_en_sheets(
    nombre: str,
    telefono: str,
    email: str = "",
    empresa: str = "",
    rubro: str = "",
    volumen_mensajes: str = "",
    lead_id: str = "",
    estado: str = "Cita Solicitada"
) -> Dict:
    """
    Registra un nuevo lead en Google Sheets
    
    Args:
        nombre: Nombre del lead
        telefono: Teléfono del lead
        email: Email del lead (opcional)
        empresa: Empresa del lead (opcional)
        rubro: Rubro del negocio (opcional)
        volumen_mensajes: Volumen de mensajes (opcional)
        lead_id: ID del lead en Krayin (opcional)
        estado: Estado actual del lead
    
    Returns:
        Dict con resultado de la operación
    """
    try:
        if not GOOGLE_SHEETS_ENABLED:
            logger.debug(f"[SHEETS] Google Sheets deshabilitado, omitiendo registro")
            return {"success": False, "message": "Google Sheets deshabilitado"}
        
        if not GOOGLE_SHEET_ID:
            logger.warning(f"[SHEETS] No hay GOOGLE_SHEET_ID configurado")
            return {"success": False, "message": "No hay hoja de cálculo configurada"}
        
        sheets_service = get_sheets_service()
        if not sheets_service:
            return {"success": False, "message": "Error autenticando Google Sheets"}
        
        # Datos a insertar
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        valores = [[
            timestamp,           # A: Fecha/Hora
            nombre,              # B: Nombre
            telefono,            # C: Teléfono
            email,               # D: Email
            empresa,             # E: Empresa
            rubro,               # F: Rubro
            volumen_mensajes,    # G: Volumen Mensajes
            lead_id,             # H: Lead ID (Krayin)
            estado,              # I: Estado
            "WhatsApp Bot"       # J: Origen
        ]]
        
        logger.info(f"[SHEETS] Registrando lead - Nombre: {nombre}, Tel: {telefono}")
        
        # Agregar fila al final de la hoja
        # Verificar metadata del spreadsheet (ayuda a detectar permisos y sheets existentes)
        try:
            meta = sheets_service.spreadsheets().get(spreadsheetId=GOOGLE_SHEET_ID).execute()
            sheet_titles = [s.get('properties', {}).get('title') for s in meta.get('sheets', [])]
            logger.debug(f"[SHEETS] Spreadsheet access OK. Sheets: {sheet_titles}")
            if 'Leads' not in sheet_titles:
                logger.warning("[SHEETS] Hoja 'Leads' no encontrada en el spreadsheet. Verifique el nombre o créela manualmente.")
        except Exception as e:
            logger.exception(f"🔴 [SHEETS] No fue posible obtener metadata del spreadsheet: {e}")

        # Agregar fila al final de la hoja y capturar respuesta
        append_result = sheets_service.spreadsheets().values().append(
            spreadsheetId=GOOGLE_SHEET_ID,
            range='Leads!A:J',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': valores}
        ).execute()

        logger.debug(f"[SHEETS] append result: {append_result}")

        # Verificar si la API reportó actualizaciones
        updates = append_result.get('updates') or {}
        updated_rows = updates.get('updatedRows', 0)
        if updated_rows > 0:
            logger.info(f"[SHEETS] Lead registrado exitosamente - updatedRows={updated_rows}")
            return {"success": True, "message": "Lead registrado en Google Sheets", "details": append_result}
        else:
            logger.warning(f"[SHEETS] Append completado pero no se detectaron filas actualizadas: {append_result}")
            return {"success": False, "message": "No se registró ninguna fila. Verifique permisos y existencia de la hoja 'Leads'.", "details": append_result}
        
    except Exception as e:
        logger.exception(f"🔴 [SHEETS] Error registrando lead en Google Sheets: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ Error al registrar en Google Sheets: {str(e)}"
        }


def _tarea_pesada_background(user_lead_info):
    """
    Esta función se ejecuta en otro hilo. 
    CRÍTICO: Como el LLM ya "cerró" la charla, tú tienes que avisar proactivamente al usuario que terminaste.
    """
    logger.info(f"🔄 [Background] Iniciando tarea pesada para thread_id: {user_lead_info.get('thread_id', 'desconocido')}...")

    try:
        if CRM_AUTO_REGISTER and KRAYIN_API_URL and KRAYIN_API_TOKEN:
            try:
                # Registrar lead en CRM
                crm_resultado = registrar_lead_en_crm(user_lead_info)

                if crm_resultado.get('success'):
                    # Guardar el lead_id para futuras actualizaciones
                    lead_id = crm_resultado.get('lead_id')
                    user_lead_info['lead_id'] = lead_id
                    logger.info(f"[CRM] Lead registrado exitosamente - lead_id={lead_id}")
                else:
                    logger.error(f"❌ [CRM] Fallo al registrar lead: {crm_resultado.get('error', 'Unknown error')}")

            except Exception as e:
                logger.exception(f"🔴 [CRM] Error al registrar lead: {e}")

        # Registrar en Google Sheets si está habilitado (independiente del CRM)
        if GOOGLE_SHEETS_ENABLED:
            try:
                # Extraer datos del diccionario
                client_name = user_lead_info.get('nombre', 'Desconocido')
                telefono = user_lead_info.get('telefono', '')
                rubro = user_lead_info.get('rubro', '')
                cantidad_mensajes = user_lead_info.get('volumen_mensajes', '0')
                lead_id = user_lead_info.get('lead_id', '0')
                
                sheets_resultado = registrar_lead_en_sheets(
                    nombre=client_name,
                    telefono=telefono,
                    email=telefono + '@example.com',
                    empresa='',
                    rubro=rubro,
                    volumen_mensajes=str(cantidad_mensajes),
                    lead_id=str(lead_id),
                    estado="Cita Solicitada"
                )
                logger.info(f"[SHEETS] {sheets_resultado.get('message', 'Sin mensaje')}")
            except Exception as e:
                logger.exception(f"🔴 [SHEETS] Error al registrar lead: {e}")

    except Exception as e:
        logger.exception(f"🔴 [Background] Error en tarea pesada: {e}")

    logger.info(f"✅ [Background] Tarea terminada.")


# Herramienta principal para activar reservas y CRM
class TriggerBookingToolInput(BaseModel):
    rubro: str = Field(description="El tipo de rubro (ej: peluquería, consultoría, fiambreria, ecommerce).")
    cantidad_mensajes: int = Field(description="Cantidad de mensajes que recibe el negocio por día.")


@tool(args_schema=TriggerBookingToolInput)
def trigger_booking_tool(rubro: str, cantidad_mensajes: int, config: RunnableConfig) -> str:
    """Activa las herramientas de reserva y registro de leads
    Devuelve confirmación inmediata de link de cita y sigue trabajando en segundo plano con CRM y Sheets.

    Args:
        rubro: Rubro del negocio
        config: Configuración del runnable (incluye thread_id y client_name)
        cantidad_mensajes: Cantidad de mensajes que recibe el negocio por día.
        
    Returns:
        Resultado con el link de reserva
    """
    # Storage para información de leads
    user_lead_info = {} 

    try:        
        # Accedemos al diccionario 'configurable'
        configuration = config.get('configurable', {})
    
        thread_id = configuration.get('thread_id', 'Valor no encontrado')
        client_name = configuration.get('client_name', 'Cliente de Prueba')
        # Extraer teléfono del formato: business_id:phone@s.whatsapp.net
        telefono = thread_id.split(':')[1].split('@')[0] if ':' in thread_id else thread_id.split('@')[0] if '@' in thread_id else ""

        rubro = rubro if rubro else "desconocido"  # Simulado para testing
        cantidad_mensajes = cantidad_mensajes if cantidad_mensajes else 0  # Simulado para testing
        lead_id = '0'  # Inicialmente sin lead_id

        # Enviar link de reserva con botones
        resultado = enviar_link_reserva()
        
        # Registrar datos del lead para CRM y Google Sheets
        user_lead_info = {
            'thread_id': thread_id,
            'nombre': client_name,
            'telefono': telefono,
            'empresa': '',
            'rubro': rubro,
            'volumen_mensajes': str(cantidad_mensajes),
            'email': telefono + '@example.com',
            'lead_id': lead_id  # Se actualizará después de registrar en CRM
        }
            
        # Pasamos los argumentos necesarios en 'args'
        hilo = threading.Thread(
            target=_tarea_pesada_background,
            args=(user_lead_info,),
            daemon=False, # False asegura que termine aunque el request HTTP muera
            name=f"BackgroundTask-{thread_id[:20]}"
        )
        
        # 3. Iniciamos el hilo (esto no bloquea al código principal)
        hilo.start()
     
        logger.info(f"[BOOKING] Resultado de trigger_booking_tool: {resultado}")
        return resultado
        
    except Exception as e:
        logger.exception(f"🔴 Error en trigger_booking_tool: {e}")
        return "Lo siento, hubo un error al procesar tu reserva. Por favor intenta nuevamente."


# --- EJEMPLO 1: Para la Pizzería ---
class PedidoPizzaInput(BaseModel):
    client_name: str = Field(description="El nombre del cliente que realiza el pedido.")
    # gusto: str = Field(description="El sabor de la pizza que quiere el cliente (ej: Muzzarella, Napolitana).")
    # cantidad: int = Field(description="La cantidad de pizzas solicitadas. Si no especifica, asume 1.")
    # tamaño: str = Field(description="El tamaño: 'chica', 'grande' o 'familiar'.")


# --- EJEMPLO 2: Para Zapatillas Nike ---
class StockZapatillasInput(BaseModel):
    modelo: str = Field(description="El nombre del modelo de zapatilla (ej: Air Force, Jordan).")
    talle: float = Field(description="El talle numérico argentino (ej: 40, 42.5).")


@tool(args_schema=StockZapatillasInput)
def consultar_stock(modelo: str, talle: float):
    """Consulta el stock disponible en el inventario."""
    # Lógica de consulta a tu DB de stock
    stock = 5 # Simulado
    return f"🔍 Buscando {modelo} en talle {talle}: Encontramos {stock} unidades."


@tool(args_schema=PedidoPizzaInput)
def ver_menu(client_name: str) -> str:
    """Retorna el menú actual de Luigi's Pizza."""
    menu = (
        f"Menú de Luigi's Pizza para: {client_name}\n"
        "1. Pizza Margherita - $10\n"
        "2. Pizza Pepperoni - $12\n"
        "3. Empanada de Carne - $5\n"
        "4. Empanada de Jamón y Queso - $5\n"
    )
    return menu


