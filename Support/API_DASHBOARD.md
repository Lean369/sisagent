# API Dashboard — Documentación

Endpoint consolidado para monitorear la plataforma SisAgent como propietario. Devuelve en una sola llamada métricas de rendimiento, costos, seguridad y uso de todos los negocios.

---

## Endpoint

```
GET /api/dashboard
```

### Autenticación

Si la variable de entorno `ADMIN_TOKEN` está definida, todas las peticiones deben incluir el header:

```
X-Admin-Token: <valor_de_ADMIN_TOKEN>
```

Si el token es incorrecto o falta, se devuelve `401 Unauthorized`.

> Para configurar: agregar `ADMIN_TOKEN=tu_secreto` en `.env`.

---

## Parámetros de consulta (Query Params)

| Parámetro    | Tipo   | Requerido | Descripción                                              |
|--------------|--------|-----------|----------------------------------------------------------|
| `start_date` | string | No        | Inicio del período. Formato `YYYY-MM-DD`. Default: hace 30 días |
| `end_date`   | string | No        | Fin del período. Formato `YYYY-MM-DD`. Default: hoy      |
| `business_id`| string | No        | Filtrar por un negocio específico. Default: todos        |

### Ejemplos de llamada

```bash
# Dashboard global últimos 30 días
curl -H "X-Admin-Token: mysecret" \
  https://api.sisnova.org/api/dashboard

# Filtrado por negocio y rango
curl -H "X-Admin-Token: mysecret" \
  "https://api.sisnova.org/api/dashboard?business_id=cliente6&start_date=2026-06-01&end_date=2026-06-11"

# Sin autenticación (si ADMIN_TOKEN no está configurado, solo en desarrollo)
curl "http://localhost:5000/api/dashboard"

#Borrado TOTAL de la BD (solo para desarrollo, no usar en producción)
curl -X POST http://localhost:5000/admin/wipe-analytics \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -d '{"confirm":"I UNDERSTAND"}'
```

---

## Estructura de la respuesta

```jsonc
{
  "period":       { "start": "2026-05-12", "end": "2026-06-11" },
  "generated_at": "2026-06-11T21:00:00Z",
  "filters":      { "business_id": "all" },

  "kpis":        { ... },   // Sección 1 — Indicadores clave
  "performance": { ... },   // Sección 2 — Rendimiento y latencia
  "costs":       { ... },   // Sección 3 — Tokens y costos
  "security":    { ... },   // Sección 4 — Seguridad y escalaciones
  "usage":       { ... },   // Sección 5 — Uso y adopción
  "businesses":  [ ... ]    // Sección 6 — Desglose por negocio (solo si no se filtró)
}
```

---

## Sección 1 — `kpis`

Indicadores de alto nivel del período seleccionado.

| Campo                    | Tipo    | Descripción                                                  | Origen                    |
|--------------------------|---------|--------------------------------------------------------------|---------------------------|
| `total_events`           | int     | Total de interacciones registradas (LLM + tools + audio)     | `analytics_events.COUNT(*)` |
| `unique_conversations`   | int     | Hilos únicos activos (`thread_id` distintos)                 | `COUNT(DISTINCT thread_id)` |
| `active_businesses`      | int     | Negocios que generaron al menos un evento                    | `COUNT(DISTINCT business_id)` |
| `total_tokens`           | int     | Suma de tokens de entrada + salida consumidos                | `SUM(input_tokens + output_tokens)` |
| `total_cost_usd`         | float   | Costo total estimado en USD                                  | `SUM(estimated_cost)` |
| `avg_latency_ms`         | int     | Latencia promedio de respuesta del LLM en milisegundos       | `AVG(latency_ms)` |
| `fallback_rate_pct`      | float   | % de llamadas que usaron el modelo de respaldo               | `llm_fallback / total * 100` |
| `transcription_events`   | int     | Cantidad de transcripciones de audio procesadas              | `event_type = 'transcription'` |
| `image_analysis_events`  | int     | Cantidad de imágenes analizadas                              | `event_type = 'image_analysis'` |

**Uso:** mostrar como tarjetas KPI en la parte superior del dashboard.

