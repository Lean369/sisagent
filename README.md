# Python Agent - Asistente Virtual WhatsApp con LLM

## Descripción General

Sistema de agente conversacional inteligente que integra WhatsApp (vía Evolution API) con modelos de lenguaje (LLM) y Google Calendar. Permite mantener conversaciones contextuales con gestión automática de memoria, sistema de reservas simplificado y finalización inteligente de conversaciones.

### Características Principales

- ✅ **Gestión de Memoria con Rotación**: Límite de 50 mensajes por conversación con ventana deslizante
- ✅ **Sistema de Reservas Simplificado**: Link directo a página de reservas de Google Calendar
- ✅ **Finalización Inteligente**: No responde a saludos/agradecimientos después de enviar el link de reserva
- ✅ **Sistema de Fallback LLM**: Respaldo automático a proveedor secundario en caso de fallo del principal
- ✅ **Logging con Rotación**: Máximo 50 MB de logs con 5 archivos de respaldo
- ✅ **Multi-LLM**: Soporte para HuggingFace, Anthropic, OpenAI y Google Gemini
- ✅ **Script de Gestión**: Herramienta completa para iniciar/detener/monitorear el agente

## Arquitectura del Sistema

### Componentes Principales

```
┌─────────────────┐
│   WhatsApp      │
│   (Usuario)     │
└────────┬────────┘
         │ Webhook
         ▼
┌─────────────────────────────────────────┐
│      Evolution API                      │
│   (https://evoapi.sisnova.com.ar)       │
└────────┬────────────────────────────────┘
         │ POST /webhook
         ▼
┌─────────────────────────────────────────┐
│   Python Agent (FastAPI)                │
│   - Recepción de webhooks               │
│   - Gestión de memoria conversacional   │
│   - Procesamiento con LLM               │
│   - Integración Google Calendar         │
└────────┬────────────────────────────────┘
         │
         ├─► LLM (HuggingFace/Anthropic/OpenAI)
         └─► Google Calendar API
```

### Stack Tecnológico

- **Framework Web**: FastAPI + Uvicorn (ASGI)
- **HTTP Client**: httpx (async), requests (sync)
- **LLM Framework**: LangChain
- **Proveedores LLM**: HuggingFace (Qwen2.5-7B-Instruct - por defecto), Anthropic Claude, OpenAI, Google Gemini
- **Storage**: Memoria RAM (en proceso) con límite de 50 mensajes por conversación
- **Logging**: Python logging con RotatingFileHandler (10 MB por archivo, 5 archivos de respaldo)
- **Integraciones**: Evolution API (WhatsApp), Google Calendar Booking Pages

## Instalación

### Requisitos Previos

- Python 3.12.3+
- Cuenta en Evolution API
- API Key de al menos un proveedor LLM (HuggingFace, Anthropic, OpenAI)
- (Opcional) Credenciales de Google Calendar API

### Pasos de Instalación

```bash
# 1. Crear entorno virtual
python3 -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# 4. Ejecutar el agente
./venv/bin/python agent.py
```

## Configuración

### Variables de Entorno (.env)

```ini
# LLM Configuration
LLM_PROVIDER=gemini                # Opciones: gemini, huggingface, anthropic, openai, ollama
LLM_PROVIDER_FALLBACK=openai       # Proveedor de respaldo en caso de fallo del principal

# API Keys para diferentes proveedores
GEMINI_API_KEY=AIzaSyAxxxxx...     # Para Google Gemini
HF_MODEL=Qwen/Qwen2.5-7B-Instruct  # Modelo de HuggingFace (si LLM_PROVIDER=huggingface)
HUGGINGFACE_API_KEY=hf_xxxxx...
ANTHROPIC_API_KEY=sk-ant-xxxxx...
OPENAI_API_KEY=sk-xxxxx...

# Evolution API (WhatsApp)
EVOLUTION_API_URL=https://evoapi.sisnova.com.ar
EVOLUTION_API_KEY=9d15c6d04d216cc8becc3721d8199c20
EVOLUTION_INSTANCE=prueba-py-agent
EVOLUTION_INSTANCE_ID=b6b78f87-1d77-49b2-8164-1c68b6b42c40

# Google Calendar (opcional - solo para booking pages)
GOOGLE_BOOKING_URL=https://calendar.app.google/uxYJoEeZvCWoT3269

# Configuración de Memoria
MAX_MESSAGES=50  # Límite de mensajes por conversación (default: 50)

# Integración con Krayin CRM
KRAYIN_API_URL=https://your-krayin-instance.com/api/v1
KRAYIN_API_TOKEN=your_api_token_here
KRAYIN_PIPELINE_ID=1  # ID del pipeline de leads
KRAYIN_STAGE_ID=1  # ID de la etapa "Nuevo Lead"
KRAYIN_USER_ID=1  # ID del usuario asignado
KRAYIN_LEAD_SOURCE_ID=5  # ID de la fuente (ej: WhatsApp)
KRAYIN_LEAD_TYPE_ID=1  # ID del tipo de lead
CRM_AUTO_REGISTER=true  # true para activar registro automático al reservar
```

### Configuración de Webhook en Evolution API

```bash
curl -X POST https://evoapi.sisnova.com.ar/webhook/set/prueba-py-agent \
  -H "Content-Type: application/json" \
  -H "apikey: YOUR_API_KEY" \
  -d '{
    "url": "http://YOUR_SERVER_IP:5000/webhook",
    "webhook_by_events": false,
    "webhook_base64": false,
    "events": ["MESSAGES_UPSERT"]
  }'
```

## Gestión de Memoria Conversacional

### Arquitectura de Memoria

El sistema implementa un sistema de memoria **en RAM por usuario** con límite de **50 mensajes por conversación**:

#### Estructura de Datos

```python
user_memories: Dict[str, Memory] = {}

# Cada entrada contiene:
{
  "user_id": {
    "chat_memory": {
      "messages": [
        HumanMessage(content="..."),
        AIMessage(content="..."),
        ...
      ]
    }
  }
}
```

#### Implementación

**Ubicación en código**: `agent.py` líneas 181-234

