# 📄 Documento PDF de Prueba para Evolution API

## ✅ Archivos Generados

### 1. **documento_prueba.pdf** (717 bytes)
PDF binario listo para visualizar o enviar.

### 2. **documento_prueba_base64.txt** (956 caracteres)
Versión en Base64 del PDF, lista para usar en APIs.

**Contenido Base64:**
```
JVBERi0xLjQKMSAwIG9iago8PAovVHlwZSAvQ2F0YWxvZwovUGFnZXMgMiAwIFIKPj4KZW5kb2JqCgoyIDAgb2JqCjw8Ci9UeXBlIC9QYWdlcwovS2lkcyBbMyAwIFJdCi9Db3VudCAxCj4+CmVuZG9iagoKMyAwIG9iago8PAovVHlwZSAvUGFnZQovUGFyZW50IDIgMCBSCi9NZWRpYUJveCBbMCAwIDYxMiA3OTJdCi9Db250ZW50cyA0IDAgUgovUmVzb3VyY2VzIDw8Ci9Gb250IDw8Ci9GMSA8PAovVHlwZSAvRm9udAovU3VidHlwZSAvVHlwZTEKL0Jhc2VGb250IC9IZWx2ZXRpY2EKPj4KPj4KPj4KPj4KZW5kb2JqCgo0IDAgb2JqCjw8Ci9MZW5ndGggMjAwCj4+CnN0cmVhbQpCVAovRjEgMjQgVGYKNTAgNzAwIFRkCihEb2N1bWVudG8gZGUgUHJ1ZWJhKSBUagowIC00MCBUZAovRjEgMTQgVGYKKEdlbmVyYWRvOiAyMDI2LTAyLTE5IDE3OjM1OjIyKSBUagowIC0zMCBUZAooRXN0ZSBlcyB1biBQREYgZGUgcHJ1ZWJhIHBhcmEgRXZvbHV0aW9uIEFQSSkgVGoKMCAtMzAgVGQKKFNpc3RlbWE6IFNpc0FnZW50IC0gV2hhdHNBcHAgQm90KSBUagpFVAplbmRzdHJlYW0KZW5kb2JqCgp4cmVmCjAgNQowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDA3NCAwMDAwMCBuIAowMDAwMDAwMTMxIDAwMDAwIG4gCjAwMDAwMDAzMTEgMDAwMDAgbiAKdHJhaWxlcgo8PAovU2l6ZSA1Ci9Sb290IDEgMCBSCj4+CnN0YXJ0eHJlZgo1NjMKJSVFT0YK
```

---

## 🔧 Función Actualizada en app.py

La función `enviar_documento_whatsapp()` ahora soporta **URL y Base64**:

```python
def enviar_documento_whatsapp(numero_destino: str, documento, nombre_instancia: str = None, 
                              filename: str = "documento.pdf", caption: str = None):
    """
    Envía un documento a través del cliente de Evolution API.
    
    Args:
        numero_destino: Número en formato internacional (549...)
        documento: URL o Base64 del documento
        nombre_instancia: Nombre de la instancia Evolution
        filename: Nombre del archivo que verá el usuario
        caption: Texto opcional que acompaña al documento
    """
```

### Uso con URL:
```python
enviar_documento_whatsapp(
    "5491131376731",
    "https://ejemplo.com/documento.pdf",
    "cliente2",
    "factura_2024.pdf",
    "Aquí está tu factura"
)
```

### Uso con Base64:
```python
with open('documento_prueba_base64.txt', 'r') as f:
    base64_data = ''.join([line for line in f if not line.startswith('#')]).strip()

enviar_documento_whatsapp(
    "5491131376731",
    base64_data,
    "cliente2",
    "documento_prueba.pdf",
    "📄 Documento de prueba"
)
```

---

## 📤 Payload Evolution API (Baileys)

### Endpoint:
```
POST /message/sendMedia/{instance}
```

