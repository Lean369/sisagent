#!/bin/bash
# Script para probar envío de documento desde el webhook

# Endpoint del webhook local
WEBHOOK_URL="http://localhost:5001/webhook/evoapi"

# Payload simulando Evolution API enviando un mensaje con texto que active el envío de documento
# El bot debería reconocer este comando y enviar el documento

cat << 'EOF' > /tmp/test_documento_payload.json
{
  "event": "messages.upsert",
  "instance": "cliente2",
  "data": {
    "key": {
      "remoteJid": "5491131376731@s.whatsapp.net",
      "fromMe": false,
      "id": "TEST_DOC_" 
    },
    "pushName": "Usuario Test",
    "message": {
      "conversation": "enviar documento de prueba"
    }
  }
}
EOF

echo "📤 Enviando payload de prueba al webhook..."
echo ""

curl -X POST \
  -H "Content-Type: application/json" \
  -d @/tmp/test_documento_payload.json \
  $WEBHOOK_URL

echo ""
echo ""
echo "✅ Payload enviado. Revisar logs para ver el resultado."