```python
# Límite configurable vía variable de entorno
MAX_MESSAGES_PER_CONVERSATION = int(os.getenv("MAX_MESSAGES", "50"))

def get_memory(user_id: str):
    """Obtiene o crea memoria para un usuario"""
    if user_id not in user_memories:
        # Fallback: almacenar mensajes en memoria RAM
        class _SimpleChatMemory:
            def __init__(self):
                self.messages: List = []  # Lista con truncado automático

            def add_user_message(self, text: str):
                self.messages.append(HumanMessage(content=text))

            def add_ai_message(self, text: str):
                self.messages.append(AIMessage(content=text))

def truncate_memory(memory):
    """Trunca la memoria si excede el límite configurado"""
    current_count = len(memory.chat_memory.messages)
    if current_count > MAX_MESSAGES_PER_CONVERSATION:
        # Mantener solo los últimos MAX_MESSAGES_PER_CONVERSATION mensajes
        memory.chat_memory.messages = memory.chat_memory.messages[-MAX_MESSAGES_PER_CONVERSATION:]
        logger.info(f"Truncated memory: {current_count} → {MAX_MESSAGES_PER_CONVERSATION} messages")
```

### Capacidad de Almacenamiento

| Aspecto | Detalle |
|---------|---------|
| **Límite por conversación** | ✅ **50 mensajes** (25 intercambios) - Configurable vía MAX_MESSAGES |
| **Truncado automático** | ✅ **Ventana deslizante** - Mantiene los últimos 50 mensajes |
| **Persistencia** | ❌ **No persistente** - Se pierde al reiniciar el agente |
| **Scope** | Por `user_id` (número de WhatsApp con JID) |
| **Tipo de almacenamiento** | Lista Python en memoria RAM |
| **Formato de mensajes** | Par Usuario/Asistente por cada interacción |
| **Conteo** | 2 mensajes por interacción (pregunta + respuesta) |

#### Ejemplo de Uso de Memoria por Usuario

| Interacciones | Mensajes guardados | Uso estimado RAM |
|---------------|-------------------|------------------|
| 10 | 20 (10 user + 10 AI) | ~5 KB |
| 25 (límite) | **50 (truncado automático)** | ~12 KB |
| 100+ | **50 (se descartan los más antiguos)** | ~12 KB |

**Usuarios simultáneos**:

| Usuarios activos | Memoria total (50 msg/usuario) |
|------------------|--------------------------------|
| 100 | ~1.2 MB |
| 1,000 | ~12 MB |
| 10,000 | ~120 MB |

**✅ IMPLEMENTADO**: Ventana deslizante automática que mantiene solo los últimos 50 mensajes por conversación.

**⚠️ RECOMENDACIONES ADICIONALES**:
1. **Persistencia**: Guardar en base de datos (Redis, PostgreSQL) para recuperar historial
2. **Expiración**: Limpiar conversaciones inactivas después de X horas
3. **Compresión**: Resumir mensajes antiguos con LLM antes de truncar

### Adición y Truncado de Mensajes

**Ubicación en código**: `agent.py` líneas 440-470 (en función `procesar_mensaje`)

```python
# Guardar en memoria
memory.chat_memory.add_user_message(mensaje)
memory.chat_memory.add_ai_message(respuesta)

# Truncar memoria si excede el límite
truncate_memory(memory)
```

Cada llamada a `procesar_mensaje()` añade **2 mensajes** a la lista:
1. El mensaje del usuario (`HumanMessage`)
2. La respuesta del asistente (`AIMessage`)

Luego, `truncate_memory()` verifica si se excedió el límite de 50 mensajes y automáticamente descarta los más antiguos, manteniendo solo los últimos 50.

**Logs de truncado**:
```
2026-01-20 10:15:23 INFO python-agent: Truncated memory: 52 → 50 messages
```

## Sistema de Fallback para Proveedores LLM

### Descripción

El sistema implementa un mecanismo de respaldo automático que permite cambiar a un proveedor LLM secundario en caso de que el proveedor principal falle. Esto mejora la disponibilidad del servicio y previene interrupciones cuando:

- El proveedor principal agota su cuota (429 RESOURCE_EXHAUSTED)
- Hay problemas de conectividad con la API del proveedor
- El servicio del proveedor está temporalmente fuera de línea
- Se exceden los límites de rate limiting

### Configuración

**Variables de entorno**:

```ini
# Proveedor LLM principal
LLM_PROVIDER=gemini

# Proveedor de respaldo (se usa automáticamente si el principal falla)
LLM_PROVIDER_FALLBACK=openai
```

### Flujo de Funcionamiento

```
┌─────────────────────────────────────────────────┐
│  Usuario envía mensaje                          │
└────────────┬────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────┐
│  Intento con Proveedor Principal (gemini)       │
└────────┬────────────────────────────────────┬───┘
         │ Éxito                              │ Error
         ▼                                    ▼
┌──────────────────┐          ┌─────────────────────────────────┐
│  Respuesta al    │          │  Log: Error con proveedor       │
│  usuario         │          │  principal                      │
└──────────────────┘          └────────────┬────────────────────┘
                                           │
                                           ▼
                              ┌─────────────────────────────────┐
                              │  Intento con Fallback (openai)  │
                              └────────┬────────────────────┬───┘
                                       │ Éxito              │ Error
                                       ▼                    ▼
                              ┌──────────────────┐  ┌──────────────────┐
                              │  Respuesta al    │  │  Mensaje de      │
                              │  usuario         │  │  error genérico  │
                              └──────────────────┘  └──────────────────┘
```

### Implementación

**Ubicación en código**: `agent.py`

#### 1. Función `get_llm_model()` modificada (líneas 395-405)

```python
def get_llm_model(provider_override=None):
    """Retorna el modelo LLM según la configuración
    
    Args:
        provider_override: Si se especifica, usa este provider en lugar del configurado
    """
    provider = (provider_override or LLM_PROVIDER).lower()
    logger.debug("Configuring LLM provider: %s", provider)
    
    # ... resto de la implementación
```

