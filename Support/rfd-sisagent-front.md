# Requerimientos Funcionales: Panel de Control Sisagent

Descripción: Este documento detalla los requerimientos funcionales para el desarrollo del panel de control de Sisagent, una plataforma de gestión de bots conversacionales para negocios. El panel permitirá a los clientes administrar sus bots y al Super Admin gestionar la plataforma global.

## 1. Arquitectura de la Solución (Frontend)
Para que este panel funcione, el backend debe exponer una API REST. A continuación se describen los endpoints necesarios:

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/tools` | Lista todas las herramientas disponibles |
| `GET` | `/api/config/clientes` | Lista todos los clientes |
| `GET` | `/api/config/clientes/<id>` | Obtiene un cliente específico |
| `POST` | `/api/config/clientes` | Crea un nuevo cliente |
| `PUT` | `/api/config/clientes/<id>` | Actualiza cliente (completo) |
| `PATCH` | `/api/config/clientes/<id>` | Actualiza cliente (parcial) |
| `DELETE` | `/api/config/clientes/<id>` | Elimina un cliente |

Todas las respuestas siguen un formato consistente:
```json
{
  "status": "success",
  "message": "Descripción de la operación",
  "data": { ... },
  "updated_fields": [ ... ]  // Solo en PATCH
}
```

## 2. Roles de Usuario

El sistema debe diferenciar claramente dos niveles de acceso:

- Cliente (Dueño de Negocio): Acceso restringido exclusivamente a su business_id.

- Super Admin: Acceso global a todos los negocios, métricas agregadas y configuraciones del sistema.

## 3. Vista de Cliente (El "Dashboard de Negocio")
Esta vista debe ser limpia, intuitiva y a prueba de errores.

### Módulo A: Estado y Control Principal

#### RF-C01 Interruptor Maestro (Kill Switch):

- Un botón tipo "Toggle" grande que permita Activar/Pausar el bot instantáneamente.

- Lógica: Si está pausado, el webhook responde 200 OK pero no procesa el mensaje (o envía un mensaje de "Mantenimiento").

#### RF-C02 Botón de Pánico (Solicitar Humano):

- Botón para forzar el modo "Silencio" manualmente desde el panel sin esperar a que el usuario lo pida.

#### RF-C03 Reactivación Manual:

Botón para "Despertar" al bot (equivalente al enlace mágico o endpoint /reactivar_bot).

### Módulo E: Ajuste del Agente (Horarios, mensajes fijos, etc.)

#### RF-C09 Configuración de Fuera de Horario:

- Definir rango horario de atención del bot.

- Definir un checkbox para activar/desactivar el modo fuera de horario.

- Definir mensaje personalizado para cuando el bot está "durmiendo" o en mantenimiento.

- Definir un checkbox para activar/desactivar el modo Silencio (Kill Switch)


### Módulo F: Broadcast de Mensajes

#### RF-C11 Envío de Anuncios:

- Área para escribir un mensaje que se enviará a todos los clientes conectados en ese momento (ej: "Estamos actualizando nuestros sistemas, disculpen las molestias").

- Botón para enviar el mensaje a todos los clientes conectados (usando WebSocket o un endpoint específico).

- Mensaje de confirmación: "¿Enviar este mensaje a todos los clientes conectados? [Confirmar] [Cancelar]"

- Lista de números telefónicos disponibles para enviar el mensaje de forma individual (usando el endpoint de envío de mensajes).


## 4. Vista de Super Admin (Tu "Torre de Control")
El Super Admin tiene acceso a un panel más completo que le permite gestionar todos los aspectos de la plataforma.
Puede ver y gestionar todos los negocios, métricas globales, logs y configuraciones del sistema.

### Módulo A: Gestión de Negocios

## RF-C01 CRUD Completo de Negocios:
Crear, leer, actualizar y eliminar negocios (clientes) desde el panel.

1. Listar todos los clientes
curl http://localhost:5000/api/config/clientes

2. Obtener cliente específico
curl http://localhost:5000/api/config/clientes/cliente2

3. Crear nuevo cliente
curl -X POST http://localhost:5000/api/config/clientes \
  -H "Content-Type: application/json" \
  -d '{
    "business_id": "cliente99",
    "nombre": "Nueva Tienda",
    "ttl_sesion_minutos": 60,
    "admin_phone": "5491134567890"
  }'

4. Actualizar parcialmente
curl -X PATCH http://localhost:5000/api/config/clientes/cliente99 \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Nueva Tienda Actualizada",
    "ttl_sesion_minutos": 90
  }'

5. Eliminar cliente
curl -X DELETE http://localhost:5000/api/config/clientes/cliente99


### Módulo B: Configuración del Cerebro (IA)

#### RF-C04 Edición de Prompt del Sistema:

Un área de texto para editar el system_prompt de cada negocio.

#### RF-C05 Configuración de Sesión (TTL):

Input numérico para definir ttl_sesion_minutos (tiempo tras el cual el bot olvida la charla) por cada negocio.

#### RF-C10 Habilitar transcripción de audio:

- Checkbox para activar/desactivar la función de transcripción de audio a texto.

### Módulo C: Gestión de Herramientas (Tools)

#### RF-C06 Selector de Herramientas:

Lista para asociar herramientas a un negocio:

- Las herramientas disponibles se podrán consultar desde el backend (GET /api/tools) y pueden incluir: RAG, HITL, Calendar, etc.

- Cada herramienta tendrá un checkbox para activarla/desactivarla para ese negocio.

```bash

