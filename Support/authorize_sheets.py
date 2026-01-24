#!/usr/bin/env python3
"""
Script para autorizar Google Sheets manualmente
Ejecutar: python3 authorize_sheets.py
"""
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CREDENTIALS_FILE = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

def main():
    print("\n🔐 Autorización de Google Sheets")
    print("=" * 50)
    
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"\n❌ Error: No se encontró el archivo {CREDENTIALS_FILE}")
        print("Por favor, descarga las credenciales desde Google Cloud Console")
        return
    
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDENTIALS_FILE, SCOPES)
        
        print("\n📋 Instrucciones:")
        print("1. Se abrirá una ventana del navegador")
        print("2. Inicia sesión con tu cuenta de Google")
        print("3. Autoriza el acceso a Google Sheets")
        print("4. Cierra la ventana cuando veas el mensaje de éxito\n")
        
        input("Presiona Enter para continuar...")
        
        # Ejecutar flujo de autorización (puerto aleatorio para evitar conflictos)
        creds = flow.run_local_server(port=0, open_browser=True)
        
        # Guardar credenciales
        with open('sheets_token.pickle', 'wb') as token:
            pickle.dump(creds, token)
        
        print("\n✅ ¡Autorización exitosa!")
        print(f"✅ Token guardado en: sheets_token.pickle")
        print("\n📌 Próximos pasos:")
        print("1. Reinicia el agente: ./agent-manager.sh restart")
        print("2. Comparte tu hoja de Google Sheets con tu cuenta de Google")
        print("3. Prueba enviando un mensaje al bot\n")
        
    except Exception as e:
        print(f"\n❌ Error durante la autorización: {e}")
        print("\nPosibles soluciones:")
        print("- Verifica que el archivo credentials.json sea correcto")
        print("- Asegúrate de que Google Sheets API esté habilitada")
        print(f"- Error detallado: {e}")

if __name__ == "__main__":
    main()
