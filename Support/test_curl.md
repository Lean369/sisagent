curl -sS -X POST "https://evoapi.sisnova.com.ar/message/sendText/cliente2" \
  -H "Content-Type: application/json" \
  -H "apikey: 0BA3E081C9A3-43FB-AB61-99615722A08C" \
  -d '{"number": "5491131376731", "text": "Prueba manual"}'


curl -X DELETE http://localhost:5000/borrar_memoria \
  -H "Content-Type: application/json" \
  -d '{"user_id":"5491131376731@s.whatsapp.net", "business_id":"cliente2"}'

curl -X POST http://localhost:5000/reactivar_bot \
  -H "Content-Type: application/json" \
  -d '{"user_id": "5491131376731@s.whatsapp.net", "business_id": "cliente2"}'


http://192.168.1.220:5000/reactivar_bot_web?business_id=cliente2&user_id=5491131376731@s.whatsapp.net

curl -s -X POST "https://evoapi.sisnova.com.ar/instance/create" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" \
  -d '{
    "instanceName": "cliente3",
    "integration": "EVOLUTION",
    "qrcode": true
  }' | jq '.'

curl -s -X GET "https://evoapi.sisnova.com.ar/instance/connect/cliente3" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" | jq '.'

curl -s -X GET "https://evoapi.sisnova.com.ar/instance/fetchInstances" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" | jq '.[] | select(.name == "cliente3")'



curl -X GET "https://evoapi.sisnova.com.ar/instance/connectionState/cliente2" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20"

curl -X GET "https://evoapi.sisnova.com.ar/instance/fetchInstances" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20"

## Ejemplo de creación de instancia y envío de mensaje con Channel Evolution:

curl -X POST https://evoapi.sisnova.com.ar/instance/create \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" \
  -d '{
    "instanceName": "cliente2",
    "integration": "EVOLUTION",
    "number": "5491144125978",
    "qrcode": false
  }'

curl -X POST https://evoapi.sisnova.com.ar/webhook/evolution \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" \
  -d '{
    "numberId": "5491144125978", 
    "key": {
        "remoteJid": "5491131376731",
        "fromMe": false,
        "id": "ABC1234"
    },
    "pushName": "Davidson",
    "message": {
        "conversation": "What is your name?"
    },
    "messageType": "conversation"
}'

# Ejemplo de creación de instancia y envío de mensaje con Channel WhatsApp Business API:

```bash
# Eliminar instancia actual
curl -X DELETE "https://evoapi.sisnova.com.ar/instance/delete/cliente3" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20"
```
```bash
# Crear con phone_number_id correcto
curl -X POST "https://evoapi.sisnova.com.ar/instance/create" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" \
  -d '{
    "instanceName": "wsapi-sisnova",
    "integration": "WHATSAPP-BUSINESS",
    "number": "992059843994228",
    "businessId": "746088638381916",
    "token": "EAAbAU6YHbzQBQwtyoFjBjc4b6fnUnAjDwEGJlRdGZCLjpiNeGi824aG953V9uGSpMlOfWJli6XZB7WNX5ed3Wvet87bT7rpaFOKZCxhFpFKOicA8yyBPRpqEOmPOr4AMFK9nLMW15vd5hoaS2GztiJsYHV1jioJ18Ggbostdu1YNjhHwDgrVQ4YCKJoIUIiZBwZDZD"
  }'
```
```bash
# Configurar webhook interno
curl -X POST "https://evoapi.sisnova.com.ar/webhook/set/wsapi-sisnova" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "url": "https://sisagent.sisnova.org/webhook/evoapi",
      "enabled": true,
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```
```bash
# Obtener configuración de la instancia para verificar que el webhook se guardó correctamente
  curl -s -X GET "https://evoapi.sisnova.com.ar/instance/fetchInstances" \
  -H "apikey: 9d15c6d04d216cc8becc3721d8199c20" \
  -H "Content-Type: application/json" | jq '.[] | select(.name == "wsapi-sisnova") | {name, integration, number, businessId, token: (.token[:50] + "...")}'
```