#### 2. Lógica de fallback en `procesar_mensaje()` (líneas ~710-735)

```python
# Invocar LLM con sistema de fallback
try:
    respuesta_llm = agente.invoke(messages)
    respuesta = respuesta_llm.content
except Exception as llm_error:
    logger.error(f"Error con LLM provider principal ({LLM_PROVIDER}): {llm_error}")
    
    # Intentar con el fallback si está configurado
    fallback_provider = os.getenv('LLM_PROVIDER_FALLBACK', '').strip()
    if fallback_provider and fallback_provider.lower() != LLM_PROVIDER.lower():
        logger.warning(f"⚠️ Intentando con proveedor de respaldo: {fallback_provider}")
        try:
            # Obtener instancia del LLM de fallback
            agente_fallback = get_llm_model(provider_override=fallback_provider)
            respuesta_llm = agente_fallback.invoke(messages)
            respuesta = respuesta_llm.content
            logger.info(f"✅ Respuesta exitosa con proveedor de respaldo: {fallback_provider}")
        except Exception as fallback_error:
            logger.error(f"❌ Error también con proveedor de respaldo ({fallback_provider}): {fallback_error}")
            return "Gracias por contactarnos. En este momento estamos experimentando dificultades técnicas..."
    else:
        logger.error("❌ No hay proveedor de respaldo configurado o es el mismo que el principal")
        return "Gracias por contactarnos. En este momento estamos experimentando dificultades técnicas..."
```

### Ejemplo de Logs

**Caso exitoso con proveedor principal**:
```
2026-01-22 23:10:45 DEBUG python-agent: Configuring LLM provider: gemini
2026-01-22 23:10:46 INFO python-agent: [RESPUESTA DEL LLM]: Hola 👋 ¡Gracias por escribirnos!
```

**Caso con fallback (proveedor principal falló)**:
```
2026-01-22 23:15:30 DEBUG python-agent: Configuring LLM provider: gemini
2026-01-22 23:15:32 ERROR python-agent: Error con LLM provider principal (gemini): 429 RESOURCE_EXHAUSTED
2026-01-22 23:15:32 WARNING python-agent: ⚠️ Intentando con proveedor de respaldo: openai
2026-01-22 23:15:32 DEBUG python-agent: Configuring LLM provider: openai
2026-01-22 23:15:34 INFO python-agent: ✅ Respuesta exitosa con proveedor de respaldo: openai
2026-01-22 23:15:34 INFO python-agent: [RESPUESTA DEL LLM]: Hola 👋 ¡Gracias por escribirnos!
```

**Caso con ambos proveedores fallando**:
```
2026-01-22 23:20:10 ERROR python-agent: Error con LLM provider principal (gemini): Connection timeout
2026-01-22 23:20:10 WARNING python-agent: ⚠️ Intentando con proveedor de respaldo: openai
2026-01-22 23:20:12 ERROR python-agent: ❌ Error también con proveedor de respaldo (openai): Invalid API key
2026-01-22 23:20:12 INFO python-agent: [RESPUESTA]: Gracias por contactarnos. En este momento estamos experimentando dificultades técnicas...
```

### Configuraciones Recomendadas

| Proveedor Principal | Proveedor Fallback | Razón |
|---------------------|-------------------|-------|
| `gemini` | `openai` | ✅ Gemini (gratuito) con OpenAI como respaldo confiable |
| `huggingface` | `openai` | ✅ HuggingFace (gratuito) con OpenAI de respaldo |
| `anthropic` | `gemini` | ✅ Claude con Gemini como alternativa económica |
| `openai` | `gemini` | ✅ OpenAI premium con Gemini gratuito de respaldo |

### Ventajas del Sistema

1. **Mayor disponibilidad**: El servicio continúa funcionando aunque un proveedor falle
2. **Ahorro de costos**: Usa proveedores gratuitos/económicos como principal y paga solo cuando fallan
3. **Gestión de cuotas**: Evita interrupciones cuando se agota la cuota del proveedor gratuito
4. **Logging completo**: Visibilidad total del comportamiento para debugging
5. **Sin cambios manuales**: Todo es automático, no requiere intervención
6. **Configuración simple**: Solo requiere dos variables de entorno

### Consideraciones

⚠️ **Importante**:
- El fallback solo se activa si el proveedor principal falla completamente
- Ambos proveedores deben tener sus API keys configuradas
- El fallback debe ser diferente del principal (se verifica automáticamente)
- Cada cambio de proveedor registra logs para auditoría

````### Monitoreo de Memoria

#### Endpoints Disponibles

##### 1. Lista de usuarios en memoria
```bash
GET http://localhost:5000/memory
```

**Respuesta**:
```json
{
  "5491131376731@s.whatsapp.net": 6,
  "5491144125978@s.whatsapp.net": 14
}
```

##### 2. Detalle de memoria por usuario
```bash
GET http://localhost:5000/memory/5491131376731@s.whatsapp.net
```

**Respuesta**:
```json
{
  "user_id": "5491131376731@s.whatsapp.net",
  "count": 6,
  "messages": [
    {"role": "HumanMessage", "content": "Hola"},
    {"role": "AIMessage", "content": "Hola! Recibí tu mensaje..."},
    {"role": "HumanMessage", "content": "¿Cómo estás?"},
    {"role": "AIMessage", "content": "Hola! Recibí tu mensaje..."}
  ]
}
```

## API Endpoints

### Webhook Receiver

```http
POST /webhook
Content-Type: application/json

{
  "event": "messages.upsert",
  "instance": "prueba-py-agent",
  "data": {
    "key": {
      "remoteJid": "5491131376731@s.whatsapp.net",
      "fromMe": false
    },
    "message": {
      "conversation": "Hola, necesito ayuda"
    }
  }
}
```

**Comportamiento**:
1. Extrae mensaje y remitente
2. Verifica que `fromMe=false` (no procesar mensajes propios)
3. Obtiene memoria del usuario
4. Invoca LLM con contexto completo
5. Envía respuesta vía Evolution API
6. Guarda intercambio en memoria

### Health Check

