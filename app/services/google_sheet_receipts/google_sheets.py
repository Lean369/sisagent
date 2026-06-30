from loguru import logger
import os
import threading
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json

# Lock para evitar race conditions cuando múltiples threads escriben al mismo tiempo
_sheets_lock = threading.Lock()

GOOGLE_SHEETS_ENABLED = os.getenv('GOOGLE_SHEETS_ENABLED', 'false').lower() == 'true'

# Variables globales internas para caché
_CONFIG_CACHE = {}
_LAST_MTIME = 0
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config_google_sheets.json')

def get_google_sheets_configs():
    """
    Retorna la configuración. Si el archivo cambió en disco, recarga automáticamente (hot reload).
    """
    global _CONFIG_CACHE, _LAST_MTIME

    try:
        # 1. Obtenemos la fecha de modificación actual del archivo
        current_mtime = os.path.getmtime(_CONFIG_PATH)

        # 2. Si la fecha es distinta a la última que leímos, recargamos
        if current_mtime != _LAST_MTIME:
            logger.info("🔄 Detectado cambio en config_google_sheets.json. Recargando...")
            
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                nuevas_configuraciones = json.load(f)
            
            # Validación simple (opcional)
            if not isinstance(nuevas_configuraciones, dict):
                raise ValueError("El JSON debe ser un diccionario.")

            # Actualizamos caché y timestamp
            _CONFIG_CACHE = nuevas_configuraciones
            _LAST_MTIME = current_mtime
            
            logger.info(f"✅ Configuración recargada: {len(_CONFIG_CACHE)} negocios.")


        return _CONFIG_CACHE

    except Exception as e:
        logger.exception(f"🔴 Error leyendo google_sheets config en caliente: {e}")
        return _CONFIG_CACHE


# Ejemplo conceptual del algoritmo de actualización usando gspread
def marcar_como_conciliado(hoja, numero_operacion):
    # Buscar en qué fila está el comprobante (asumiendo que la operacion esta en col 4)
    celda = hoja.find(numero_operacion, in_column=4)
    if celda:
        # Actualizar la columna de "Estado" (asumiendo que es la columna 7)
        hoja.update_cell(celda.row, 7, "Conciliado ✅")