```

[ ] Búsqueda en Base de Conocimientos (RAG)

[ ] Derivación a Humano (HITL)

[ ] Consultar Menú/Precios (Excel)

[ ] Agendar Citas (Calendar)

### Módulo D: Base de Conocimientos (RAG)

#### RF-C07 Subida de Archivos:

- Área de "Drag & Drop" para subir archivos PDF, CSV o TXT.

- Acción: Al subir, el backend debe ejecutar automáticamente el script de ingesta/vectorización.

#### RF-C08 Listado de Documentos:

Ver qué archivos están actualmente "enseñados" al bot y poder borrarlos.

### Módulo F: Métricas Globales (Analytics Dashboard)

#### RF-A01 KPIs Agregados:

- Total de mensajes procesados hoy (suma de todos los clientes).

- Costo Total USD acumulado (mes en curso).

- Tasa de Error Global (fallos de API).

#### RF-A02 Tabla de Negocios:

- Listado de todos los clientes (business_id, Nombre, Estado, Plan).

- Columnas de métricas rápidas: "Gasto del mes", "Última actividad".

- Acciones: "Editar Config", "Ver Logs", "Suspender Servicio".

- Activar funcionalidades: Trasncripción de audio, fuera de horario, broadcast

### Módulo G: Gestión de Facturación (Unit Economics)

#### RF-A03 Reporte de Costos por Cliente:

- Visualización exacta de cuántos tokens consumió cada cliente para poder facturarles.

- Desglose: Costo Modelo Principal vs. Costo Backup.

- Asignar planes de suscripción (Free, Pro, Enterprise) con límites y precios predefinidos.

### Módulo H: Auditoría y Logs

#### RF-A04 Visor de Logs en Vivo:

Una consola web que muestre los logs de analytics_events filtrables por business_id para depurar errores sin entrar al servidor por SSH.

## 5. Mockup de Datos (Estructura JSON propuesta para API)
Para que el frontend funcione, el backend debería devolver un JSON así al hacer GET /api/config/{business_id}:

```JSON
  "cliente1": {
    "nombre": "Soporte IT Start",
    "ttl_sesion_minutos": 60,
    "admin_phone": "5491131312345",
    "audio_transcripcion": false,
    "fuera_de_servicio": {
      "activo": false,
      "horario_inicio": "09:00",
      "horario_fin": "18:00",
      "dias_laborales": [1, 2, 3, 4, 5, 6],
      "zona_horaria": "America/Argentina/Buenos_Aires",
      "mensaje": []
    },
    "system_prompt": ["Eres un experto en soporte IT de ATMs",
    "Tu objetivo es ayudar a resolver problemas técnicos."],
    "mensaje_HITL": "",
    "mensaje_usuario_1": [],
    "tools_habilitadas": ["consultar_base_conocimiento"]
  },
  "cliente2": ....
```

## 6. Stack Tecnológico Sugerido para Frontend
.