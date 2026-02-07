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

## 3. Funcionalidades Clave

A) Procesamiento Asíncrono ("Fire and Forget")
Para evitar timeouts de WhatsApp y soportar múltiples usuarios simultáneos:

- El Webhook (/webhook) recibe el mensaje y responde 200 OK en milisegundos.

- La tarea de procesamiento se delega inmediatamente a un ThreadPoolExecutor.

- Esto libera al servidor web para seguir recibiendo mensajes mientras la IA "piensa" en hilos separados.

B) Memoria y Contexto (Multi-tenant)

- Persistencia: Cada conversación se guarda en PostgreSQL bajo un thread_id único formado por business_id:telefono_usuario.

- Aislamiento: El sistema soporta múltiples negocios (cliente1, cliente2) con configuraciones, prompts y herramientas totalmente independientes, cargadas dinámicamente desde config_negocios.json.

C) Human-in-the-Loop (HITL) - Protocolo de Derivación

Sistema robusto para pasar del Bot al Humano y viceversa:

1. Activación: El Agente detecta frustración o solicitud compleja y ejecuta la tool solicitar_atencion_humana.

2. Notificación: Se envía alerta al dueño (WhatsApp) y aviso al cliente.

3. Modo Silencio: La tool retorna la señal "DERIVACION_EXITOSA_SILENCIO". El sistema intercepta esto y bloquea cualquier respuesta automática del LLM, dejando el chat "mudo".

4. Reactivación: El humano, al terminar, dispara el endpoint /reactivar_bot. Esto inyecta un mensaje de sistema (BOT_REACTIVADO) que "despierta" al agente.

D) Herramientas "Non-Blocking"

Las operaciones lentas (escribir en Google Sheets o CRM) no detienen la conversación:

- La herramienta retorna una confirmación inmediata al usuario (ej: "Agendando...").

- Se dispara un hilo secundario (daemon) que realiza la conexión a las APIs externas en segundo plano sin bloquear el flujo del chat.

E) Procesamiento de Audio

- Soporte nativo para notas de voz.

- Flujo: Descarga de audio -> Conversión (ffmpeg) -> Transcripción (OpenAI Whisper) -> Inyección como texto en el Agente.

## 4. Flujos de Datos (Workflows)

Flujo 1: Recepción de Mensaje

1. Evolution API envía POST /webhook.

2. Flask valida el payload, extrae user_id y verifica reglas de DDoS.

3. ThreadPool asigna un worker libre.

4. Flask retorna 200 OK inmediatamente.

Flujo 2: Razonamiento del Agente (Worker)

1. LangGraph recupera el estado previo de PostgreSQL usando el thread_id.

2. Carga el system_prompt específico del negocio desde JSON.

3. LLM razona sobre el historial y decide: ¿Responder directo o usar Tool?

    - Si es Tool: Ejecuta función Python -> Obtiene resultado -> Vuelve a pensar.

    - Si es Respuesta: Genera texto final.

4. Filtro de Salida: Verifica si hay señal de "Silencio" (derivación).

5. Envío: Llama a Evolution API para enviar la respuesta final al usuario.

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
  "cliente_ejemplo": {
    "nombre": "Pizzería Demo",
    "admin_phone": "54911xxxxxxxx",
    "system_prompt": [
      "Eres un asistente de pizzería.",
      "Tus objetivos son vender y tomar pedidos."
    ],
    "tools_habilitadas": ["ver_menu", "solicitar_atencion_humana"]
  }
}
```

Endpoints de Gestión:

1.  POST /webhook: Recepción de mensajes (Evolution API).

2.  POST /reactivar_bot: Despierta al bot tras intervención humana.
```bash
curl -X POST http://localhost:5000/reactivar_bot \
  -H "Content-Type: application/json" \
  -d '{"user_id": "5491131376731@s.whatsapp.net", "business_id": "cliente2"}'
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

## 7. Próximos Pasos (Roadmap)
Panel de Control (Frontend): Crear una interfaz visual para ver conversaciones, logs y pausar/activar bots manualmente.

Métricas y Analytics: Explotar los logs de consumo de tokens para facturación por cliente y análisis de sentimiento.

RAG (Retrieval Augmented Generation): Integrar una base de conocimientos vectorial (PDFs/Web) para respuestas más específicas sobre productos sin ensuciar el prompt del sistema.

Broadcast: Funcionalidad para envíos masivos proactivos a listas de leads capturados.