```http
GET /health
```

**Respuesta**: `{"status": "ok"}`

### Memory Inspection

```http
GET /memory
GET /memory/{user_id}
```

Ver sección "Monitoreo de Memoria" arriba.

## Flujo de Procesamiento de Mensajes

```
1. Webhook recibido desde Evolution API
   ↓
2. Validación (no procesar si fromMe=true)
   ↓
3. Extracción de datos (remitente, mensaje)
   ↓
4. get_memory(user_id)
   ├─ Si existe: cargar conversación histórica
   └─ Si no existe: crear nueva memoria vacía
   ↓
5. Construcción del prompt
   ├─ System prompt con instrucciones
   ├─ Mensajes históricos del usuario
   └─ Nuevo mensaje del usuario
   ↓
6. Invocación del LLM
   ↓
7. Procesamiento de respuesta
   ├─ Detectar acción (ej: agendar cita)
   └─ Ejecutar acción si es necesario
   ↓
8. Envío de respuesta vía Evolution API
   ├─ Fallback 1: instance name (prueba-py-agent)
   ├─ Fallback 2: instance UUID
   └─ Fallback 3: EVOLUTION_INSTANCE desde .env
   ↓
9. Guardado en memoria
   ├─ memory.chat_memory.add_user_message(mensaje)
   └─ memory.chat_memory.add_ai_message(respuesta)
   ↓
10. Retornar {"status": "success"}
```

## Sistema de Reservas de Citas

### Funcionamiento Simplificado

El agente utiliza un sistema de reservas **simplificado** que envía al usuario un link a una página de reservas de Google Calendar pre-configurada.

#### Ventajas del Sistema Actual

- ✅ **Sin autenticación OAuth**: No requiere configurar credenciales de Google Calendar
- ✅ **Sin complejidad**: Una sola herramienta (`enviar_link_reserva`)
- ✅ **Control total**: El usuario ve disponibilidad real y elige fecha/hora
- ✅ **Experiencia mejor**: Link profesional de Google Calendar
- ✅ **Sin errores del LLM**: No necesita extraer fechas/horas del lenguaje natural

#### Configuración

