# Meta Embedded Signup v4 — Guía Completa

**Última actualización:** Febrero 2026  
**Aplica a:** WhatsApp Business Platform (Cloud API)

---

## ¿Qué es Embedded Signup?

Embedded Signup es el mecanismo oficial de Meta para que un **Tech Provider o Solution Partner** permita a sus clientes (negocios) conectar su cuenta de WhatsApp Business a la plataforma del provider, **sin que el cliente tenga que realizar configuraciones técnicas manuales**.

Desde la perspectiva del cliente: hace clic en un botón, se autentica con su cuenta de Facebook/Meta, selecciona su WABA y número de teléfono, y listo.  
Desde la perspectiva del backend: el provider recibe credenciales para operar ese número en nombre del cliente via Cloud API.

---

## Actores y roles

| Actor | Descripción |
|---|---|
| **Tech Provider / Solution Partner** | La empresa que construye la plataforma (vos). Tiene una Meta App registrada. |
| **Business Customer** | El negocio que quiere conectar su WhatsApp. Tiene un WABA y un número de teléfono. |
| **Meta Graph API** | La API de Meta para intercambiar tokens y registrar activos. |
| **WhatsApp Cloud API** | La API para enviar/recibir mensajes una vez que el número está registrado. |

---

## Requisitos previos

