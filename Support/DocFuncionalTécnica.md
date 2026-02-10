# 📘 Documentación Funcional y Técnica: Sisagent by Sisnova Tech

**Versión:** 1.0  
**Fecha:** 07/02/2026  
**Estado:** Producción / Beta

---

## 1. Visión General del Proyecto
El sistema es un **Agente Conversacional Orquestado** diseñado para automatizar la atención al cliente, ventas y soporte técnico de Pymes a través de WhatsApp.

A diferencia de un chatbot tradicional (árbol de decisión estático), este sistema utiliza **Inteligencia Artificial Generativa (LLM)** controlada por un grafo de estados (**LangGraph**). Esto permite conversaciones naturales, memoria contextual, uso de herramientas externas (CRM, Sheets, Calendar) y una gestión fluida de la intervención humana (*Human-in-the-Loop*).

---

## 2. Arquitectura del Sistema

El sistema sigue una arquitectura **Event-Driven** (basada en eventos) y de microservicios lógicos, optimizada para alta concurrencia y tolerancia a fallos.

### Diagrama de Flujo de Alto Nivel

```mermaid
graph TD
    User((Usuario WhatsApp)) -->|Mensaje| EvolutionAPI[Evolution API v2]
    EvolutionAPI -->|Webhook POST| FlaskApp[Servidor Flask]
    FlaskApp -->|200 OK (Ack)| EvolutionAPI
    FlaskApp -->|ThreadPool| Worker[Worker Asíncrono]
    
    subgraph "Núcleo de IA (Agente)"
        Worker -->|Carga Estado| DB[(PostgreSQL)]
        Worker -->|Procesa| LangGraph[LangGraph Engine]
        LangGraph -->|Infiere| LLM[Google Gemini / GPT-4o]
        LangGraph -->|Ejecuta| Tools[Herramientas Python]
    end
    
    subgraph "Integraciones"
        Tools -->|API| GoogleSheets
        Tools -->|API| KrayinCRM
        Tools -->|API| GoogleCalendar
    end
    
    LangGraph -->|Respuesta| EvolutionAPI
    EvolutionAPI -->|WhatsApp| User
```

### Componentes Principales

1. Canal de Entrada (WhatsApp): Gestionado por Evolution API, que convierte los mensajes de WhatsApp en Webhooks HTTP y permite el envío programático de respuestas.

2. Servidor Web (Flask - app.py): El punto de entrada principal. Recibe los webhooks, valida la seguridad (DDoS protection) y distribuye la carga.

3. Motor de IA (LangGraph - agente.py): El cerebro del sistema. Gestiona el estado de la conversación, la memoria a corto/largo plazo y la toma de decisiones.

4. Gestor de Herramientas (crm_tools.py): Módulos Python que conectan al agente con el mundo real.

5. Base de Datos (PostgreSQL): Almacena el historial de chat y los "Checkpoints" del grafo para persistencia entre sesiones.

## 3. Funcionalidades y herramientas Clave

### A) Procesamiento Asíncrono ("Fire and Forget")
Para evitar timeouts de WhatsApp y soportar múltiples usuarios simultáneos:

- El Webhook (/webhook) recibe el mensaje y responde 200 OK en milisegundos.

- La tarea de procesamiento se delega inmediatamente a un ThreadPoolExecutor.

- Esto libera al servidor web para seguir recibiendo mensajes mientras la IA "piensa" en hilos separados.

### B) Memoria y Contexto (Multi-tenant)

- Persistencia: Cada conversación se guarda en PostgreSQL bajo un thread_id único formado por business_id:telefono_usuario.

- Aislamiento: El sistema soporta múltiples negocios (cliente1, cliente2) con configuraciones, prompts y herramientas totalmente independientes, cargadas dinámicamente desde config_negocios.json.

### C) Human-in-the-Loop (HITL) - Herramienta de Derivación

Protocolo robusto de derivación a humanos con seguridad y fail-safes:

Activación: El Agente ejecuta la herramienta: solicitar_atencion_humana.

Modo Silencio con TTL: Se activa la señal "DERIVACION_EXITOSA_SILENCIO".

Notificación Segura (Magic Links): Se envía un enlace al dueño con un token firmado (JWT).

