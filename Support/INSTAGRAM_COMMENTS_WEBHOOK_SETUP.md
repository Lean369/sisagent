# Configuración de Webhook para Comentarios de Instagram

## 📋 Resumen

Esta guía explica cómo configurar el webhook de Instagram para recibir comentarios de publicaciones directamente en tu agente IA Python, sin depender de Chatwoot (que no soporta comentarios).

## 🔧 Configuración del Servidor

### 1. Variables de Entorno (.env)

Ya configuradas en `/root/sisagent/sisagent-flask-directo/.env`:

```bash
# Configuración de Instagram Business API (para comentarios)
INSTAGRAM_ACCESS_TOKEN=IGAASo4iYH7VJBZAFB6WEYxS2pyTlFTeVBTMkhZATEZAubU1vV2VkeUJJcEhNYUM2VjR3R1JMTXc1SXI5MEMzRHFodEVXSzgwVTZAOSnNNT1pDRzlMRHNaZADY0VXdLb1l1UWtyZAGJGTEt1SUVESkpfcTkzVFZAOaS1qS29raU5MVHB3UQZDZD
INSTAGRAM_VERIFY_TOKEN=instagram_webhook_verify_2026
INSTAGRAM_PAGE_ID=17841478854980502
FB_APP_SECRET=4764c806108c289f7bf12fecd1d514fa
FB_APP_ID=1311589160971602
```

### 2. Endpoint Creado

✅ **URL del webhook:** `https://sisagent.sisnova.com.ar/webhook/instagram`

El endpoint está implementado en `app.py` y soporta:
- **GET:** Verificación de webhook por Meta (challenge/response)
- **POST:** Recepción de comentarios de Instagram

## 📱 Configuración en Meta Developer Console

### Paso 1: Acceder a la App de Facebook

1. Ve a [Meta Developer Console](https://developers.facebook.com/apps)
2. Selecciona tu app (ID: `1311589160971602`)
3. En el menú lateral, busca **"Productos"** → **"Webhooks"**

### Paso 2: Configurar Webhook de Instagram

1. En la sección de Webhooks, busca **"Instagram"**
2. Haz clic en **"Edit Subscription"** o **"Configure"**

#### Configurar URL del Webhook:

```
Callback URL: https://sisagent.sisnova.com.ar/webhook/instagram
Verify Token: instagram_webhook_verify_2026
```

3. Haz clic en **"Verify and Save"** (Meta hará una petición GET para verificar)
4. Si la verificación es exitosa, verás un ✅ verde

### Paso 3: Suscribirse a Eventos

Selecciona los siguientes campos de suscripción:

- ✅ **comments** - Comentarios en publicaciones
- ✅ **mentions** (opcional) - Menciones en stories
- ✅ **live_comments** (opcional) - Comentarios en vivos

Haz clic en **"Save"**

### Paso 4: Conectar Instagram Business Account

1. Ve a **"Instagram Business Account"** en el menú de productos
2. Conecta tu cuenta de Instagram Business: `sisnova.tech`
3. Verifica que el Page ID sea: `17841478854980502`

## 🧪 Probar el Webhook

### Test desde Meta Console

1. En la sección de Webhooks, busca tu suscripción de Instagram
2. Haz clic en **"Test"** → **"Comments"**
3. Meta enviará un webhook de prueba a tu servidor
4. Verifica en logs del Flask app:

```bash
cd /root/sisagent/sisagent-flask-directo
./agent-manager.sh logs | grep "Instagram"
```

### Test Real

1. Publica una foto/video/reel en `@sisnova.tech`
2. Comenta en la publicación desde otra cuenta
3. Verifica que llegue el webhook y el agente responda

## 📊 Estructura del Webhook

### Payload de Comentario

```json
{
  "entry": [
    {
      "id": "17841478854980502",
      "time": 1772314320,
      "changes": [
        {
          "field": "comments",
          "value": {
            "from": {
              "id": "2978593885678283",
              "username": "lean396"
            },
            "media": {
              "id": "17893439049281758",
              "media_product_type": "REELS"
            },
            "id": "18057496505389779",
            "text": "Hola, ¿cuánto cuesta?"
          }
        }
      ]
    }
  ]
}
```

## 🔄 Flujo de Procesamiento

1. **Meta envía webhook** → `https://sisagent.sisnova.com.ar/webhook/instagram`
2. **Flask recibe comentario** → Extrae `username`, `text`, `media_id`
3. **ThreadPool procesa** → `procesar_y_responder_instagram()`
4. **Agente IA responde** → LangGraph genera respuesta
5. **Respuesta en Instagram** → Graph API publica respuesta al comentario

## 🔍 Monitoreo y Logs

```bash
# Ver logs en tiempo real
cd /root/sisagent/sisagent-flask-directo
./agent-manager.sh logs

# Buscar eventos de Instagram específicamente
./agent-manager.sh logs | grep "💬 Comentario IG"
./agent-manager.sh logs | grep "📸 Instagram webhook"

# Ver errores
./agent-manager.sh logs | grep "ERROR.*Instagram"
```

## ⚠️ Limitaciones y Consideraciones

1. **Instagram API Rate Limits:**
   - 200 llamadas por hora por usuario
   - 4800 llamadas por día por app

2. **Longitud de Respuesta:**
   - Máximo 500 caracteres por comentario
   - El código trunca automáticamente respuestas largas

3. **Permisos Requeridos:**
   - `instagram_basic`
   - `instagram_manage_comments`
   - `instagram_manage_messages`
   - `pages_read_engagement`
   - `pages_manage_metadata`

4. **Aprobación de Meta:**
   - Los permisos avanzados requieren revisión de apps por Meta
   - Proceso toma 1-5 días hábiles

## 🔐 Seguridad

- El endpoint valida el `verify_token` en peticiones GET
- Usa HTTPS (certificado SSL válido requerido por Meta)
- Los logs NO muestran tokens completos (primeros 20 chars únicamente)

## 📞 Troubleshooting

### Webhook no se verifica:
- Verifica que `INSTAGRAM_VERIFY_TOKEN` coincida exactamente
- Revisa que Flask esté corriendo: `curl https://sisagent.sisnova.com.ar/health`
- Verifica que Traefik esté ruteando correctamente

### Comentarios no llegan:
- Revisa permisos en Meta Console
- Verifica que la cuenta de Instagram esté conectada como Business Account
- Revisa logs: `./agent-manager.sh logs | grep Instagram`

### Respuesta no se envía:
- Verifica `INSTAGRAM_ACCESS_TOKEN` válido
- Revisa que el token tenga permisos `instagram_manage_comments`
- Verifica rate limits de Instagram Graph API

## 📚 Recursos Adicionales

- [Instagram Graph API - Comments](https://developers.facebook.com/docs/instagram-api/reference/ig-comment)
- [Webhooks de Instagram](https://developers.facebook.com/docs/instagram-api/webhooks)
- [Graph API Explorer](https://developers.facebook.com/tools/explorer/)

---

**Última actualización:** 28 de febrero de 2026  
**Autor:** Sisagent Team  
**Version:** 1.0.0