---

## Sección 2 — `performance`

### `latency_percentiles_ms`

Distribución estadística de latencia del LLM.

| Campo | Descripción |
|-------|-------------|
| `p50` | La mitad de las respuestas tardan menos de este valor (mediana) |
| `p95` | El 95% de respuestas está por debajo (indicador de experiencia del usuario) |
| `p99` | El 99% está por debajo (detecta picos extremos) |
| `max` | Peor tiempo de respuesta registrado |

**Alerta recomendada:** si `p95 > 8000ms`, investigar modelo o carga del servidor.

**Origen:** `PERCENTILE_CONT` sobre `analytics_events.latency_ms`.

---

### `latency_by_tool`

Latencia promedio desglosada por herramienta invocada.

```jsonc
[{ "tool": "consultar_orden_tiendanube", "avg_latency_ms": 1240, "calls": 87 }]
```

**Uso:** detectar qué herramienta externa es el cuello de botella.  
**Origen:** `AVG(latency_ms) GROUP BY tool_name`.

---

### `events_per_hour`

Throughput del sistema: cantidad de eventos por hora.

```jsonc
[{ "hour": "2026-06-11T14:00:00", "events": 43 }]
```

**Uso:** gráfico de área para visualizar picos de demanda y detectar horarios críticos.  
**Origen:** `COUNT(*) GROUP BY DATE_TRUNC('hour', timestamp)`.

---

### `fallback_rate_daily`

Tasa diaria de uso del modelo de respaldo (LLM fallback).

```jsonc
[{ "date": "2026-06-10", "fallbacks": 3, "total": 120, "rate_pct": 2.5 }]
```

**Uso:** si la tasa sube sostenidamente, el modelo primario puede estar teniendo problemas (rate limits, errores de API).  
**Origen:** `event_type = 'llm_fallback'` vs total por día.

---

## Sección 3 — `costs`

### `daily`

Costo y tokens consumidos por día.

```jsonc
[{ "date": "2026-06-10", "cost_usd": 0.0341, "tokens": 45200 }]
```

**Uso:** gráfico de barras para control de presupuesto diario.

---

### `monthly_projection_usd`

Proyección del gasto mensual extrapolando el promedio diario del período consultado.

```jsonc
{ "monthly_projection_usd": 1.023 }
```

**Fórmula:** `promedio_diario_del_período × 30`.

---

### `by_model`

Desglose de costos por modelo LLM.

```jsonc
[{ "model": "gemini-2.5-flash-lite", "cost_usd": 0.021, "input_tokens": 30000, "output_tokens": 8000, "calls": 150 }]
```

**Uso:** comparar eficiencia de modelos, decidir migraciones.  
**Origen:** `SUM(estimated_cost) GROUP BY model_name` en `analytics_events`.  
Los precios por token se leen de `config_pricing.json`.

---

### `by_event_type`

Costo por tipo de operación: LLM primario, fallback, transcripción, análisis de imágenes.

```jsonc
[{ "type": "llm_primary", "cost_usd": 0.031, "calls": 145 }]
```

**Uso:** entender qué tipo de operación consume más presupuesto.

---

### `avg_output_input_ratio`

Ratio promedio entre tokens de salida y tokens de entrada.

```jsonc
{ "avg_output_input_ratio": 0.42 }
```

**Interpretación:**
- `< 0.3` → las respuestas son cortas en relación al prompt (puede ser normal o excesivo en el system prompt)
- `> 1.0` → el modelo genera respuestas muy largas (revisar instrucciones)

---

## Sección 4 — `security`

### `hitl_escalations` y `hitl_rate_pct`

Cantidad y porcentaje de conversaciones derivadas a un agente humano.

```jsonc
{ "hitl_escalations": 5, "hitl_rate_pct": 3.2 }
```

**Origen:** `tool_name = 'solicitar_atencion_humana'` en `analytics_events`.  
**Alerta recomendada:** si la tasa supera el 10%, el agente puede no estar resolviendo correctamente.

---

### `businesses_enabled` / `businesses_disabled`

Estado operativo de los negocios configurados en la plataforma.

