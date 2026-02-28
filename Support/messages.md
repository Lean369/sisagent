
# Mensajes entrantes:

## Ejemplo de payload de mensaje entrante que recibe el webhook de Evolution API canal API:

```json
{
  "event": "messages.upsert",
  "instance": "cliente2",
  "data": {
    "key": {
      "remoteJid": "5491131376731@s.whatsapp.net",
      "remoteJidAlt": "5491131376731@s.whatsapp.net",
      "fromMe": false,
      "id": "AC37559D8001E5AD80AABD8E0BB9B006",
      "participant": "",
      "addressingMode": "lid"
    },
    "pushName": "Leandro",
    "status": "DELIVERY_ACK",
    "message": {
      "conversation": "Hola, que venden?",
      "messageContextInfo": {
        "threadId": [],
        "deviceListMetadata": {
          "senderKeyIndexes": [],
          "recipientKeyIndexes": [],
          "senderKeyHash": {
            "0": 78,
            "1": 156,
            "2": 105,
            "3": 90,
            "4": 140,
            "5": 106,
            "6": 123,
            "7": 176,
            "8": 234,
            "9": 180
          },
          "senderTimestamp": { "low": 1770335675, "high": 0, "unsigned": true },
          "recipientKeyHash": {
            "0": 219,
            "1": 29,
            "2": 128,
            "3": 21,
            "4": 120,
            "5": 226,
            "6": 43,
            "7": 12,
            "8": 41,
            "9": 71
          },
          "recipientTimestamp": {
            "low": 1771275008,
            "high": 0,
            "unsigned": true
          }
        },
        "deviceListMetadataVersion": 2,
        "messageSecret": {
          "0": 208,
          "1": 216,
          "2": 144,
          "3": 115,
          "4": 187,
          "5": 51,
          "6": 72,
          "7": 85,
          "8": 122,
          "9": 27,
          "10": 12,
          "11": 68,
          "12": 103,
          "13": 6,
          "14": 143,
          "15": 152,
          "16": 60,
          "17": 217,
          "18": 212,
          "19": 47,
          "20": 66,
          "21": 121,
          "22": 215,
          "23": 113,
          "24": 25,
          "25": 213,
          "26": 74,
          "27": 191,
          "28": 13,
          "29": 207,
          "30": 159,
          "31": 245
        }
      }
    },
    "messageType": "conversation",
    "messageTimestamp": 1771373387,
    "instanceId": "84811dcf-3941-4304-b9a4-1f58f378feae",
    "source": "android"
  },
  "destination": "https://sisagent.sisnova.org/webhook/evoapi",
  "date_time": "2026-02-17T21:09:48.104Z",
  "sender": "5491144125978@s.whatsapp.net",
  "server_url": "https://evoapi.sisnova.com.ar",
  "apikey": "9D88E4A5-C33A-4BE4-8587-333689F09235"
}
```

## Ejemplo de payload de mensaje entrante que recibe el webhook de Evolution API canal API:

```json
{
  "event": "messages.upsert",
  "instance": "cliente3",
  "data": {
    "key": {
      "id": "wamid.HBgNNTQ5MTEzMTM3NjczMRUCABIYFjNFQjAwNDNFMzhDNkVGNjBEMEQ2QjgA",
      "remoteJid": "541131376731@s.whatsapp.net",
      "fromMe": false
    },
    "pushName": "Leandro",
    "message": { "conversation": "hola!" },
    "messageType": "conversation",
    "messageTimestamp": 1771383139,
    "source": "unknown",
    "instanceId": "6ba5531b-0063-4c91-b389-b2a21b3137e9"
  },
  "destination": "https://sisagent.sisnova.org/webhook/evoapi",
  "date_time": "2026-02-17T23:52:20.829Z",
  "server_url": "https://evoapi.sisnova.com.ar",
  "apikey": "EAARU4bSxtyYBO1XzfvLKB4PXfAoIAt4GYGqQgGb4ZA3fhbnWbJ8qxu7lS12HkGZAGcjvOaWUsrXcYJxfBdv2wdJnQYj9Ivm1QEgRo0ftX3mbafLAmsaNrZCevFx3jPHgZCkzNNaRXJS2FQGKIrkpJqXIORZB5KJZBavlMfn8cPmqR1bSe4gG5HPZBtUqNlEZBvVDwwZDZD"
}
```