def write_record_sheets(datos_recibo, extra, thread_id) -> tuple:
    """
    Registra un nuevo recibo de transferencia en Google Sheets
    """
    try:
        config = get_google_sheets_configs().get(thread_id)

        if not GOOGLE_SHEETS_ENABLED:
            logger.debug(f"[SHEETS] Google Sheets deshabilitado, omitiendo registro")
            return False, "Google Sheets deshabilitado"
        else:
            logger.debug(f"[SHEETS] Google Sheets habilitado, procesando registro para thread_id={thread_id}")
        
        if not config or not config.get("GOOGLE_SHEET_ID"):
            logger.warning(f"[SHEETS] No hay GOOGLE_SHEET_ID configurado para el thread {thread_id} en config_google_sheets.json")
            return False, "No hay GOOGLE_SHEET_ID configurado"
        else:
            logger.debug(f"[SHEETS] GOOGLE_SHEET_ID encontrado: {config.get('GOOGLE_SHEET_ID')} para thread_id={thread_id}")
        
        if not config or not config.get("GOOGLE_CREDENTIALS_FILE"):
            logger.warning(f"[SHEETS] No hay GOOGLE_CREDENTIALS_FILE configurado para el thread {thread_id} en config_google_sheets.json")
            return False, "No hay GOOGLE_CREDENTIALS_FILE configurado"
        else:
            logger.debug(f"[SHEETS] GOOGLE_CREDENTIALS_FILE encontrado: {config.get('GOOGLE_CREDENTIALS_FILE')} para thread_id={thread_id}")

        sheets_service = get_sheets_service(config)

        if not sheets_service:
            logger.error(f"[SHEETS] Error autenticando Google Sheets")
            return False, "❌ Error autenticando Google Sheets"
        
        import json
        if isinstance(datos_recibo, str):
            try:
                datos_recibo = json.loads(datos_recibo)
            except json.JSONDecodeError:
                logger.warning("[SHEETS] datos_recibo es una cadena no JSON; omitiendo registro")
                return False, "❌ datos_recibo es una cadena no JSON"

        # Helper para soportar tanto dict como objetos con atributos
        def _g(key: str):
            if isinstance(datos_recibo, dict):
                return datos_recibo.get(key, "")
            return getattr(datos_recibo, key, "")

        # Determinar si es entrada o salida
        try:
            monto_num = float(str(_g('monto')).replace(',', '.').strip() or 0)
        except (ValueError, TypeError):
            monto_num = 0.0

        extra_list = extra if isinstance(extra, list) else [extra]
        if _g('cuenta_destino') in extra_list:
            entrada = monto_num
            salida = 0
            comision = round(monto_num * 3.5 / 100, 2)  # comisión del 3.5% para entradas
            saldo = round(entrada - comision, 2)
        else:
            salida = monto_num
            entrada = 0
            comision = 0.0
            saldo = round(-salida, 2)

        # Datos a insertar
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        estado = "Pendiente"
        valores = [[
            estado,                           # A: Estado de la transferencia (Pendiente, Conciliado, etc.)
            _g('fecha'),                      # B: Fecha de la transferencia
            _g('nombre_emisor'),              # C: Nombre del emisor de la transferencia
            _g('nombre_receptor'),            # D: Nombre del receptor de la transferencia
            entrada,                          # E: monto entrante
            salida,                           # F: monto saliente
            comision,                         # G: comisión
            None,  # H: saldo acumulado (se reemplaza con la fórmula real en _escribir_en_sheets
            _g('banco_origen'),               # I: Banco de origen de la transferencia
            _g('banco_destino'),              # J: Banco de destino de la transferencia
            _g('cuenta_origen'),              # K: Cuenta de origen de la transferencia, 22 dígitos para CVU argentino
            _g('cuenta_destino'),             # L: Cuenta de destino de la transferencia, 22 dígitos para CVU argentino
            _g('operacion'),                  # M: Número de operación de la transferencia
            _g('hora'),                       # N: Hora de la transferencia
            _g('referencia'),                 # O: Referencia de la transferencia
            _g('concepto'),                   # P: Concepto de la transferencia
            timestamp                         # Q: Fecha/Hora
        ]]

        logger.info(f"[SHEETS] Registrando recibo de transferencia - Nombre Emisor: {_g('nombre_emisor')}, Nombre Receptor: {_g('nombre_receptor')}, Monto: {_g('monto')}")

        # Lock para serializar escrituras concurrentes y evitar filas vacías por race condition
        with _sheets_lock:
            return _escribir_en_sheets(sheets_service, valores, config)

    except HttpError as e:
        status = e.resp.status if hasattr(e, 'resp') else '?'
        logger.error(f"🔴 [SHEETS] Error HTTP {status} de Google Sheets API: {e._get_reason()}")
        return False, f"🔴 Error de Google Sheets API ({status})"
    except Exception as e:
        logger.exception(f"🔴 [SHEETS] Error registrando recibo en Google Sheets: {e}")
        return False, "🔴 Error registrando recibo en Google Sheets"


def _escribir_en_sheets(sheets_service, valores, config) -> tuple:
    try:
        return _escribir_en_sheets_inner(sheets_service, valores, config)
    except HttpError as e:
        status = e.resp.status if hasattr(e, 'resp') else '?'
        logger.error(f"🔴 [SHEETS] Error HTTP {status} de Google Sheets API: {e._get_reason()}")
        return False, f"🔴 Error de Google Sheets API ({status})"
    except Exception as e:
        logger.error(f"🔴 [SHEETS] Error inesperado en _escribir_en_sheets: {e}")
        return False, "🔴 Error inesperado escribiendo en Google Sheets"