```jsonc
{ "businesses_enabled": 4, "businesses_disabled": 1 }
```

**Origen:** campo `enabled` en `config_negocios.json`.

---

### `tool_errors`

Top herramientas con errores registrados (requiere que el código guarde eventos con `event_type = 'tool_error'`).

```jsonc
[{ "tool": "consultar_orden_tiendanube", "errors": 2 }]
```

**Uso:** detectar APIs externas caídas o con tokens vencidos.

---

## Sección 5 — `usage`

### `daily_unique_users`

Usuarios únicos activos por día (medido por `thread_id` distintos).

```jsonc
[{ "date": "2026-06-10", "users": 18 }]
```

**Uso:** gráfico de línea para ver crecimiento o caída de adopción.

---

### `top_tools`

Las 15 herramientas más invocadas en el período.

```jsonc
[{ "tool": "consultar_base_conocimiento", "calls": 210 }]
```

**Uso:** barra horizontal para ver qué funcionalidades usa más cada negocio.

---

### `event_type_distribution`

Distribución de todos los tipos de evento.

```jsonc
[
  { "type": "llm_primary",      "count": 580 },
  { "type": "llm_fallback",     "count": 12 },
  { "type": "transcription",    "count": 34 },
  { "type": "image_analysis",   "count": 8 }
]
```

**Uso:** donut chart para ver mix de operaciones.

---

## Sección 6 — `businesses`

Solo se incluye cuando **no** se filtra por `business_id`. Muestra el ranking de negocios por costo.

```jsonc
[
  {
    "business_id":       "cliente6",
    "events":            320,
    "conversations":     45,
    "cost_usd":          0.0512,
    "avg_latency_ms":    1830,
    "fallback_rate_pct": 1.25
  }
]
```

**Uso:** tabla de negocios para identificar los más activos, más costosos, o con mayor tasa de fallback.

---

## Tabla de origen de datos

| Dato                        | Tabla / Archivo                      | Se registra en                    |
|-----------------------------|--------------------------------------|-----------------------------------|
| Tokens, costos, latencia    | `analytics_events`                   | `analytics.py:registrar_evento()` |
| Tools usadas                | `analytics_events.tool_name`         | `agente.py` → LangGraph           |
| Escalaciones HITL           | `analytics_events` `tool_name=hitl`  | `tools_hitl.py`                   |
| Estado de negocios          | `config_negocios.json`               | Configuración manual              |
| Precios por modelo          | `config_pricing.json`                | Configuración manual              |
| Conversaciones (checkpoints)| `checkpoints` (PostgreSQL)           | LangGraph checkpointer            |

---

## Recomendaciones para Grafana

Si conectás Grafana directamente a PostgreSQL:

```sql
-- Panel: Costo acumulado por día y negocio
SELECT DATE(timestamp) AS time, business_id, SUM(estimated_cost) AS cost
FROM analytics_events
WHERE $__timeFilter(timestamp)
GROUP BY DATE(timestamp), business_id
ORDER BY time;

-- Panel: Latencia P95 por hora
SELECT DATE_TRUNC('hour', timestamp) AS time,
       PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
FROM analytics_events
WHERE $__timeFilter(timestamp)
GROUP BY time ORDER BY time;

-- Panel: Tasa de fallback diaria
SELECT DATE(timestamp) AS time,
       ROUND(COUNT(*) FILTER (WHERE event_type = 'llm_fallback')::numeric / COUNT(*) * 100, 2) AS fallback_pct
FROM analytics_events
WHERE $__timeFilter(timestamp)
GROUP BY DATE(timestamp) ORDER BY time;
```

---

## Alertas recomendadas

| Condición                          | Acción sugerida                              |
|------------------------------------|----------------------------------------------|
| `fallback_rate_pct > 5%`           | Revisar API key del modelo primario          |
| `p95 > 8000ms`                     | Revisar carga del servidor o modelo lento    |
| `hitl_rate_pct > 10%`              | Revisar system prompt del negocio afectado   |
| `tool_errors` con entries nuevos   | Verificar tokens de APIs externas            |
| `monthly_projection_usd` > umbral  | Ajustar TTL de sesiones o filtrar eventos    |