## Ejemplo de payload de mensaje entrante que recibe el webhook de Chatwoot:
```json
{
  "account": { "id": 1, "name": "cliente1" },
  "additional_attributes": {},
  "content_attributes": {},
  "content_type": "text",
  "content": "Hola",
  "conversation": {
    "additional_attributes": {},
    "can_reply": true,
    "channel": "Channel::Api",
    "contact_inbox": {
      "id": 54,
      "contact_id": 26,
      "inbox_id": 3,
      "source_id": "2ef52e3f-3dfe-4b14-9a84-4cb8b8d0d7cd",
      "created_at": "2026-02-16T15:07:27.104Z",
      "updated_at": "2026-02-16T15:07:27.104Z",
      "hmac_verified": false,
      "pubsub_token": "BufhrGRWt9eGW7u7HZzcVQDd"
    },
    "id": 10,
    "inbox_id": 3,
    "messages": [
      {
        "id": 684,
        "content": "Hola",
        "account_id": 1,
        "inbox_id": 3,
        "conversation_id": 10,
        "message_type": 0,
        "created_at": 1771373419,
        "updated_at": "2026-02-18T00:10:19.676Z",
        "private": false,
        "status": "sent",
        "source_id": "WAID:AC0EF0EB816E7470A21671ADD3851E56",
        "content_type": "text",
        "content_attributes": {},
        "sender_type": "Contact",
        "sender_id": 26,
        "external_source_ids": {},
        "additional_attributes": {},
        "processed_message_content": "Hola",
        "sentiment": {},
        "conversation": {
          "assignee_id": null,
          "unread_count": 1,
          "last_activity_at": 1771373419,
          "contact_inbox": {
            "source_id": "2ef52e3f-3dfe-4b14-9a84-4cb8b8d0d7cd"
          }
        },
        "sender": {
          "additional_attributes": {},
          "custom_attributes": {},
          "email": null,
          "id": 26,
          "identifier": "5491131376731@s.whatsapp.net",
          "name": "Leandro",
          "phone_number": "+5491131376731",
          "thumbnail": "",
          "blocked": false,
          "type": "contact"
        }
      }
    ],
    "labels": [],
    "meta": {
      "sender": {
        "additional_attributes": {},
        "custom_attributes": {},
        "email": null,
        "id": 26,
        "identifier": "5491131376731@s.whatsapp.net",
        "name": "Leandro",
        "phone_number": "+5491131376731",
        "thumbnail": "",
        "blocked": false,
        "type": "contact"
      },
      "assignee": null,
      "team": null,
      "hmac_verified": false
    },
    "status": "pending",
    "custom_attributes": {},
    "snoozed_until": null,
    "unread_count": 1,
    "first_reply_created_at": "2026-02-16T15:07:28.416Z",
    "priority": null,
    "waiting_since": 0,
    "agent_last_seen_at": 1771351339,
    "contact_last_seen_at": 1771351338,
    "last_activity_at": 1771373419,
    "timestamp": 1771373419,
    "created_at": 1771254447,
    "updated_at": 1771373419.6795785
  },
  "created_at": "2026-02-18T00:10:19.676Z",
  "id": 684,
  "inbox": { "id": 3, "name": "SisnovaWS" },
  "message_type": "incoming",
  "private": false,
  "sender": {
    "account": { "id": 1, "name": "cliente1" },
    "additional_attributes": {},
    "avatar": "",
    "custom_attributes": {},
    "email": null,
    "id": 26,
    "identifier": "5491131376731@s.whatsapp.net",
    "name": "Leandro",
    "phone_number": "+5491131376731",
    "thumbnail": "",
    "blocked": false
  },
  "source_id": "WAID:AC0EF0EB816E7470A21671ADD3851E56",
  "event": "message_created"
}
```