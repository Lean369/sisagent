#!/usr/bin/env python3
"""
Script para generar un PDF de prueba y convertirlo a base64.
Útil para testing de envío de documentos vía Evolution API.
"""

import base64
import io
from datetime import datetime

def crear_pdf_simple():
    """Crea un PDF simple sin dependencias externas usando estructura PDF básica."""
    
    # Estructura básica de un PDF
    pdf_content = f"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj

2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj

3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Resources <<
/Font <<
/F1 <<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
>>
>>
>>
endobj

4 0 obj
<<
/Length 200
>>
stream
BT
/F1 24 Tf
50 700 Td
(Documento de Prueba) Tj
0 -40 Td
/F1 14 Tf
(Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) Tj
0 -30 Td
(Este es un PDF de prueba para Evolution API) Tj
0 -30 Td
(Sistema: SisAgent - WhatsApp Bot) Tj
ET
endstream
endobj

xref
0 5
0000000000 65535 f 
0000000015 00000 n 
0000000074 00000 n 
0000000131 00000 n 
0000000311 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
563
%%EOF
"""
    
    return pdf_content.encode('latin-1')


def main():
    print("🔧 Generando documento PDF de prueba...")
    
    # Crear PDF
    pdf_bytes = crear_pdf_simple()
    print(f"✅ PDF generado: {len(pdf_bytes)} bytes")
    
    # Convertir a base64
    pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
    print(f"✅ Convertido a base64: {len(pdf_base64)} caracteres")
    
    # Guardar en archivo de texto
    output_file = "documento_prueba_base64.txt"
    with open(output_file, 'w') as f:
        f.write("# Documento PDF de prueba en Base64\n")
        f.write("# Generado: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + "\n")
        f.write("# Uso: Copiar el contenido base64 y usar en Evolution API\n\n")
        f.write(pdf_base64)
    
    print(f"✅ Guardado en: {output_file}")
    
    # También guardar el PDF binario
    pdf_binary_file = "documento_prueba.pdf"
    with open(pdf_binary_file, 'wb') as f:
        f.write(pdf_bytes)
    
    print(f"✅ PDF binario guardado en: {pdf_binary_file}")
    
    # Mostrar primeros 100 caracteres del base64
    print("\n📋 Primeros 100 caracteres del base64:")
    print(pdf_base64[:100] + "...")
    
    print("\n🎯 Para usar en Evolution API:")
    print(f"   - Leer el archivo: {output_file}")
    print(f"   - O usar directamente el PDF: {pdf_binary_file}")
    print("\n💡 Ejemplo de payload para Evolution API:")
    print("""
    {
        "number": "5491131376731",
        "mediaMessage": {
            "mediatype": "document",
            "fileName": "documento_prueba.pdf",
            "media": "<BASE64_AQUI>"
        }
    }
    """)


if __name__ == "__main__":
    main()
