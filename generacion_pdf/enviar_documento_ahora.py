#!/usr/bin/env python3
"""
Script DIRECTO para enviar el documento PDF generado.
Este script importa la función actualizada y envía el documento.
"""

import sys
import os

# Agregar el directorio al path
sys.path.insert(0, os.path.dirname(__file__))

# NO importar app completo, solo lo necesario
from evolutionapi.client import EvolutionClient
from loguru import logger

def enviar_documento_directo():
    """Envía el documento de prueba usando Evolution API directamente."""
    
    # Configuración
    EVOLUTION_URL = os.environ.get("EVOLUTION_API_URL", "https://evoapi.sisnova.com.ar")
    EVOLUTION_API_KEY = os.environ.get("EVOLUTION_API_KEY")
    NUMERO_DESTINO = "5491131376731"  # Sin @s.whatsapp.net
    NOMBRE_INSTANCIA = "cliente2"
    
    print("📄 Enviando documento PDF de prueba")
    print(f"   URL: {EVOLUTION_URL}")
    print(f"   Destino: {NUMERO_DESTINO}")
    print(f"   Instancia: {NOMBRE_INSTANCIA}")
    print()
    
    # Cargar el base64
    with open('documento_prueba_base64.txt', 'r') as f:
        lines = f.readlines()
        base64_content = ''.join([line for line in lines if not line.startswith('#')]).strip()
    
    print(f"✅ Base64 cargado: {len(base64_content)} caracteres")
    print()
    
    # Crear cliente
    client = EvolutionClient(base_url=EVOLUTION_URL, api_token=EVOLUTION_API_KEY)
    
    # Endpoint correcto para Baileys
    endpoint = f"message/sendMedia/{NOMBRE_INSTANCIA}"
    
    # Payload con base64
    payload = {
        "number": NUMERO_DESTINO,
        "mediatype": "document",
        "mimetype": "application/pdf",
        "caption": "📄 Documento de prueba generado por SisAgent",
        "fileName": "documento_prueba.pdf",
        "media": base64_content
    }
    
    print("📤 Enviando al API...")
    try:
        response = client.post(endpoint, data=payload)
        
        if response:
            print("✅ Respuesta recibida:")
            print(response)
            
            if isinstance(response, dict) and response.get("key"):
                print("🎉 ¡Documento enviado exitosamente!")
            else:
                print("⚠️ Respuesta sin 'key', revisar:")
                print(response)
        else:
            print("❌ No se recibió respuesta del API")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    enviar_documento_directo()
