# Configuración de Google Sheets para Registro de Leads

Esta guía te ayudará a configurar la integración con Google Sheets para que el agente registre automáticamente los leads que soliciten citas.

## 📋 Requisitos Previos

1. Una cuenta de Google
2. Acceso a Google Cloud Console
3. Una hoja de cálculo de Google Sheets creada

## 🔧 Pasos de Configuración

### 1. Crear un Proyecto en Google Cloud

1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuevo proyecto o selecciona uno existente
3. Habilita la API de Google Sheets:
   - Ve a "APIs y servicios" > "Biblioteca"
   - Busca "Google Sheets API"
   - Haz clic en "Habilitar"

### 2. Crear una Cuenta de Servicio

1. En Google Cloud Console, ve a "APIs y servicios" > "Credenciales"
2. Haz clic en "Crear credenciales" > "Cuenta de servicio"
3. Completa el formulario:
   - **Nombre**: `python-agent-sheets`
   - **Descripción**: `Cuenta para registrar leads desde WhatsApp Bot`
4. Haz clic en "Crear y continuar"
5. En "Otorgar acceso", puedes dejarlo vacío
6. Haz clic en "Listo"

### 3. Generar la Clave JSON

1. En la lista de cuentas de servicio, haz clic en la que acabas de crear
2. Ve a la pestaña "Claves"
3. Haz clic en "Agregar clave" > "Crear nueva clave"
4. Selecciona "JSON" y haz clic en "Crear"
5. Se descargará un archivo JSON automáticamente
6. Guarda este archivo en `/home/leanusr/python-agent/credentials.json`

```bash
# Cambiar permisos del archivo de credenciales
chmod 600 /home/leanusr/python-agent/credentials.json
```

### 4. Preparar la Hoja de Cálculo

1. Crea una nueva hoja de cálculo en Google Sheets
2. Renombra la primera pestaña a **"Leads"**
3. Agrega los siguientes encabezados en la primera fila:

| A | B | C | D | E | F | G | H | I | J |
|---|---|---|---|---|---|---|---|---|---|
| Fecha/Hora | Nombre | Teléfono | Email | Empresa | Rubro | Volumen Mensajes | Lead ID | Estado | Origen |

4. Copia el ID de la hoja de cálculo desde la URL:
   ```
   https://docs.google.com/spreadsheets/d/[ESTE_ES_EL_ID]/edit
   ```

5. **Importante**: Comparte la hoja con la cuenta de servicio:
   - Haz clic en "Compartir"
   - Pega el email de la cuenta de servicio (está en el archivo JSON, campo `client_email`)
   - Dale permiso de "Editor"
   - Haz clic en "Enviar"

### 5. Configurar el Archivo .env

Edita el archivo `.env` y actualiza estas variables:

```bash
# Google Sheets Integration
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEET_ID=tu_id_de_hoja_aqui
GOOGLE_CREDENTIALS_FILE=service-account.json
```

### 6. Reiniciar el Agente

```bash
cd /home/leanusr/python-agent
./agent-manager.sh restart
```

## 📊 Estructura de Datos

Cuando un usuario solicita una cita, se registrará automáticamente con la siguiente información:

- **Fecha/Hora**: Timestamp del registro
- **Nombre**: Nombre del contacto
- **Teléfono**: Número de WhatsApp
- **Email**: Email si fue proporcionado
- **Empresa**: Nombre de la empresa si fue proporcionado
- **Rubro**: Sector del negocio
- **Volumen Mensajes**: Cantidad de mensajes diarios que recibe
- **Lead ID**: ID del lead en Krayin CRM (si está habilitado)
- **Estado**: Estado actual del lead (ej: "Cita Solicitada")
- **Origen**: Siempre será "WhatsApp Bot"

## 🔍 Verificar el Funcionamiento

1. Envía un mensaje a tu bot de WhatsApp solicitando una cita
2. Completa la conversación hasta que el bot envíe el link de reserva
3. Verifica que aparezca una nueva fila en tu hoja de Google Sheets

## 🐛 Solución de Problemas

### Error: "Error autenticando Google Sheets"

- Verifica que el archivo `credentials.json` existe en la ruta correcta
- Verifica que los permisos del archivo sean correctos (`chmod 600`)
- Asegúrate de que la cuenta de servicio tenga la API de Sheets habilitada

### Error: "No hay hoja de cálculo configurada"

- Verifica que `GOOGLE_SHEET_ID` esté correctamente configurado en `.env`
- El ID debe ser solo la parte entre `/d/` y `/edit` de la URL

### Error: "The caller does not have permission"

- Asegúrate de haber compartido la hoja con el email de la cuenta de servicio
- El email está en `credentials.json` en el campo `client_email`
- Dale permisos de "Editor", no solo de "Viewer"

### Los datos no aparecen en la hoja

- Verifica que `GOOGLE_SHEETS_ENABLED=true` en `.env`
- Revisa los logs: `tail -f /home/leanusr/python-agent/agent_verbose.log | grep SHEETS`
- Busca mensajes como "[SHEETS] ✅ Lead registrado exitosamente"

## 📝 Logs

Para ver los logs relacionados con Google Sheets:

```bash
# Ver logs en tiempo real
tail -f /home/leanusr/python-agent/agent_verbose.log | grep SHEETS

# Buscar registros exitosos
grep "\[SHEETS\] ✅" agent_verbose.log

# Buscar errores
grep "\[SHEETS\].*Error" agent_verbose.log
```

## 🔒 Seguridad

- El archivo `credentials.json` contiene información sensible
- Asegúrate de no subirlo a repositorios públicos
- Ya está incluido en `.gitignore` por defecto
- Mantén los permisos restrictivos: `chmod 600 credentials.json`

## ⚙️ Desactivar la Integración

Si deseas desactivar temporalmente la integración:

```bash
# Edita .env y cambia:
GOOGLE_SHEETS_ENABLED=false

# Reinicia el agente
./agent-manager.sh restart
```

## 🎯 Ejemplo de Fila Registrada

```
Fecha/Hora: 2026-01-22 14:30:15
Nombre: Juan Pérez
Teléfono: 5491131376731
Email: juan@empresa.com
Empresa: Empresa ABC
Rubro: Retail
Volumen Mensajes: 500
Lead ID: 10
Estado: Cita Solicitada
Origen: WhatsApp Bot
```

## 📞 Soporte

Si tienes problemas con la configuración, revisa:
1. Los logs del agente: `tail -f agent_verbose.log`
2. La documentación oficial de Google Sheets API: https://developers.google.com/sheets/api
3. Verifica que todas las dependencias estén instaladas:
   ```bash
   ./venv/bin/pip list | grep google
   ```

## ✨ Funcionalidades Futuras

- Actualización automática de estado cuando el usuario agenda la cita
- Dashboard de estadísticas desde la hoja
- Notificaciones por email cuando se registra un nuevo lead
- Integración con Google Data Studio para visualización
