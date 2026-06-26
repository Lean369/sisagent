# Crear Service Account para Google Sheets

## Pasos para crear una Service Account:

### 1. Ir a Google Cloud Console
- URL: https://console.cloud.google.com/
- Proyecto: `deft-velocity-484422-s0`

### 2. Crear Service Account
1. Ve a "IAM y administración" > "Cuentas de servicio"
2. Haz clic en "CREAR CUENTA DE SERVICIO"
3. Completa:
   - **Nombre**: `python-agent-sheets`
   - **ID**: `python-agent-sheets`
   - **Descripción**: `Cuenta para registrar leads en Google Sheets`
4. Haz clic en "CREAR Y CONTINUAR"
5. En "Otorgar a esta cuenta de servicio acceso al proyecto", déjalo vacío
6. Haz clic en "CONTINUAR"
7. Haz clic en "LISTO"

### 3. Crear y Descargar Clave JSON
1. En la lista de cuentas de servicio, haz clic en la recién creada
2. Ve a la pestaña "CLAVES"
3. Haz clic en "AGREGAR CLAVE" > "Crear clave nueva"
4. Selecciona tipo "JSON"
5. Haz clic en "CREAR"
6. Se descargará un archivo JSON

### 4. Subir el archivo al servidor

Opción A - Usando SCP (desde tu computadora):
```bash
scp ~/Downloads/deft-velocity-*.json leanusr@tu-servidor:/home/leanusr/python-agent/service-account.json
```

Opción B - Copiar y pegar:
```bash
# En el servidor
nano /home/leanusr/python-agent/service-account.json
# Pega el contenido del archivo JSON descargado
# Guarda con Ctrl+O, Enter, Ctrl+X
```

### 5. Configurar permisos
```bash
cd /home/leanusr/python-agent
chmod 600 service-account.json
```

### 6. Actualizar .env
```bash
# Edita el archivo .env
nano .env

# Cambia esta línea:
GOOGLE_CREDENTIALS_FILE=service-account.json
```

### 7. Compartir la hoja con la Service Account

si da error de permisos:
2026-06-25 21:35:52.754 | ERROR    | app.services.google_sheets:_escribir_en_sheets:120 - 🔴 [SHEETS] Error HTTP 403 de Google Sheets API: The caller does not have permission

Debes compartir la hoja de Google Sheets con la service account:

1. Abre tu hoja de Google Sheets
2. Haz clic en "Compartir"
3. Copia el email de la service account del archivo JSON (campo `client_email`)
   - Será algo como: `python-agent-sheets@deft-velocity-484422-s0.iam.gserviceaccount.com`
4. Pégalo en el campo de compartir
5. Dale permisos de "Editor"
6. Desmarca "Notificar a las personas"
7. Haz clic en "Compartir"

### 8. Verificar que la hoja funciona
 
Si la Google Sheets API no está habilitada en el proyecto de Google Cloud.

2026-06-25 21:29:51.161 | ERROR    | app.services.google_sheets:_escribir_en_sheets:120 - 🔴 [SHEETS] Error HTTP 403 de Google Sheets API: Google Sheets API has not been used in project 726646446648 before or it is disabled.

Habilitala directamente desde este link (ya incluye el project ID del error):

https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=726646446648


### 10. Reiniciar el agente
```bash
./agent-manager.sh restart
```

## ✅ Verificar que funciona
```bash
# Ver logs de Google Sheets
tail -f agent_verbose.log | grep SHEETS
```

Deberías ver:
- `[SHEETS] Servicio de Google Sheets autenticado exitosamente`
- `[SHEETS] ✅ Lead registrado exitosamente en Google Sheets`

## 🔍 El archivo JSON debe tener esta estructura:
```json
{
  "type": "service_account",
  "project_id": "deft-velocity-484422-s0",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...",
  "client_email": "python-agent-sheets@deft-velocity-484422-s0.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "..."
}
```

Lo importante es que tenga `"type": "service_account"`.
