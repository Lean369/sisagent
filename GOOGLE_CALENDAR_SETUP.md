# Configuración de Google Calendar API

## ⚠️ Estado Actual

Las funciones de calendario requieren credenciales de Google Calendar que **aún no están configuradas**.

## 📋 Funciones Disponibles

El agente tiene tres funciones de calendario:

1. **`generar_link_calendario`**: Genera un link de Google Calendar (NO requiere credenciales)
2. **`agendar_cita`**: Agenda cita directamente en el calendario (REQUIERE credenciales)
3. **`obtener_slots_disponibles`**: Muestra horarios disponibles (REQUIERE credenciales)

## 🔧 Configuración Requerida

Para habilitar las funciones de calendario completas, necesitas:

### Paso 1: Crear Proyecto en Google Cloud

1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuevo proyecto o selecciona uno existente
3. Habilita la **Google Calendar API**:
   - Menú → APIs y servicios → Biblioteca
   - Busca "Google Calendar API"
   - Haz clic en "Habilitar"

### Paso 1.5: Configurar Pantalla de Consentimiento OAuth

**⚠️ IMPORTANTE**: Debes configurar esto ANTES de crear credenciales.

1. Ve a [Pantalla de consentimiento](https://console.cloud.google.com/apis/credentials/consent)
2. Selecciona **"External"** (Usuario externo)
3. Haz clic en **"CREATE"**
4. Completa la información básica:
   - **App name**: Python Agent Calendar
   - **User support email**: Tu email
   - **Developer contact**: Tu email
5. Haz clic en **"SAVE AND CONTINUE"** (omitir scopes)
6. En la sección **"Test users"**:
   - Haz clic en **"+ ADD USERS"**
   - Agrega tu email (el que usarás para autenticar)
   - Haz clic en **"SAVE AND CONTINUE"**
7. Revisa y haz clic en **"BACK TO DASHBOARD"**

**Opcional - Publicar la app** (Recomendado para evitar límite de usuarios de prueba):
1. En el dashboard, haz clic en **"PUBLISH APP"**
2. Confirma - No necesitas verificación de Google para uso personal
3. Estado: "Testing" → "In production"

### Paso 2: Crear Credenciales OAuth 2.0

1. Ve a [Credenciales](https://console.cloud.google.com/apis/credentials)
2. Haz clic en "Crear credenciales" → "ID de cliente de OAuth"
3. **IMPORTANTE**: Tipo de aplicación: **Aplicación de escritorio** (NO web)
4. Nombre: "Python Agent Calendar"
5. Haz clic en "Crear"
6. **NO necesitas agregar URIs de redirección** (las apps de escritorio usan localhost automáticamente)

**⚠️ Si ya creaste las credenciales como "Aplicación web"**:
1. Ve a tus credenciales existentes
2. Cámbialas a "Aplicación de escritorio"
3. O crea nuevas credenciales como "Aplicación de escritorio"

**Nota**: Las aplicaciones de escritorio de Google OAuth automáticamente permiten cualquier puerto en `http://localhost`, por lo que no necesitas configurar URIs específicas.

### Paso 3: Descargar y Guardar Credenciales

1. Descarga el archivo JSON de credenciales
2. Renómbralo a `credentials.json`
3. Guárdalo en: `/home/leanusr/python-agent/credentials.json`

```bash
# Verificar que el archivo existe
ls -la /home/leanusr/python-agent/credentials.json
```

### Paso 4: Primera Autenticación

**⚠️ IMPORTANTE**: La autenticación debe hacerse ANTES de iniciar el agente en background.

#### Opción 1: Script Automático (Recomendado)

```bash
cd /home/leanusr/python-agent
./venv/bin/python setup_calendar_auth.py
```

Este script:
- ✅ Verifica que `credentials.json` existe
- ✅ Abre el navegador para autenticación
- ✅ Guarda `token.pickle` automáticamente
- ✅ Prueba el acceso al calendario

#### Opción 2: Manual

La primera vez que el agente use las funciones de calendario:

1. **NO** inicies el agente en background con `nohup`
2. Ejecuta directamente: `./venv/bin/python agent.py`
3. Cuando intente acceder al calendario, se abrirá un navegador
4. Inicia sesión con tu cuenta de Google
5. Acepta los permisos solicitados
6. Se creará automáticamente `token.pickle`
7. Presiona Ctrl+C para detener el agente
8. Ahora sí puedes iniciarlo en background

### Solución al Error de Redirección

**Error**: `No puedes acceder a esta app porque no cumple con la política OAuth 2.0 de Google`
```
redirect_uri=http://localhost:XXXXX/
```

**Causa**: Las credenciales fueron creadas como "Aplicación web" en lugar de "Aplicación de escritorio"

**Solución**:
1. Ve a [Google Cloud Console - Credenciales](https://console.cloud.google.com/apis/credentials)
2. Encuentra tu credencial OAuth 2.0
3. **Opción A**: Editar la credencial existente
   - Haz clic en el nombre de la credencial
   - Si dice "Web application" arriba, no puedes cambiarla
   - Elimínala y crea una nueva
4. **Opción B**: Crear nueva credencial
   - Haz clic en "Crear credenciales" → "ID de cliente de OAuth"
   - **IMPORTANTE**: Selecciona "Aplicación de escritorio"
   - Nombre: "Python Agent Calendar Desktop"
   - Haz clic en "Crear"
5. Descarga el nuevo JSON y reemplaza `credentials.json`
6. Ejecuta nuevamente: `./venv/bin/python setup_calendar_auth.py`

**Nota**: Las aplicaciones de escritorio NO requieren configurar URIs de redirección manualmente.

---

**Error alternativo**: `redirect_uri_mismatch` con aplicación web

Si creaste las credenciales como "Aplicación web" y quieres mantenerlas así, agrega estas URIs:
- `http://localhost`
- `http://localhost:8080/`
- `http://localhost:8081/`
- `http://localhost:8082/`
(Repite hasta :8090 para cubrir puertos comunes)

Pero **recomendamos usar "Aplicación de escritorio"** que es más simple.

## 🔒 Seguridad

- **NO** subas `credentials.json` o `token.pickle` a Git
- Ya están en `.gitignore`
- Mantén estos archivos seguros

## ✅ Verificación

Para verificar que todo funciona:

```bash
cd /home/leanusr/python-agent
python -c "from agent import get_calendar_service; print(get_calendar_service())"
```

## 🚀 Estado de las Funciones

| Función | Requiere Credenciales | Estado |
|---------|----------------------|--------|
| `generar_link_calendario` | ❌ No | ✅ Funcional |
| `agendar_cita` | ✅ Sí | ⚠️ Requiere configuración |
| `obtener_slots_disponibles` | ✅ Sí | ⚠️ Requiere configuración |

## 📝 Notas

- El calendario usado es el **calendario principal** de la cuenta autenticada
- Zona horaria: `America/Argentina/Buenos_Aires`
- Horario laboral: 9:00 AM - 6:00 PM
- Solo días laborables (lunes a viernes)