### Estructura del Payload:
```json
{
  "number": "5491131376731",
  "mediatype": "document",
  "mimetype": "application/pdf",
  "caption": "📄 Documento de prueba generado por SisAgent",
  "fileName": "documento_prueba.pdf",
  "media": "<BASE64_AQUI>"
}
```

### Tipos de documento soportados:
- **PDF**: `application/pdf`
- **Word**: `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- **Excel**: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- **PowerPoint**: `application/vnd.openxmlformats-officedocument.presentationml.presentation`
- **Texto**: `text/plain`
- **ZIP**: `application/zip`

---

## 🧪 Scripts de Prueba

### 1. Generar nuevo PDF:
```bash
python generar_pdf_base64.py
```

### 2. Enviar documento directamente:
```bash
source .venv/bin/activate
python enviar_documento_ahora.py
```

### 3. Probar via webhook:
```bash
./test_webhook_documento.sh
```

---

## 📝 Ejemplo de Uso en el Bot

El bot puede enviar documentos desde cualquier tool o respuesta:

```python
# En una tool o función del agente:
from app import enviar_documento_whatsapp

# Opción 1: URL pública
enviar_documento_whatsapp(
    user_id,
    "https://mi-servidor.com/catalogo.pdf",
    business_id,
    "catalogo_productos.pdf",
    "Aquí está nuestro catálogo de productos"
)

# Opción 2: PDF generado dinámicamente
import base64
pdf_bytes = generar_factura(cliente_id)  # Tu función que genera PDF
pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

enviar_documento_whatsapp(
    user_id,
    pdf_base64,
    business_id,
    f"factura_{cliente_id}.pdf",
    "Tu factura del mes"
)
```

---

## 🎯 Características Implementadas

✅ Soporte para URLs externas  
✅ Soporte para Base64 directo  
✅ Detección automática del tipo (URL vs Base64)  
✅ Limpieza de prefijos `data:application/pdf;base64,`  
✅ Configuración de nombre de archivo personalizado  
✅ Caption opcional para documentos  
✅ Logging detallado de operaciones  
✅ Manejo de errores robusto  

---

## 🔄 Cambios Aplicados

1. ✅ Función `enviar_documento_whatsapp()` actualizada en [app.py](app.py#L43-L82)
2. ✅ Endpoint cambiado de `/message/sendDocument/` a `/message/sendMedia/`
3. ✅ Payload adaptado al formato correcto de Baileys
4. ✅ Servicio reiniciado (PID: 1078309)
5. ✅ Health check OK

---

## 📊 Archivos Disponibles

```
/home/leanusr/sisagent/
├── documento_prueba.pdf              # PDF binario (717 bytes)
├── documento_prueba_base64.txt       # Base64 del PDF (956 chars)
├── generar_pdf_base64.py            # Script generador
├── enviar_documento_ahora.py        # Script de envío directo
└── test_webhook_documento.sh        # Test via webhook
```

---

## 💡 Recomendaciones

1. Para documentos > 10 MB, usar siempre URL  
2. Para documentos generados dinámicamente < 5 MB, Base64 es eficiente  
3. Validar MIME type según el tipo de archivo  
4. Usar nombres de archivo descriptivos para mejor UX  
5. Incluir caption explicativo cuando sea relevante  

---

## 🚀 Próximos Pasos

Para enviar un documento en producción:

1. **Generar o descargar el documento**
2. **Convertir a Base64** (si no tienes URL pública)
3. **Llamar a la función** con los parámetros correctos
4. **Verificar en logs** que el envío fue exitoso

**Ejemplo rápido:**
```python
# Cargar base64 del archivo
with open('documento_prueba_base64.txt', 'r') as f:
    base64_pdf = ''.join([line for line in f if not line.startswith('#')]).strip()

# Enviar
enviar_documento_whatsapp(
    "5491131376731",
    base64_pdf,
    "cliente2",
    "documento_prueba.pdf",
    "📄 Tu documento está listo"
)
```

---

**Generado:** 2026-02-19  
**Estado:** ✅ Listo para usar  
**PID Servicio:** 1078309
