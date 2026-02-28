#!/usr/bin/env python3
"""
Script de prueba para enviar documento PDF vía Evolution API.
"""

import sys
import os

# Agregar el directorio al path para importar módulos locales
sys.path.insert(0, os.path.dirname(__file__))

from app import enviar_documento_whatsapp

def test_enviar_documento():
    """
    Prueba el envío de documento usando base64.
    """
    
    # Configuración
    NUMERO_DESTINO = "5491131376731@s.whatsapp.net"  # Tu número de prueba
    NOMBRE_INSTANCIA = "cliente2"  # Tu instancia
    
    print("📄 Test: Envío de documento PDF")
    print(f"   Destino: {NUMERO_DESTINO}")
    print(f"   Instancia: {NOMBRE_INSTANCIA}")
    print()
    
    # Cargar el base64 del archivo
    with open('documento_prueba_base64.txt', 'r') as f:
        lines = f.readlines()
        # Saltar las líneas de comentario que empiezan con #
        base64_content = ''.join([line for line in lines if not line.startswith('#')]).strip()
    
    print(f"✅ Base64 cargado: {len(base64_content)} caracteres")
    print(f"   Primeros 50: {base64_content[:50]}...")
    print()
    
    # Opción 1: Enviar usando URL (si tienes el PDF alojado)
    # documento_url = "https://ejemplo.com/documento.pdf"
    # resultado = enviar_documento_whatsapp(NUMERO_DESTINO, documento_url, NOMBRE_INSTANCIA)
    
    # Opción 2: Modificar la función para soportar base64 directamente
    # (requiere ajustar app.py para soportar base64)
    
    print("💡 NOTA: La función actual espera una URL.")
    print("   Para enviar base64, necesitas:")
    print("   1. Subir el PDF a un servidor web público, O")
    print("   2. Modificar enviar_documento_whatsapp() para soportar base64 directamente")
    print()
    print("📋 Base64 del documento:")
    print(base64_content)
    print()
    print("🔧 Payload Evolution API para envío con base64:")
    print("""
    POST /message/sendMedia/{instance}
    {
        "number": "5491131376731",
        "mediatype": "document",
        "mimetype": "application/pdf",
        "caption": "Documento de prueba generado por SisAgent",
        "fileName": "documento_prueba.pdf",
        "media": "data:application/pdf;base64,<BASE64_AQUI>"
    }
    """)


if __name__ == "__main__":
    test_enviar_documento()