1. **Crear página de reservas en Google Calendar**:
   - Ve a [Google Calendar](https://calendar.google.com)
   - Configuración > Páginas de reservas
   - Crea una nueva página de reservas
   - Configura horarios disponibles y duración de citas

2. **Copiar URL de la página de reservas**:
   ```
   https://calendar.app.google/uxYJoEeZvCWoT3269
   ```

3. **Configurar en .env**:
   ```ini
   GOOGLE_BOOKING_URL=https://calendar.app.google/uxYJoEeZvCWoT3269
   ```

#### Flujo de Conversación

```
Usuario: "Quiero agendar una cita"
    ↓
Agente detecta intención → {"accion": "reserva", "motivo": ""}
    ↓
Agente envía link de reserva:
    📅 *Agenda tu cita aquí*
    
    Para reservar tu cita, haz clic en el siguiente enlace:
    https://calendar.app.google/uxYJoEeZvCWoT3269
    
    ✅ Podrás ver los horarios disponibles
    ✅ Elegir la fecha y hora que prefieras
    ✅ Confirmar tu reserva al instante
    
    ¿Necesitas ayuda con algo más?
    ↓
[CONVERSACIÓN FINALIZADA]
    ↓
Usuario: "gracias" / "hola" / "ok"
    ↓
Agente NO responde (mensaje genérico después de reserva)
    ↓
Usuario: "¿puedo cambiar la fecha?"
    ↓
Agente responde (pregunta real, reinicia conversación)
```

### Sistema de Finalización de Conversación

#### Comportamiento Inteligente

El agente implementa un sistema de **finalización automática** para evitar respuestas innecesarias:

**Después de enviar el link de reserva**:
- ❌ **NO responde** a mensajes genéricos: "hola", "gracias", "ok", "perfecto", "listo"
- ✅ **SÍ responde** a preguntas reales: "¿puedo cambiar la fecha?", "¿cuánto cuesta?"

#### Detección de Mensajes Genéricos

**Ubicación en código**: `agent.py` función `es_mensaje_generico()`

```python
def es_mensaje_generico(mensaje: str) -> bool:
    """Detecta si un mensaje es solo un saludo o agradecimiento genérico"""
    # Palabras genéricas detectadas:
    palabras_genericas = [
        'hola', 'hello', 'hi', 'buenas', 'buenos dias',
        'gracias', 'thanks', 'ok', 'okay', 'dale', 
        'perfecto', 'excelente', 'listo', 'entendido',
        'chau', 'adiós', 'bye', 'hasta luego'
    ]
    
    # Mensajes cortos (<20 caracteres) que coinciden con palabras genéricas
    # NO se consideran genéricos si tienen "?" (son preguntas)
```

#### Flag de Estado: `booking_sent`

Cada memoria de usuario tiene un flag `booking_sent` que rastrea el estado:

```python
memory.booking_sent = False  # Conversación normal
memory.booking_sent = True   # Link enviado, solo responder a preguntas reales
```

**Logs de finalización**:
```
2026-01-21 13:59:36 INFO python-agent: [BOOKING] Conversación marcada como completada para user_id=...
2026-01-21 13:59:45 INFO python-agent: [BOOKING] Conversación finalizada. Mensaje genérico ignorado: hola
2026-01-21 14:05:12 INFO python-agent: [BOOKING] Nueva pregunta después del link, continuando conversación: ¿puedo cambiar la fecha?
```

### Prompt del Sistema

**Ubicación en código**: `agent.py` función `procesar_mensaje()` (usando `AGENT_INSTRUCTION` de `prompts.py`)

El prompt instruye al LLM a:
1. Detectar intención de agendar/reservar
2. Responder SOLO con JSON: `{"accion": "reserva", "motivo": "opcional"}`
3. NO preguntar fecha, hora ni duración al cliente
4. El motivo es opcional para contexto

## Integración con Krayin CRM

### Registro Automático de Leads

El agente puede registrar automáticamente leads en **Krayin CRM** cuando un usuario solicita reservar una cita.

#### Características

- ✅ **Registro automático**: Crea lead cuando se envía link de reserva
- ✅ **Información completa**: Guarda nombre, teléfono, empresa, rubro
- ✅ **Valor calculado**: Estima valor del lead basado en información
- ✅ **Configurable**: Se puede activar/desactivar con variable de entorno
- ✅ **Logging completo**: Registra todo el proceso con prefijo [CRM]

#### Configuración

**Variables de entorno requeridas**:

```ini
# URL de tu instancia Krayin
KRAYIN_API_URL=https://your-krayin.com/api/v1

# Token de autenticación de la API
KRAYIN_API_TOKEN=your_api_token_here

# IDs de configuración (obtener desde Krayin)
KRAYIN_PIPELINE_ID=1        # ID del pipeline de leads
KRAYIN_STAGE_ID=1           # ID de la etapa inicial
KRAYIN_USER_ID=1            # ID del usuario asignado
KRAYIN_LEAD_SOURCE_ID=5     # ID de la fuente (WhatsApp)
KRAYIN_LEAD_TYPE_ID=1       # ID del tipo de lead

# Bandera de activación
CRM_AUTO_REGISTER=true      # true o false
```

#### Flujo de Registro

```
Usuario solicita cita
    ↓
LLM detecta: {"accion": "reserva"}
    ↓
Sistema envía link de reserva
    ↓
[SI CRM_AUTO_REGISTER=true]
    ↓
Extrae datos: nombre, teléfono
    ↓
Crea persona en Krayin CRM
    ↓
Crea lead con información completa:
  - Título: "Nombre - Empresa"
  - Descripción: Rubro, volumen mensajes, notas
  - Valor: Calculado automáticamente
  - Pipeline: Configurado
  - Etapa: "Nuevo Lead"
    ↓
Guarda lead_id en memoria
    ↓
Log: ✅ Lead creado en Krayin CRM (ID: 123, Valor: $500)
```

#### Estructura de Datos del Lead

**Información almacenada en `user_lead_info[user_id]`**:

```python
{
    "nombre": "Juan Pérez",          # De push_name o "Lead desde WhatsApp"
    "telefono": "5491131376731",     # Extraído del user_id
    "empresa": "",                   # Opcional (futuro)
    "rubro": "",                     # Opcional (futuro)
    "volumen_mensajes": "",          # Opcional (futuro)
    "email": "",                     # Opcional (futuro)
    "lead_id": 123                   # ID en Krayin después de crear
}
```

#### Cálculo de Valor del Lead

El sistema calcula automáticamente el valor estimado del lead:

```python
# Si hay información de volumen de mensajes
valor = max(volumen_mensajes * 10, 500)

# Ejemplo:
# 100 mensajes/día → $1,000
# 50 mensajes/día → $500 (mínimo)
# Sin info → $500 (valor por defecto)
```

#### Funciones CRM

**1. `registrar_lead_en_crm(user_id, telefono)`**
- Punto de entrada principal
- Obtiene información de `user_lead_info`
- Llama a `crear_lead_krayin()`
- Guarda `lead_id` en memoria

**2. `crear_lead_krayin(...)`**
- Crea persona con `crear_persona_krayin()`
- Construye título y descripción
- Calcula valor del lead
- Crea lead en Krayin
- Retorna resultado

**3. `crear_persona_krayin(nombre, telefono, email)`**
- Crea contacto en CRM
- Retorna `person_id`
- Maneja errores de API

**4. `actualizar_lead_krayin(lead_id, stage_id, notas)`**
- Actualiza etapa del lead
- Agrega notas al lead
- Disponible para uso futuro

## Envío de Mensajes (Fallback Strategy)

### Algoritmo de Reintentos

El sistema intenta enviar mensajes usando múltiples identificadores en orden:

```python
candidates = [
  webhook_instance_id,      # 1. ID recibido en el webhook
  webhook_instance_name,    # 2. Nombre de instancia del webhook  
  EVOLUTION_INSTANCE_ID,    # 3. UUID desde .env
  EVOLUTION_INSTANCE        # 4. Nombre desde .env
]

for candidate in candidates:
    response = POST /message/sendText/{candidate}
    if 200 <= status < 300:
        return response  # Éxito
    # Continuar con siguiente candidato
```

### Manejo de Errores

- **HTTP 401 Unauthorized**: API key incorrecta
- **HTTP 404 Not Found**: Instancia no existe
- **HTTP 400 Bad Request**: JID no existe o formato inválido
- **HTTP 201 Created**: ✅ Mensaje enviado exitosamente (status: PENDING)

Todos los intentos se registran en `agent_verbose.log`:

```
DEBUG python-agent: Tried sendText with candidate=prueba-py-agent status=201 response={...}
```

## Logging y Monitoreo

### Sistema de Rotación de Archivos

El agente implementa un sistema de **rotación automática de logs** para prevenir que los archivos llenen el disco:

**Configuración**: `agent.py` líneas 56-73

```python
from logging.handlers import RotatingFileHandler

# Mantiene hasta 10MB por archivo, con 5 archivos de respaldo (total: 50MB máximo)
rotating_handler = RotatingFileHandler(
    'agent_verbose.log',
    maxBytes=10*1024*1024,  # 10 MB por archivo
    backupCount=5,  # Mantener 5 archivos de respaldo
    encoding='utf-8'
)
```

### Archivos de Log

| Archivo | Tamaño máximo | Propósito |
|---------|---------------|-----------|
| `agent_verbose.log` | 10 MB (activo) | Logs detallados con nivel DEBUG |
| `agent_verbose.log.1` | 10 MB | Respaldo más reciente |
| `agent_verbose.log.2` | 10 MB | Respaldo |
| `agent_verbose.log.3` | 10 MB | Respaldo |
| `agent_verbose.log.4` | 10 MB | Respaldo |
| `agent_verbose.log.5` | 10 MB | Respaldo más antiguo |

**Total máximo**: ~50 MB en disco

**Rotación automática**: Cuando `agent_verbose.log` alcanza 10 MB:
1. `.log` → `.log.1`
2. `.log.1` → `.log.2`
3. ... 
4. `.log.5` se elimina (más antiguo)

### Niveles de Logging

```python
DEBUG: Todos los eventos (HTTP, memoria, procesamiento)
INFO: Webhooks recibidos, mensajes procesados, reservas
WARNING: Problemas no críticos, errores de JSON
ERROR: Fallos en envío de mensajes, excepciones
```

### Logs Específicos del Sistema de Reservas

```
# Generación de link
INFO python-agent: [BOOKING] Generando link de reserva - Motivo: consulta proyecto

# Link enviado exitosamente  
INFO python-agent: [BOOKING] Link de reserva generado exitosamente

# Conversación marcada como finalizada
INFO python-agent: [BOOKING] Conversación marcada como completada para user_id=5491131376731@s.whatsapp.net

# Mensaje genérico ignorado
INFO python-agent: [BOOKING] Conversación finalizada. Mensaje genérico ignorado: gracias

# Conversación reiniciada
INFO python-agent: [BOOKING] Nueva pregunta después del link, continuando conversación: ¿puedo cambiar la fecha?

# No se envía respuesta
INFO python-agent: [BOOKING] No se envía respuesta - conversación finalizada
```

### Logs Específicos de Krayin CRM

```
# Inicio de registro
INFO python-agent: [CRM] Iniciando registro de lead para user_id=5491131376731@s.whatsapp.net, telefono=5491131376731

# Información del lead
DEBUG python-agent: [CRM] Información del lead: {'nombre': 'Juan', 'telefono': '5491131376731', ...}

# Creación de persona
INFO python-agent: [CRM] Creando persona - Nombre: Juan, Telefono: 5491131376731
DEBUG python-agent: [CRM] Datos de persona: {'name': 'Juan', 'contact_numbers': [{'value': '5491131376731', 'label': 'work'}]}
INFO python-agent: [CRM] Persona creada exitosamente - person_id=45

# Creación de lead
INFO python-agent: [CRM] Creando lead en Krayin - Nombre: Juan, Telefono: 5491131376731
DEBUG python-agent: [CRM] Paso 1: Creando persona en Krayin
INFO python-agent: [CRM] Persona creada exitosamente - person_id=45
DEBUG python-agent: [CRM] Valor del lead calculado: $500 (basado en 100 mensajes)
DEBUG python-agent: [CRM] Paso 2: Creando lead con datos: {...}
DEBUG python-agent: [CRM] Respuesta de API: status=201
INFO python-agent: [CRM] Lead creado exitosamente - lead_id=123, valor=$500

# Resultado final
INFO python-agent: [CRM] Lead registrado exitosamente - lead_id=123
INFO python-agent: [CRM] ✅ Lead creado en Krayin CRM (ID: 123, Valor: $500)

# En caso de error
ERROR python-agent: [CRM] Error al crear lead: status=400, error={...}
ERROR python-agent: [CRM] Fallo al registrar lead: No se pudo crear la persona
ERROR python-agent: [CRM] Error al registrar lead: Connection timeout
```

### Ejemplo de Logs

```
2026-01-20 00:50:06 INFO python-agent: Received webhook payload: {"event":"messages.upsert"...
2026-01-20 00:50:06 INFO python-agent: Processing message from 5491131376731@s.whatsapp.net: Prueba final
2026-01-20 00:50:06 DEBUG python-agent: get_memory called for user_id=5491131376731@s.whatsapp.net
2026-01-20 00:50:07 DEBUG python-agent: Tried sendText with candidate=prueba-py-agent status=201
2026-01-20 00:50:07 INFO httpx: HTTP Request: POST https://evoapi.sisnova.com.ar/... "HTTP/1.1 201 Created"
```

## Ejecución en Producción

### Usando el Script de Gestión (Recomendado)

Se incluye un script `agent-manager.sh` para gestionar el agente fácilmente:

```bash
# Ver ayuda
./agent-manager.sh help

# Iniciar el agente
./agent-manager.sh start

# Ver estado
./agent-manager.sh status

# Reiniciar el agente
./agent-manager.sh restart

# Detener el agente
./agent-manager.sh stop

# Ver logs en tiempo real
./agent-manager.sh logs
```

**Características del script**:
- ✅ Verifica que el agente esté corriendo
- ✅ Health check automático
- ✅ Muestra uso de memoria
- ✅ Detención graceful con fallback a forzado
- ✅ Logs en tiempo real

### Usando systemd (Linux)

```bash
# Copiar archivo de servicio
sudo cp chatwoot.service /etc/systemd/system/python-agent.service

# Editar ruta del script
sudo nano /etc/systemd/system/python-agent.service

# Habilitar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable python-agent
sudo systemctl start python-agent

# Ver logs
sudo journalctl -u python-agent -f
```

### Usando PM2 (Node.js process manager)

```bash
pm2 start "./venv/bin/python agent.py" --name python-agent
pm2 save
pm2 startup
```

### Usando nohup (manual)

```bash
# Iniciar
nohup ./venv/bin/python agent.py > agent.log 2>&1 &
echo $! > agent.pid

# Detener
kill $(cat agent.pid)

# Ver logs
tail -f agent.log
```

**⚠️ Recomendación**: Usa `agent-manager.sh` en lugar de nohup manual.

### Verificar Estado

```bash
# Usando el script de gestión
./agent-manager.sh status

# O manualmente
# Health check
curl http://localhost:5000/health

# Ver usuarios en memoria
curl http://localhost:5000/memory

# Verificar proceso
ps aux | grep agent.py
ss -ltnp | grep ':5000'
```

## Limitaciones Conocidas

### Memoria

- ❌ **No persistente**: Se pierde al reiniciar
- ✅ **Con límite**: Máximo 50 mensajes por conversación (ventana deslizante automática)
- ❌ **Sin expiración**: Conversaciones en RAM nunca se limpian automáticamente (solo por reinicio)
- ✅ **Uso controlado**: ~12 KB por usuario activo (con 50 mensajes)
- ✅ **Flag de estado**: Tracking de `booking_sent` para finalización de conversaciones

### Sistema de Reservas

- ✅ **Simplificado**: Solo envía link a página de reservas pre-configurada
- ✅ **Sin autenticación**: No requiere credenciales de Google Calendar
- ✅ **Finalización inteligente**: No responde a mensajes genéricos después de enviar link
- ⚠️ **Depende de configuración externa**: Requiere crear página de reservas en Google Calendar manualmente

### Krayin CRM

- ✅ **Registro automático**: Crea leads cuando usuario reserva cita
- ✅ **Configurable**: Se puede activar/desactivar con `CRM_AUTO_REGISTER`
- ✅ **Información completa**: Guarda nombre, teléfono, empresa, valor estimado
- ✅ **Logging detallado**: Prefijo [CRM] en todos los logs
- ⚠️ **Requiere configuración**: API URL y token necesarios
- ❌ **Sin persistencia**: Información de leads se pierde al reiniciar

### LLM

- ✅ **HuggingFace**: Implementado con `Qwen/Qwen2.5-7B-Instruct` usando `chat_completion` API (por defecto)
- ✅ **Anthropic**: Disponible con Claude
- ✅ **OpenAI**: Disponible con GPT-4
- ✅ **Google Gemini**: Disponible con gemini-flash
- ✅ **Context window**: Límite de 50 mensajes previene exceder ventana del modelo
- ❌ **Sin streaming**: Respuestas completas (no parciales)

**Proveedores disponibles**:

| Proveedor | Modelo | Estado | Configuración |
|-----------|--------|--------|--------------|
| **HuggingFace** | Qwen/Qwen2.5-7B-Instruct | ✅ Por Defecto | `LLM_PROVIDER=huggingface` + `HF_MODEL=Qwen/Qwen2.5-7B-Instruct` |
| **Anthropic** | claude-sonnet-4 | ✅ Disponible | `LLM_PROVIDER=anthropic` |
| **OpenAI** | gpt-4 | ✅ Disponible | `LLM_PROVIDER=openai` |
| **Gemini** | gemini-flash | ✅ Disponible | `LLM_PROVIDER=gemini` |

### Logging

- ✅ **Rotación automática**: Máximo 50 MB total (10 MB × 5 archivos)
- ✅ **Protección de disco**: No crece indefinidamente
- ❌ **Sin compresión**: Archivos rotan pero no se comprimen (.gz)

### Escalabilidad

- ❌ **Proceso único**: Sin clustering ni balanceo de carga
- ❌ **Estado en memoria**: No puede escalar horizontalmente sin compartir estado
- ⚠️ **Bloqueo**: Procesamiento síncrono del LLM puede causar latencia

## Mejoras Recomendadas

### Completadas ✅

1. ✅ **Implementar ventana deslizante de memoria** (COMPLETADO):
   - Implementado límite de 50 mensajes por conversación
   - Truncado automático después de cada interacción
   - Configurable vía variable de entorno `MAX_MESSAGES`

2. ✅ **Sistema de reservas simplificado** (COMPLETADO):
   - Link directo a página de reservas de Google Calendar
   - Sin necesidad de autenticación OAuth
   - Una sola herramienta: `enviar_link_reserva`

3. ✅ **Finalización inteligente de conversaciones** (COMPLETADO):
   - Detecta mensajes genéricos después de enviar link
   - No responde a "gracias", "ok", "hola" post-reserva
   - Reinicia conversación si hay pregunta real

4. ✅ **Rotación de archivos de log** (COMPLETADO):
   - RotatingFileHandler con límite de 10 MB por archivo
   - 5 archivos de respaldo (máximo 50 MB total)
   - Protección contra llenado de disco

### Alta Prioridad

5. **Persistencia en Redis/PostgreSQL**:
   - Guardar conversaciones en base de datos
   - Cargar últimos N mensajes al procesar
   - Archivar conversaciones antiguas
   - Mantener flag `booking_sent` entre reinicios

6. **Expiración automática**:
   ```python
   # Limpiar conversaciones inactivas > 24h
   cleanup_inactive_conversations(max_age_hours=24)
   ```

7. **Compresión de logs antiguos**:
   - Usar `gzip` para comprimir archivos `.log.1`, `.log.2`, etc.
   - Reducir espacio en disco aún más

### Prioridad Media

8. **Métricas y monitoreo**: Prometheus + Grafana
9. **Rate limiting**: Limitar mensajes por usuario/minuto
10. **Caché de respuestas**: Redis para preguntas frecuentes
11. **Queue system**: RabbitMQ/Celery para procesamiento asíncrono

### Prioridad Baja

12. **Multi-tenancy**: Soporte para múltiples instancias de WhatsApp
13. **UI Admin**: Panel web para gestión y monitoreo
14. **Testing**: Suite de tests unitarios e integración

## Troubleshooting

### El agente no responde mensajes

**Síntoma**: El proceso está corriendo pero no responde a mensajes de WhatsApp

**Causas comunes**:

1. **Conversación finalizada después de reserva**:
   - **Causa**: El usuario envió un mensaje genérico ("hola", "gracias", "ok") después de recibir el link de reserva
   - **Comportamiento esperado**: El agente NO responde a estos mensajes para evitar spam
   - **Solución**: El usuario debe hacer una pregunta específica para reiniciar la conversación
   - **Verificar logs**: 
     ```bash
     grep "Conversación finalizada" agent_verbose.log
     grep "Mensaje genérico ignorado" agent_verbose.log
     ```

2. **Error en el LLM**:
   - Verificar logs: `tail -f agent_verbose.log`
   - Buscar errores de API key o límites de rate
   - Probar con otro proveedor: cambiar `LLM_PROVIDER` en `.env`

3. **Webhook no configurado**:
   - Verificar webhook en Evolution API
   - Probar health endpoint: `curl http://localhost:5000/health`

4. **Proceso no está corriendo**:
   - Verificar: `./agent-manager.sh status`
   - Reiniciar: `./agent-manager.sh restart`

### Mensajes no deseados después de enviar link de reserva

**Síntoma**: El agente sigue respondiendo después de enviar el link de calendario

**Causa**: El sistema de finalización puede no estar detectando correctamente los mensajes genéricos

**Verificación**:
```bash
# Ver qué mensajes se están procesando
grep "Processing message" agent_verbose.log | tail -20

# Ver si se marcó como finalizada
grep "booking_sent" agent_verbose.log | tail -10

# Ver detección de mensajes genéricos
grep "es_mensaje_generico" agent_verbose.log | tail -10
```

**Solución**:
1. Verificar que el código tiene la función `es_mensaje_generico()` implementada
2. Agregar más palabras a la lista de `palabras_genericas` si es necesario
3. Revisar logs para ver qué tipo de mensaje se está enviando

### Conversación no se reinicia después de hacer una pregunta

**Síntoma**: El agente no responde a una pregunta real después de finalizar la conversación

**Causa**: La pregunta puede ser detectada como mensaje genérico

**Solución**:
1. Asegurarse de que la pregunta tiene un "?" 
2. O que tiene más de 20 caracteres
3. Revisar la función `es_mensaje_generico()` para ajustar la lógica

### Logs crecen demasiado rápido

**Síntoma**: Los archivos de log rotan muy seguido (ej: cada hora)

**Causa**: Nivel DEBUG con muchas peticiones genera mucha información

**Soluciones**:

1. **Aumentar tamaño de archivos**:
   ```python
   # En agent.py, cambiar:
   maxBytes=10*1024*1024  # De 10 MB
   # A:
   maxBytes=50*1024*1024  # 50 MB
   ```

2. **Reducir nivel de logging**:
   ```python
   # Cambiar de DEBUG a INFO
   logging.basicConfig(level=logging.INFO, ...)
   ```

3. **Aumentar número de respaldos**:
   ```python
   backupCount=10  # Mantener 10 archivos en vez de 5
   ```

### Errores de autenticación (HTTP 401)

- Verificar `EVOLUTION_API_KEY` en `.env`
- Confirmar que la API key es válida en Evolution API

### Mensajes no se guardan en memoria

- Verificar que `fromMe=false` en el webhook
- Revisar logs para confirmar que `get_memory` fue llamado
- Consultar `/memory` endpoint

### Alto uso de RAM

- Verificar cantidad de usuarios: `curl http://localhost:5000/memory | jq 'length'`
- Verificar límite configurado: `echo $MAX_MESSAGES` 
- Reiniciar agente para limpiar memoria: `./agent-manager.sh restart`

### Link de reserva no funciona

**Síntoma**: El usuario hace clic en el link pero aparece error "Page not found"

**Causa**: URL de reserva incorrecta o página de reservas no creada

**Solución**:
1. Verificar que `GOOGLE_BOOKING_URL` en `.env` es correcto
2. Probar el link manualmente en un navegador
3. Crear una nueva página de reservas en Google Calendar si es necesario
4. Asegurarse de que la página está publicada (no en borrador)

### Errores de integración con Krayin CRM

**Síntoma**: Logs muestran errores al crear leads en CRM

**Causas comunes**:

1. **Token inválido o expirado**:
   ```
   [CRM] Error al crear lead: status=401
   ```
   - Verificar `KRAYIN_API_TOKEN` en `.env`
   - Generar nuevo token en Krayin

2. **IDs de configuración incorrectos**:
   ```
   [CRM] Error al crear lead: status=400
   ```
   - Verificar `KRAYIN_PIPELINE_ID`, `KRAYIN_STAGE_ID`, etc.
   - Obtener IDs correctos desde panel de Krayin

3. **No se puede crear persona**:
   ```
   [CRM] No se pudo crear la persona
   ```
   - Verificar formato de teléfono
   - Revisar logs detallados: `grep "\[CRM\]" agent_verbose.log`

4. **CRM deshabilitado**:
   - Verificar: `echo $CRM_AUTO_REGISTER` → debe ser "true"
   - Verificar que `KRAYIN_API_URL` y `KRAYIN_API_TOKEN` estén configurados

**Logs útiles**:
```bash
# Ver todos los logs de CRM
grep "\[CRM\]" agent_verbose.log | tail -50

# Ver solo errores de CRM
grep "\[CRM\].*ERROR" agent_verbose.log

# Ver leads creados exitosamente
grep "Lead creado exitosamente" agent_verbose.log
```

## Licencia

Este proyecto es de uso interno. Todos los derechos reservados.

## Contacto y Soporte

Para preguntas o soporte, contactar al equipo de desarrollo interno.

---

**Versión**: 2.0.0  
**Última actualización**: 2026-01-21  
**Autor**: Sisnova Tech Team

### Changelog

#### v2.0.0 (2026-01-21)
- ✅ Sistema de reservas simplificado con link directo a Google Calendar
- ✅ Finalización inteligente de conversaciones post-reserva
- ✅ Rotación automática de logs (50 MB máximo)
- ✅ Detección de mensajes genéricos para evitar spam
- ✅ Logging mejorado con prefijos [BOOKING] y [CRM]
- ✅ Script de gestión agent-manager.sh
- ✅ Integración con Krayin CRM para registro automático de leads
- ✅ Soporte para mensajes con botones/links en Evolution API

#### v1.0.0 (2026-01-20)
- ✅ Versión inicial con integración WhatsApp
- ✅ Soporte multi-LLM (HuggingFace, Anthropic, OpenAI, Gemini)
- ✅ Gestión de memoria con límite de 50 mensajes
- ✅ Integración Evolution API

##### Mejoras futuras planificadas
- Concurrencia y escalabilidad

Opción                | Complejidad | Mensajes/min | Usuarios simultáneos | Setup
Flask básico (actual) | Baja        | 6-20         |   1-3                | Listo en 10 min
Flask + Threading     | Baja        | 60-120       |    10-20             | 15 min
Flask + Celery + Redis| Media       | 300-600      |    50-100            | 30 min
FastAPI + AsyncIO     | Media       | 200-400      |    30-60             | 20 min
FastAPI + Celery      | Alta        | 600-1200     |    100-500           | 1 hora

