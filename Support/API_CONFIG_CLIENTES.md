# 📚 API de Gestión de Clientes - SisAgent

Documentación de los endpoints REST para gestionar clientes en `config_negocios.json`.

## 📋 Tabla de Contenidos

- [Listar Clientes](#listar-clientes)
- [Obtener Cliente](#obtener-cliente)
- [Crear Cliente](#crear-cliente)
- [Actualizar Cliente (Completo)](#actualizar-cliente-completo)
- [Actualizar Cliente (Parcial)](#actualizar-cliente-parcial)
- [Eliminar Cliente](#eliminar-cliente)
- [Ejemplos de Uso](#ejemplos-de-uso)

---

## Endpoints

### Listar Clientes

Obtiene la lista completa de clientes configurados.

**Endpoint:** `GET /api/config/clientes`

**Response 200:**
```json
{
  "cliente1": {
    "nombre": "Nike Store Palermo",
    "ttl_sesion_minutos": 60,
    "admin_phone": "54911XXXXXXXX",
    ...
  },
  "cliente2": {
    "nombre": "Luigi's Pizza",
    ...
  }
}
```

**Ejemplo cURL:**
```bash
curl http://localhost:5000/api/config/clientes
```

---

### Obtener Cliente

Obtiene la configuración de un cliente específico.

**Endpoint:** `GET /api/config/clientes/<business_id>`

**Parámetros URL:**
- `business_id` (string): ID del cliente (ej: `cliente1`, `cliente2`)

**Response 200:**
```json
{
  "nombre": "Luigi's Pizza",
  "ttl_sesion_minutos": 6,
  "admin_phone": "5491131376731",
  "fuera_de_servicio": {
    "activo": false,
    "horario_inicio": "09:00",
    "horario_fin": "23:00",
    "dias_laborales": [1, 2, 3, 4, 5, 6],
    "zona_horaria": "America/Argentina/Buenos_Aires",
    "mensaje": []
  },
  "system_prompt": ["..."],
  "mensaje_HITL": "...",
  "mensaje_usuario_1": ["..."],
  "tools_habilitadas": ["ver_menu", "solicitar_atencion_humana"]
}
```

**Response 404:**
```json
{
  "error": "Cliente cliente999 no existe"
}
```

**Ejemplo cURL:**
```bash
curl http://localhost:5000/api/config/clientes/cliente2
```

---

### Crear Cliente

Crea un nuevo cliente en la configuración.

**Endpoint:** `POST /api/config/clientes`

**Request Body:**
```json
{
  "business_id": "cliente10",
  "nombre": "Nueva Tienda",
  "ttl_sesion_minutos": 60,
  "admin_phone": "5491134567890",
  "system_prompt": ["Eres un asistente virtual..."],
  "tools_habilitadas": ["consultar_inventario"]
}
```

**Campos Requeridos:**
- `business_id` (string): ID único del cliente
- `nombre` (string): Nombre del negocio
- `ttl_sesion_minutos` (number): Tiempo de vida de sesión en minutos
- `admin_phone` (string): Teléfono del administrador

**Campos Opcionales:**
- `fuera_de_servicio` (object): Configuración de horario
- `system_prompt` (array): Instrucciones para el agente
- `mensaje_HITL` (string): Mensaje cuando se deriva a humano
- `mensaje_usuario_1` (array): Mensaje inicial al usuario
- `tools_habilitadas` (array): Herramientas disponibles

**Response 201:**
```json
{
  "status": "success",
  "message": "Cliente cliente10 creado",
  "data": {
    "nombre": "Nueva Tienda",
    "ttl_sesion_minutos": 60,
    ...
  }
}
```

**Response 409:**
```json
{
  "error": "Cliente cliente10 ya existe"
}
```

**Ejemplo cURL:**
```bash
curl -X POST http://localhost:5000/api/config/clientes \
  -H "Content-Type: application/json" \
  -d '{
    "business_id": "cliente10",
    "nombre": "Nueva Tienda",
    "ttl_sesion_minutos": 60,
    "admin_phone": "5491134567890",
    "system_prompt": ["Eres un asistente virtual..."]
  }'
```

---

### Actualizar Cliente (Completo)

Actualiza completamente la configuración de un cliente (reemplaza todo).

**Endpoint:** `PUT /api/config/clientes/<business_id>`

**Parámetros URL:**
- `business_id` (string): ID del cliente

**Request Body:**
```json
{
  "nombre": "Luigi's Pizza & Pasta",
  "ttl_sesion_minutos": 10,
  "admin_phone": "5491131376731",
  "fuera_de_servicio": {
    "activo": true,
    "horario_inicio": "10:00",
    "horario_fin": "22:00",
    "dias_laborales": [1, 2, 3, 4, 5],
    "zona_horaria": "America/Argentina/Buenos_Aires",
    "mensaje": ["Estamos cerrados"]
  },
  "system_prompt": ["Eres un camarero italiano..."],
  "mensaje_HITL": "Derivando a atención humana...",
  "mensaje_usuario_1": ["¡Bienvenido a Luigi's!"],
  "tools_habilitadas": ["ver_menu"]
}
```

**Response 200:**
```json
{
  "status": "success",
  "message": "Cliente cliente2 actualizado",
  "data": {
    "nombre": "Luigi's Pizza & Pasta",
    ...
  }
}
```

**Ejemplo cURL:**
```bash
curl -X PUT http://localhost:5000/api/config/clientes/cliente2 \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Luigi''s Pizza & Pasta",
    "ttl_sesion_minutos": 10,
    "admin_phone": "5491131376731",
    "fuera_de_servicio": {...},
    "system_prompt": [...],
    "mensaje_HITL": "...",
    "mensaje_usuario_1": [...],
    "tools_habilitadas": [...]
  }'
```

---

### Actualizar Cliente (Parcial)

Actualiza solo los campos especificados de un cliente.

**Endpoint:** `PATCH /api/config/clientes/<business_id>`

**Parámetros URL:**
- `business_id` (string): ID del cliente

**Request Body (solo campos a actualizar):**
```json
{
  "nombre": "Luigi's Pizza Renovado",
  "ttl_sesion_minutos": 15,
  "fuera_de_servicio": {
    "activo": true
  }
}
```

**Response 200:**
```json
{
  "status": "success",
  "message": "Cliente cliente2 actualizado",
  "updated_fields": ["nombre", "ttl_sesion_minutos", "fuera_de_servicio"],
  "data": {
    "nombre": "Luigi's Pizza Renovado",
    "ttl_sesion_minutos": 15,
    "admin_phone": "5491131376731",
    "fuera_de_servicio": {
      "activo": true,
      "horario_inicio": "09:00",
      ...
    },
    ...
  }
}
```

**Ventajas de PATCH:**
- Solo actualizas lo que necesitas
- Merge recursivo para objetos anidados
- No pierdes los demás campos

**Ejemplo cURL:**
```bash
curl -X PATCH http://localhost:5000/api/config/clientes/cliente2 \
  -H "Content-Type: application/json" \
  -d '{
    "nombre": "Luigi''s Pizza Renovado",
    "ttl_sesion_minutos": 15
  }'
```

---

### Eliminar Cliente

Elimina un cliente de la configuración.

**Endpoint:** `DELETE /api/config/clientes/<business_id>`

**Parámetros URL:**
- `business_id` (string): ID del cliente

**Response 200:**
```json
{
  "status": "success",
  "message": "Cliente cliente10 eliminado",
  "deleted_data": {
    "nombre": "Nueva Tienda",
    ...
  }
}
```

**Response 404:**
```json
{
  "error": "Cliente cliente999 no existe"
}
```

**Ejemplo cURL:**
```bash
curl -X DELETE http://localhost:5000/api/config/clientes/cliente10
```

---

## 📝 Ejemplos de Uso

### Python (requests)

```python
import requests

BASE_URL = "http://localhost:5000"

# Listar todos los clientes
response = requests.get(f"{BASE_URL}/api/config/clientes")
clientes = response.json()
print(f"Total clientes: {len(clientes)}")

# Obtener cliente específico
response = requests.get(f"{BASE_URL}/api/config/clientes/cliente2")
cliente = response.json()
print(f"Cliente: {cliente['nombre']}")

# Crear nuevo cliente
nuevo_cliente = {
    "business_id": "cliente11",
    "nombre": "Tech Store",
    "ttl_sesion_minutos": 30,
    "admin_phone": "5491134567890",
    "system_prompt": ["Eres un vendedor de tecnología"],
    "tools_habilitadas": ["consultar_stock"]
}
response = requests.post(f"{BASE_URL}/api/config/clientes", json=nuevo_cliente)
print(response.json())

# Actualizar parcialmente (PATCH)
actualizaciones = {
    "nombre": "Tech Store Premium",
    "ttl_sesion_minutos": 45
}
response = requests.patch(
    f"{BASE_URL}/api/config/clientes/cliente11",
    json=actualizaciones
)
print(response.json())

# Actualizar completamente (PUT)
cliente_completo = {
    "nombre": "Tech Store Premium",
    "ttl_sesion_minutos": 45,
    "admin_phone": "5491134567890",
    "fuera_de_servicio": {
        "activo": False,
        "horario_inicio": "09:00",
        "horario_fin": "18:00",
        "dias_laborales": [1, 2, 3, 4, 5],
        "zona_horaria": "America/Argentina/Buenos_Aires",
        "mensaje": []
    },
    "system_prompt": ["Eres un vendedor de tecnología premium"],
    "mensaje_HITL": "",
    "mensaje_usuario_1": ["Bienvenido a Tech Store"],
    "tools_habilitadas": ["consultar_stock"]
}
response = requests.put(
    f"{BASE_URL}/api/config/clientes/cliente11",
    json=cliente_completo
)
print(response.json())

# Eliminar cliente
response = requests.delete(f"{BASE_URL}/api/config/clientes/cliente11")
print(response.json())
```

### JavaScript (fetch)

```javascript
const BASE_URL = "http://localhost:5000";

// Listar clientes
fetch(`${BASE_URL}/api/config/clientes`)
  .then(res => res.json())
  .then(data => console.log(`Total clientes: ${Object.keys(data).length}`));

// Obtener cliente
fetch(`${BASE_URL}/api/config/clientes/cliente2`)
  .then(res => res.json())
  .then(data => console.log(`Cliente: ${data.nombre}`));

// Crear cliente
fetch(`${BASE_URL}/api/config/clientes`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    business_id: "cliente12",
    nombre: "Boutique Fashion",
    ttl_sesion_minutos: 30,
    admin_phone: "5491134567890",
    system_prompt: ["Eres un asesor de moda"],
    tools_habilitadas: ["consultar_catalogo"]
  })
})
  .then(res => res.json())
  .then(data => console.log(data));

// Actualizar parcialmente
fetch(`${BASE_URL}/api/config/clientes/cliente12`, {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    nombre: "Boutique Fashion Exclusive",
    ttl_sesion_minutos: 60
  })
})
  .then(res => res.json())
  .then(data => console.log(data));

// Eliminar
fetch(`${BASE_URL}/api/config/clientes/cliente12`, {
  method: 'DELETE'
})
  .then(res => res.json())
  .then(data => console.log(data));
```

---

## 🔐 Seguridad

### Recomendaciones para Producción:

1. **Autenticación**: Agregar middleware de autenticación
   ```python
   from functools import wraps
   
   def requiere_auth(f):
       @wraps(f)
       def decorated(*args, **kwargs):
           token = request.headers.get('Authorization')
           if not validar_token(token):
               return jsonify({"error": "No autorizado"}), 401
           return f(*args, **kwargs)
       return decorated
   
   @app.route('/api/config/clientes', methods=['POST'])
   @requiere_auth
   def crear_cliente():
       ...
   ```

2. **Rate Limiting**: Limitar peticiones por IP
3. **Validación Estricta**: Validar tipos de datos y rangos
4. **Backup Automático**: Hacer backup antes de modificar
5. **Logs de Auditoría**: Registrar quién modifica qué

---

## ⚠️ Notas Importantes

1. **Hot Reload**: Las modificaciones se aplicarán automáticamente gracias al sistema de hot reload de `utilities.py`
2. **Backup**: Se recomienda hacer backup del archivo antes de modificaciones masivas
3. **Validación**: Los endpoints validan campos requeridos pero podrías agregar más validaciones
4. **Codificación**: El archivo se guarda con `encoding='utf-8'` para soportar caracteres especiales
5. **Formato**: El JSON se guarda con `indent=2` para mantener legibilidad

---

## 🧪 Testing

### Test Manual con cURL:

```bash
# 1. Listar clientes
curl http://localhost:5000/api/config/clientes

# 2. Crear cliente de prueba
curl -X POST http://localhost:5000/api/config/clientes \
  -H "Content-Type: application/json" \
  -d '{
    "business_id": "test_cliente",
    "nombre": "Test Store",
    "ttl_sesion_minutos": 30,
    "admin_phone": "5491111111111"
  }'

# 3. Obtener cliente creado
curl http://localhost:5000/api/config/clientes/test_cliente

# 4. Actualizar parcialmente
curl -X PATCH http://localhost:5000/api/config/clientes/test_cliente \
  -H "Content-Type: application/json" \
  -d '{"nombre": "Test Store Updated"}'

# 5. Eliminar cliente de prueba
curl -X DELETE http://localhost:5000/api/config/clientes/test_cliente
```

---

## 📊 Estructura de Datos

### Esquema de Cliente:

```typescript
interface Cliente {
  nombre: string;                    // Nombre del negocio
  ttl_sesion_minutos: number;       // TTL de sesión
  admin_phone: string;              // Teléfono admin
  fuera_de_servicio: {
    activo: boolean;
    horario_inicio: string;         // HH:MM
    horario_fin: string;            // HH:MM
    dias_laborales: number[];       // 1-7 (Lun-Dom)
    zona_horaria: string;           // TZ identifier
    mensaje: string[];
  };
  system_prompt: string[];          // Instrucciones del sistema
  mensaje_HITL: string;             // Mensaje derivación humana
  mensaje_usuario_1: string[];     // Mensaje inicial
  tools_habilitadas: string[];     // Herramientas disponibles
}
```

---

¿Preguntas? Contacta al equipo de desarrollo.