Reactivación: El humano hace clic en el enlace, disparando una petición GET validada que inyecta BOT_REACTIVADO.

### D) Herramientas "Non-Blocking"

Las operaciones lentas (escribir en Google Sheets o CRM) no detienen la conversación:

- La herramienta retorna una confirmación inmediata al usuario (ej: "Agendando...").

- Se dispara un hilo secundario (daemon) que realiza la conexión a las APIs externas en segundo plano sin bloquear el flujo del chat.

### E) Procesamiento de Audio

- Soporte nativo para notas de voz.

- Flujo: Descarga de audio -> Conversión (ffmpeg) -> Transcripción (OpenAI Whisper) -> Inyección como texto en el Agente.

### F) Gestión de Sesión y Olvido Automático (Lazy Expiration)

Mecanismo para limpiar el contexto tras un periodo de inactividad:

TTL Configurable: Cada negocio define su tiempo de vida de sesión (ej. 60 min).

Verificación Perezosa: Al llegar un mensaje nuevo, se calcula la antigüedad del último checkpoint.

Olvido Selectivo: Si el tiempo expiró, el sistema borra la memoria de corto plazo y el LLM inicia una nueva conversación "fresca", evitando alucinaciones con contextos antiguos.

### G) Sistema RAG (Retrieval-Augmented Generation)
Permite al agente consultar una base de conocimientos específica del negocio para respuestas más precisas sin sobrecargar el prompt del sistema.

- Embeddings: Convierten texto (tu PDF) en listas de números (vectores) que representan el significado a través del script de ingesta ingest_knowledge.py el cual crea una memoria vectorial local con ChromaDB.

- Vector Store: Base de datos ChromaDB donde guardan los vectores y sus metadatos (ej. página del PDF).

- RAG: El proceso de buscar en esa base y dárselo al LLM.

## 4. Flujos de Datos (Workflows)

### Flujo 1: Recepción de Mensaje

1. Evolution API envía POST /webhook.

2. Flask valida el payload, extrae user_id y verifica reglas de DDoS.

3. ThreadPool asigna un worker libre.

4. Flask retorna 200 OK inmediatamente.

### Flujo 2: Razonamiento del Agente (Worker)

1. LangGraph recupera el estado previo de PostgreSQL usando el thread_id.

2. Carga el system_prompt específico del negocio desde JSON.

3. Verificación de Sesión: Si expiró el TTL, se resetea el historial

4. LLM razona sobre el historial y decide: ¿Responder directo o usar Tool?

    - Si es Tool: Ejecuta función Python -> Obtiene resultado -> Vuelve a pensar.

    - Si es Respuesta: Genera texto final.

5. Registro de Métricas: Se lanza un hilo independiente para guardar tokens, latencia y costos en la DB sin bloquear la respuesta al usuario

6. Filtro de Salida: Verifica si hay señal de "Silencio" (derivación).

7. Envío: Llama a Evolution API para enviar la respuesta final al usuario.

## 5. Stack Tecnológico
Componente | Tecnología | Descripción
Backend | Python 3.10+ / Flask | Servidor API y Lógica de negocio.
IA Orchestrator | LangChain / LangGraph | Gestión de estado, grafos y herramientas.
LLM | Google Gemini 1.5 Flash / GPT-4o | Modelos de lenguaje principales y de backup.
Database | PostgreSQL + Psycopg3 | Almacenamiento de memoria conversacional (Checkpoints).
Mensajería | Evolution API v2 | Pasarela de WhatsApp.
Integraciones | Google APIs, Krayin CRM | Herramientas de negocio conectadas.
Infraestructura | Docker | Contenerización recomendada para despliegue.

## 6. Configuración y Mantenimiento
Archivo config_negocios.json
Controla el comportamiento por cliente sin tocar código. Permite definir prompts y herramientas habilitadas.