1. **Meta for Developers App** creada en [developers.facebook.com](https://developers.facebook.com).
2. **Facebook Login for Business** habilitado en tu app.
3. **Dominio con HTTPS** donde hostearás la página de signup.
4. El dominio debe estar añadido en:
   - *Facebook Login for Business → Settings → Allowed domains*
   - *Valid OAuth redirect URIs*
5. Crear una **Configuración de Login** desde *Facebook Login for Business → Configurations*, usando el template **"WhatsApp Embedded Signup Configuration With 60 Expiration Token"**.
6. Guardar el **Configuration ID** generado (lo necesitarás en el frontend).
7. Tener el **App ID** y el **App Secret** de tu Meta App.

---

## Flujo Completo Paso a Paso

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (Browser)                              │
│                                                                          │
│  1. Cliente hace clic en "Conectar WhatsApp"                             │
│  2. FB.login() abre el popup de Embedded Signup de Meta                  │
│  3. Cliente se autentica con FB y selecciona su WABA/número              │
│  4. Meta envía DOS eventos al frontend:                                  │
│     a. postMessage → { phone_number_id, waba_id, business_id }           │
│     b. FB.login callback → { authResponse: { code } }  (TTL: 30s)       │
│  5. Frontend juntas los dos eventos y hace POST al backend               │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │  POST /api/onboard-whatsapp
                                    │  { code, phone_number_id, waba_id }
┌───────────────────────────────────▼─────────────────────────────────────┐
│                          BACKEND (Python/Flask)                          │
│                                                                          │
│  Paso 1: Exchange code → access_token                                    │
│          GET graph.facebook.com/v21.0/oauth/access_token                 │
│                                                                          │
│  Paso 2: Registrar número para Cloud API                                 │
│          POST graph.facebook.com/v21.0/{phone_number_id}/register        │
│                                                                          │
│  Paso 3: Suscribir app a webhooks del WABA                               │
│          POST graph.facebook.com/v21.0/{waba_id}/subscribed_apps         │
│                                                                          │
│  Paso 4: Crear instancia en Evolution API (o tu proveedor de BSP)        │
│          POST evoapi.sisnova.com.ar/instance/create                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Detalle del Frontend

### Inicialización del SDK

```javascript
window.fbAsyncInit = function() {
  FB.init({
    appId: 'TU_APP_ID',       // ID de tu Meta App
    version: 'v21.0',          // Versión de Graph API
    xfbml: true,
    cookie: true
  });
};
```

### Listener de postMessage

Meta envía este evento cuando el usuario **completa** el flujo:

```javascript
window.addEventListener('message', function(event) {
  if (!event.origin.endsWith('facebook.com')) return;
  const data = JSON.parse(event.data);
  if (data.type === 'WA_EMBEDDED_SIGNUP') {
    if (data.event === 'FINISH') {
      // data.data contiene: phone_number_id, waba_id, business_id
      _sessionData = data.data;
    } else if (data.event === 'CANCEL') {
      // data.data.current_step indica en qué pantalla se canceló
    }
  }
});
```

**Posibles valores de `data.event`:**

| Valor | Significado |
|---|---|
| `FINISH` | Onboarding completo con número de teléfono |
| `FINISH_ONLY_WABA` | Completó sin número de teléfono |
| `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` | Completó con un número de WhatsApp Business App |
| `CANCEL` | El usuario abandonó el flujo |

### Lanzar el flujo (FB.login)

```javascript
FB.login(function(response) {
  if (response.authResponse) {
    const code = response.authResponse.code; // ⚠️ Expira en 30 segundos
    // Enviar code + datos del postMessage al backend
  }
}, {
  config_id: 'TU_CONFIGURATION_ID',
  response_type: 'code',                    // ← Obligatorio para Embedded Signup v4
  override_default_response_type: true,     // ← Obligatorio
  extras: { setup: {} }
});
```

> ⚠️ **IMPORTANTE:** El `code` tiene un TTL de **30 segundos**. El backend debe intercambiarlo por el token inmediatamente.

---

## Detalle del Backend

### Paso 1: Intercambiar el código por un Access Token

```
GET https://graph.facebook.com/v21.0/oauth/access_token
    ?client_id={APP_ID}
    &client_secret={APP_SECRET}
    &code={CODE}
```

**Respuesta:**
```json
{
  "access_token": "EAABcde...",
  "token_type": "bearer"
}
```

> **Nota:** Para el flujo iniciado por `FB.login()`, **NO** incluir `redirect_uri`. Solo se usa si el flujo fue originado por una URL de redirect OAuth estándar.

---

### Paso 2: Registrar el número de teléfono para Cloud API

Este paso activa el número en Cloud API. Sin él, el número no puede enviar ni recibir mensajes via API.

```
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/register
Authorization: Bearer {ACCESS_TOKEN}
Content-Type: application/json

{
  "messaging_product": "whatsapp",
  "pin": "000000"
}
```

**Respuesta exitosa:** `{ "success": true }`

> El `pin` es un código de verificación de 6 dígitos. Si el número ya tiene un PIN configurado por el cliente, debe usar ese valor. `000000` funciona para números nuevos sin PIN previo.

---

### Paso 3: Suscribir la app a los webhooks del WABA

Necesario para que los mensajes entrantes del cliente lleguen a tu webhook.

```
POST https://graph.facebook.com/v21.0/{WABA_ID}/subscribed_apps
Authorization: Bearer {ACCESS_TOKEN}
```

**Respuesta exitosa:** `{ "success": true }`

> Después de esto, los mensajes de los usuarios finales del cliente llegarán a tu webhook configurado en la Meta App.

---

### Paso 4 (Solution Partners solamente): Compartir línea de crédito

Solo obligatorio para **Solution Partners** (no para Tech Providers):

```
POST https://graph.facebook.com/v21.0/{CREDIT_LINE_ID}/whatsapp_credit_sharing_and_attach
Authorization: Bearer {PARTNER_SYSTEM_USER_TOKEN}
Content-Type: application/json

{
  "waba_id": "{CUSTOMER_WABA_ID}",
  "waba_currency": "USD"
}
```

---

## Diferencias: Tech Provider vs Solution Partner

| | Tech Provider | Solution Partner |
|---|---|---|
| Paga las conversaciones | El cliente paga directo a Meta | El partner paga y factura al cliente |
| Compartir línea de crédito | ❌ No requerido | ✅ Obligatorio |
| Acceso al WABA | Sistema User del cliente | Sistema User del partner |
| Caso de uso típico | SaaS donde cada cliente tiene su cuenta Meta | Servicio gestionado, el partner administra todo |

---

## Variables de entorno necesarias

```bash
# Meta App
META_APP_ID=123456789012345
META_APP_SECRET=abcdef1234567890abcdef1234567890
GRAPH_VERSION=v21.0

# Configuración de Embedded Signup
CONFIG_ID=1234567890123456  # ID de tu Facebook Login for Business Configuration

# Para el flujo OAuth estándar (si usás redirect_uri)
REDIRECT_URI=https://tu-dominio.com/callback/whatsapp

# Evolution API (si usás Evolution como BSP)
EVOLUTION_API_URL=https://tu-evolution-api.com
EVOLUTION_API_KEY=tu-api-key
```

---

## Webhooks a configurar en Meta App

Para recibir notificaciones debes estar suscripto (en tu Meta App) a:

| Webhook | Para qué sirve |
|---|---|
| `messages` | Mensajes entrantes y estados de entrega |
| `account_update` | Se dispara cuando un cliente completa el Embedded Signup. Contiene info del negocio. |
| `message_template_status_update` | Notificaciones cuando aprueban/rechazan templates |
| `phone_number_quality_update` | Cambios en la calidad del número |

---

## Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `code` ya expiró | El backend tardó más de 30s en intercambiar el token | Asegurarse de que el POST del frontend llegue de inmediato |
| `OAuthException: Invalid OAuth access token` | Token incorrecto o expirado | Verificar que se intercambió el code correctamente |
| `Invalid parameter: pin` | PIN incorrecto para un número con 2FA activado | Pedir el PIN al cliente o usar el de su cuenta previamente |
| `Error code 100` al registrar | El número ya está registrado en Cloud API | Verificar si ya existe una instancia, continuar al paso 3 |
| Popup bloqueado | El browser bloqueó el popup de `FB.login()` | `FB.login()` debe llamarse **directamente desde un evento de usuario** (onclick) |
| `FB is not defined` | SDK no cargó aún | Asegurarse de que `FB.login()` se llama después de que `fbAsyncInit` fue invocado |
| Dominio no permitido | El dominio no está en Allowed Domains | Agregar el dominio en Facebook Login for Business → Settings |

---

## Flujo en esta implementación (sisagent)

```
Frontend:  /onboard-whatsapp
              ↓ FB.login() + postMessage listener
Backend:   POST /api/onboard-whatsapp
              ↓ 1. Exchange code → access_token
              ↓ 2. POST /{phone_number_id}/register
              ↓ 3. POST /{waba_id}/subscribed_apps
              ↓ 4. POST evoapi.sisnova.com.ar/instance/create
               (crea instancia WHATSAPP-BUSINESS en Evolution API)
```

---

## Referencias

- [Meta: Embedded Signup Overview](https://developers.facebook.com/docs/whatsapp/embedded-signup)
- [Meta: Implementation Guide (v4)](https://developers.facebook.com/docs/whatsapp/embedded-signup/implementation)
- [Meta: Onboarding as Tech Provider](https://developers.facebook.com/docs/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider)
- [Meta: Onboarding as Solution Partner](https://developers.facebook.com/docs/whatsapp/embedded-signup/onboarding-customers-as-a-solution-partner)
- [Meta: Embedded Signup Errors](https://developers.facebook.com/docs/whatsapp/embedded-signup/errors)
- [Meta: Register Phone Number](https://developers.facebook.com/docs/whatsapp/cloud-api/reference/registration)
- [Meta: Webhooks for WhatsApp Business](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks)