def _escribir_en_sheets_inner(sheets_service, valores, config) -> tuple:
        # Calcular next_row dentro del lock (operación atómica: leer→insertar→escribir)
        try:
            spreadsheet_name = config.get("GOOGLE_SHEET_NAME")
            col_data = sheets_service.spreadsheets().values().get(
                spreadsheetId=config.get("GOOGLE_SHEET_ID"),
                range=f'{spreadsheet_name}!A:A'
            ).execute()
            next_row = len(col_data.get('values', [])) + 1
        except HttpError:
            raise
        except Exception:
            next_row = 2  # fallback: después de la cabecera

        # Verificar duplicado por número de operación (columna M, índice 12)
        operacion = valores[0][12] if valores and valores[0] and len(valores[0]) > 12 else None
        if operacion:
            try:
                col_m = sheets_service.spreadsheets().values().get(
                    spreadsheetId=config.get("GOOGLE_SHEET_ID"),
                    range=f'{spreadsheet_name}!M:M'
                ).execute()
                existing = [row[0] for row in col_m.get('values', []) if row]
                if operacion in existing:
                    logger.warning(f"[SHEETS] Operación '{operacion}' ya existe en la hoja. Se omite el registro duplicado.")
                    return False , f"❌ Operación {operacion} DUPLICADA."
            except HttpError:
                raise
            except Exception as e:
                logger.warning(f"[SHEETS] No se pudo verificar duplicados en columna M: {e}")

        # Reemplazar el placeholder None con la fórmula dinámica usando next_row real
        if valores and valores[0] and len(valores[0]) > 7 and valores[0][7] is None:
            valores[0][7] = f"=SUMA(E$2:E{next_row})-SUMA(F$2:F{next_row})-SUMA(G$2:G{next_row})"

        # Verificar metadata y obtener sheetId numérico de la hoja 'recibos'
        recibos_sheet_id = None
        try:
            meta = sheets_service.spreadsheets().get(spreadsheetId=config.get("GOOGLE_SHEET_ID")).execute()
            sheet_titles = [s.get('properties', {}).get('title') for s in meta.get('sheets', [])]
            logger.debug(f"[SHEETS] Spreadsheet access OK. Sheets: {sheet_titles}")
            if config.get("GOOGLE_SHEET_NAME") not in sheet_titles:
                logger.warning(f"[SHEETS] Hoja '{config.get('GOOGLE_SHEET_NAME')}' no encontrada en el spreadsheet. Verifique el nombre o créela manualmente.")
            recibos_sheet_id = next(
                (s['properties']['sheetId'] for s in meta.get('sheets', [])
                 if s.get('properties', {}).get('title') == config.get("GOOGLE_SHEET_NAME")),
                None
            )
        except HttpError:
            raise
        except Exception as e:
            logger.error(f"🔴 [SHEETS] No fue posible obtener metadata del spreadsheet: {e}")

        # Insertar fila vacía heredando formato de la fila inferior (inheritFromBefore=False)
        if recibos_sheet_id is not None:
            try:
                sheets_service.spreadsheets().batchUpdate(
                    spreadsheetId=config.get("GOOGLE_SHEET_ID"),
                    body={"requests": [{
                        "insertDimension": {
                            "range": {
                                "sheetId": recibos_sheet_id,
                                "dimension": "ROWS",
                                "startIndex": next_row - 1,  # 0-indexed
                                "endIndex": next_row
                            },
                            "inheritFromBefore": False  # heredar formato de la fila inferior
                        }
                    }]}
                ).execute()
                logger.debug(f"[SHEETS] Fila insertada en posición {next_row} con formato de fila inferior")
            except HttpError:
                raise
            except Exception as e:
                logger.warning(f"[SHEETS] insertDimension falló, continuando con update directo. Error: {e}")

        # Escribir los valores en la fila recién insertada
        spreadsheet_name = config.get("GOOGLE_SHEET_NAME")
        update_result = sheets_service.spreadsheets().values().update(
            spreadsheetId=config.get("GOOGLE_SHEET_ID"),
            range=f'{spreadsheet_name}!A{next_row}',
            valueInputOption='USER_ENTERED',
            body={'values': valores}
        ).execute()

        logger.debug(f"[SHEETS] update result: {update_result}")
        updated_rows = update_result.get('updatedRows', 0)
        if updated_rows > 0:
            logger.info(f"[SHEETS] Recibo registrado exitosamente - updatedRows={updated_rows}")
            return True, f"✅ Operación: {valores[0][12]} registrada exitosamente\n 📌 Tipo de registro: {'Entrada' if valores[0][4] > 0 else 'Salida'}\n👩‍⚕️ Clienta: {valores[0][2]}"
        else:
            logger.warning(f"[SHEETS] Update completado pero no se detectaron filas actualizadas: {update_result}")
            return False, "⚠️ No se detectaron filas actualizadas"


def get_sheets_service(config):
    """
    Autentica y retorna el servicio de Google Sheets API
    Soporta tanto OAuth2 como Service Account
    
    Returns:
        Servicio de Google Sheets autenticado
    """
    try:
        
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        PATH = os.path.join(os.path.dirname(__file__), config.get("GOOGLE_CREDENTIALS_FILE"))
        # Verificar qué tipo de credenciales tenemos
        with open(PATH, 'r') as f:
            creds_data = json.load(f)
        
        # Si es Service Account
        if 'type' in creds_data and creds_data['type'] == 'service_account':
            logger.debug(f"[SHEETS] Usando Service Account")
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(
                PATH, scopes=SCOPES
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
        logger.exception(f"🔴 [SHEETS] Archivo {PATH} no encontrado")
        return None
    except Exception as e:
        logger.exception(f"🔴 [SHEETS] Error autenticando Google Sheets: {e}")
        return None