```json
{
  "cliente1": {
    "nombre": "Nike Store Palermo",
    "ttl_sesion_minutos": 60,
    "admin_phone": "54911XXXXXXXX",
    "fuera_de_servicio": {
      "activo": false,
      "horario_inicio": "22:00",
      "horario_fin": "09:00",
      "dias_laborales": [1, 2, 3, 4, 5, 6],
      "zona_horaria": "America/Argentina/Buenos_Aires",
      "mensaje": []
    },
    "system_prompt": "Eres un experto vendedor de Nike. Tu objetivo es vender zapatillas y ropa deportiva...",
    "mensaje_HITL": "",
    "mensaje_usuario_1": [],
    "tools_habilitadas": []
  }
```

## Endpoints de Gestión:

1.  POST /webhook: Recepción de mensajes (Evolution API).

2.  POST /reactivar_bot: Despierta al bot tras intervención humana.

```bash
curl -X POST http://localhost:5000/reactivar_bot \
  -H "Content-Type: application/json" \
  -d '{"user_id": "5491131376731@s.whatsapp.net", "business_id": "cliente2"}'

Reactivación segura mediante Magic Link.
http://192.168.1.220:5000/reactivar_bot_web?token=eyJhbGciOiJIUzI1NiIsInR5cCI6Ik......
```

3.  DELETE /borrar_memoria: Resetea la conversación de un usuario.

```bash
curl -X DELETE http://localhost:5000/borrar_memoria \
  -H "Content-Type: application/json" \
  -d '{"user_id":"5491131376731@s.whatsapp.net", "business_id":"cliente2"}'
```

4.  GET /admin/grafo-estados: Endpoint para visualizar el grafo de estados del agente en formato PNG.

```bash
curl -X GET http://localhost:5000/ver-grafo --output arquitectura_agente.png

http://192.168.1.220:5000/ver-grafo
```

## 7. Metricas y Analíticas

### 📊 Nuevas Métricas a implementar: 

- Latencia Pura: Tiempo de "pensamiento" del LLM descontando la red.

- Tasa de Uso de Herramientas (Tool Usage Rate):

  ¿Qué es? ¿Qué % de mensajes resultan en una reserva, una consulta de stock o una derivación humana?

  ¿Por qué? Te dice qué funcionalidad es la más valiosa para cada cliente.

- Tasa de Derivación (Handoff Rate):

  ¿Qué es? Porcentaje de conversaciones que terminan en solicitar_atencion_humana.

  ¿Por qué? Si es muy alto (>20%), tu prompt o tus tools están fallando. Si es muy bajo, quizás el bot no está detectando la frustración.

- Costo Real vs. Precio de Venta (Unit Economics):

  Calculado: (Tokens Entrada * Costo + Tokens Salida * Costo).

  Para facturar con margen de ganancia.

- Cantidad de Interacciones por Usuario: Para entender el engagement y detectar usuarios frecuentes.

- cantidad de iteracciones por cliente: Para comparar entre negocios y entender quién saca más provecho del sistema.

### Endpoint que devuelve un JSON estructurado con:

- KPIs Generales: Costo total, tokens totales, latencia promedio.

- Desglose por Modelo: Para ver cuánto usaste el modelo principal vs. el de backup.

- Análisis de Sentimiento: Conteo de positivos, negativos y neutros. (no implementado aún)

A) Consulta Básica (Últimos 30 días)

```bash
curl "http://localhost:5000/api/metrics?business_id=cliente2"
```

B) Consulta con Rango de Fechas Específico

```bash
curl "http://localhost:5000/api/metrics?business_id=cliente2&start_date=2024-02-01&end_date=2024-02-15"
```

```json
{
  "models_breakdown": [
    {
      "cost": 0.000235,
      "model": "openai/gpt-oss-20b",
      "usage_count": 3
    }
  ],
  "period": {
    "end": "2026-02-08",
    "start": "2026-01-09"
  },
  "sentiment_breakdown": {},
  "summary": {
    "avg_latency_ms": 732,
    "total_cost_usd": 0.000235,
    "total_input_tokens": 1464,
    "total_interactions": 3,
    "total_output_tokens": 416,
    "total_tokens": 1880
  }
}
```

## . Próximos Pasos (Roadmap)
Panel de Control (Frontend): Crear una interfaz visual para ver conversaciones, logs y pausar/activar bots manualmente.

Broadcast: Funcionalidad para envíos masivos proactivos a listas de leads capturados.