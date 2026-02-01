# Readme SAAS Siagent

## Funcionalidades:

- Integración con Flask para multi-hilo
- Multi-tenancy
- Conexión en Pool a Postgres.
- Fallback de LLM
- Compilación con interrupción (HITL).

## Caracteres Unicode
⚠️  ▲  🔺 
🟢 🟡 🔴
🟩
## Detalle de Funcionalidades

### Integración con Flask para multi-hilo

La app está diseñada para integrarse con Flask. Separa la lógica del Pool de Conexiones (que vive todo el tiempo) de la Ejecución del Agente (que ocurre en cada petición web), e incluye una herramienta de ejecución.

### Conexión en Pool a Postgres

La app utiliza el ConnectionPool de Postgres para manejar la concurrencia de llamadas correctamente. LangGraph necesita una conexión activa para guardar memoria, y el Pool te da conexiones bajo demanda.
La inicialización de tablas solo se ejecuta una vez al arrancar usando una conexión temporal del pool para verificar que las tablas existan.
La configuración por defecto es de hasta 20 usuarios simultáneos procesando

Ventajas de este enfoque
- Escalable: pool = ConnectionPool(...) maneja múltiples usuarios a la vez sin saturar la base de datos.
- Robusto: Si la conexión se cae, el pool intenta reconectar automáticamente.

Configuraciones:
- max_lifetime=600: Obliga al pool a tirar a la basura cualquier conexión que tenga más de 10 minutos de vida. Esto previene errores silenciosos que ocurren cuando una conexión vive "demasiado" (días).

- max_idle=300: Si una conexión no se usa en 5 minutos, se cierra. La próxima vez que alguien pida una, el pool creará una nueva y fresca.

- keepalives: Le dice al sistema operativo que envíe pequeños "pings" a la base de datos cada 30 segundos. Esto evita que los firewalls corten la conexión creyendo que está abandonada.

### Multi-tenancy

Para manejar múltiples negocios (Multi-tenancy) en una sola aplicación de Agentes, Se basa en tres pilares fundamentales: Identificación Compuesta, Configuración Dinámica y Aislamiento de Contexto.

Es como si la aplicación funcionara como un Hotel:

La App es el edificio.
- El Business ID es el número de piso (cada empresa tiene su estilo).
- El User ID es el número de habitación (cada cliente tiene su historia).
- El Thread ID es la llave única que combina ambos (piso_habitacion).

La Estrategia de IDs (La Clave) para no mezclar por ejemplo el "cliente_1" de la Pizzería con el "cliente_2" de la Zapatería.

thread_id = f"{business_id}:{user_id}"

### Fallback de LLM

Las APIs fallan, tienen límites de velocidad (Rate Limits) o entran en mantenimiento. El agente tiene la capacidad de cambiar el LLM automáticamente.

En el ecosistema LangChain/LangGraph, existe una función nativa y elegante llamada .with_fallbacks().

Estrategia: "El Doble Motor"
El truco es configurar ambos modelos por separado, vincular las herramientas a ambos, y luego unirlos en un solo objeto ejecutable.

### Human-in-the-Loop (HITL) / "Modo Copiloto"

¿Qué es? En lugar de que el agente haga todo automático siempre, permites que para acciones sensibles (como "Autorizar devolución", "Agendar cita confirmada" o "Dar descuento"), el agente se detenga, le avise a un humano (el dueño del negocio), y espere su aprobación (un click) para continuar.

¿Por qué es novedoso y útil?

Elimina el miedo: El mayor freno de venta de IA a empresas es: "¿Y si el bot se vuelve loco y regala mi inventario?". Con esto, les garantizas control.

Es nativo de LangGraph: A diferencia de LangChain clásico, LangGraph fue diseñado específicamente para esto (capacidad de pausar un hilo y reanudarlo). Muy pocos competidores lo implementan porque es técnicamente complejo si no usas grafos.

- Detalle de llamadas de ejemplo con y sin uso de herramientas:

```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hola, quienes son?","user_id":"user123","business_id":"nike_store"}'

  {"response":"Soy un experto en calzado deportivo y vendedor de zapatillas Nike. Estoy aqu\u00ed para ayudarte a encontrar el par perfecto de zapatillas Nike que se adapte a tus necesidades y preferencias. \u00bfQu\u00e9 tipo de zapatillas Nike te gustar\u00eda conocer m\u00e1s sobre?","status":"COMPLETADO"}

  curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"No, gracias ,  adios!","user_id":"user123","business_id":"nike_store"}'

"{"message":"El asistente solicita permiso para ejecutar: consultar_inventario","status":"REQUIERE_APROBACION","tool_args":{"producto":"zapatillas Nike disponibles"},"tool_name":"consultar_inventario"}"


curl -X POST http://localhost:5000/aprobar \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"nike_store:user123","decision":"approve"}'

curl -X POST http://localhost:5000/aprobar \
  -H "Content-Type: application/json" \
  -d '{"business_id":"cliente2","user_id":"5491131376731@s.whatsapp.net","decision":"approve"}'

{"response":"Tenemos varios modelos de zapatillas Nike disponibles, incluyendo Air Max, Air Force, Jordan, y m\u00e1s. \u00bfTe gustar\u00eda saber m\u00e1s sobre alguno de estos modelos en particular?","status":"ACCION_EJECUTADA"}

curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"No, gracias ,  adios!","user_id":"user123","business_id":"nike_store"}'

{"response":"\u00a1Hasta luego! Que tengas un buen d\u00eda y si necesitas algo m\u00e1s, no dudes en regresar. \u00a1Que te vaya bien!","status":"COMPLETADO"}

curl -X POST http://localhost:5000/aprobar \
  -H "Content-Type: application/json" \
  -d '{"business_id":"cliente2","user_id":"5491131376731@s.whatsapp.net","decision":"reject"}'
  ```

## Borrado de memoria BD Postgres

LangGraph guarda datos en 3 tablas principales: checkpoints, checkpoint_blobs y checkpoint_writes. Debemos limpiar las tres para ese usuario.

```bash
curl -X DELETE http://localhost:5000/borrar_memoria \
  -H "Content-Type: application/json" \
  -d '{"user_id":"5491131376731@s.whatsapp.net", "business_id":"cliente2"}'
```

Borrado Total (Reset de Fábrica - Cuidado ⚠️)
Esto borrará el historial de todos los clientes de todos los negocios. Tu bot arrancará como si lo hubieras instalado hoy.

SQL
TRUNCATE TABLE checkpoints, checkpoint_blobs, checkpoint_writes;

¿Qué pasa después de borrar?
La próxima vez que ese usuario envíe un mensaje, LangGraph buscará su thread_id en la base de datos.
Como no encontrará nada, iniciará un nuevo estado vacío.
Se ejecutará el System Prompt original de nuevo.
El bot no recordará nada de lo anterior (ni el nombre, ni pedidos previos).

### Time Out de aprobaciones

Como la aplicación es pasiva (solo despierta cuando recibe una petición HTTP), el concepto de "liberarse sola" funciona así:

Al intentar Aprobar: Si el usuario hace clic en "Aprobar" después de X minutos, el sistema le dice "La solicitud caducó" y cancela la acción.

Al volver a Hablar: Si el usuario ignora la aprobación y escribe "Hola" 2 horas después, el sistema detecta que la acción pendiente es vieja, la cancela automáticamente y procesa el "Hola" como nuevo.

¿Qué logra esto?
Seguridad: Nadie puede aprobar un reembolso de hace 3 días.

Fluidez: Si el cliente se arrepiente, deja de hablar y vuelve al día siguiente preguntando "¿Tienen stock?", el bot no le dirá "¡Espera! Aún no aprobé el reembolso anterior". Simplemente olvidará lo anterior y responderá sobre el stock.

# Tiempo máximo de espera (ej: 5 minutos)
TIEMPO_EXPIRACION_MINUTOS = 5