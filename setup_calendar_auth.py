#!/usr/bin/env python3
"""
Script para realizar la primera autenticación con Google Calendar.
Debe ejecutarse MANUALMENTE antes de iniciar el agente en background.
"""

import os
import pickle
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

def setup_calendar_auth():
    """Configura la autenticación de Google Calendar interactivamente"""
    
    print("=" * 60)
    print("CONFIGURACIÓN DE AUTENTICACIÓN GOOGLE CALENDAR")
    print("=" * 60)
    print()
    
    # Verificar que existe credentials.json
    if not os.path.exists('credentials.json'):
        print("❌ ERROR: No se encontró 'credentials.json'")
        print()
        print("Pasos para obtener credentials.json:")
        print("1. Ve a https://console.cloud.google.com/apis/credentials")
        print("2. Crea 'ID de cliente de OAuth 2.0'")
        print("3. ⚠️  IMPORTANTE: Selecciona 'Aplicación de escritorio' (NO web)")
        print("4. Descarga el JSON y guárdalo aquí como 'credentials.json'")
        print()
        print("Nota: Si usas 'Aplicación web', verás errores de redirect_uri.")
        print()
        return False
    
    print("✅ Encontrado: credentials.json")
    
    # Verificar si ya existe token.pickle
    if os.path.exists('token.pickle'):
        print("⚠️  Ya existe token.pickle")
        response = input("¿Quieres reautenticar? (s/N): ").strip().lower()
        if response != 's':
            print("Autenticación cancelada.")
            return True
        os.remove('token.pickle')
        print("Token anterior eliminado.")
    
    print()
    print("Iniciando flujo de autenticación...")
    print("Se abrirá tu navegador. Inicia sesión y autoriza la aplicación.")
    print()
    
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json', SCOPES)
        # Puerto 8099 configurado para OAuth
        creds = flow.run_local_server(port=8099)
        
        # Guardar credenciales
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
        
        print()
        print("=" * 60)
        print("✅ AUTENTICACIÓN EXITOSA")
        print("=" * 60)
        print()
        print("El archivo token.pickle ha sido creado.")
        print("Ahora puedes iniciar el agente con:")
        print("  ./venv/bin/python agent.py")
        print()
        
        # Probar acceso al calendario
        service = build('calendar', 'v3', credentials=creds)
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        
        print(f"📅 Calendarios accesibles: {len(calendars)}")
        for cal in calendars[:3]:
            print(f"  - {cal['summary']}")
        
        return True
        
    except Exception as e:
        print("=" * 60)
        print("❌ ERROR EN AUTENTICACIÓN")
        print("=" * 60)
        print(f"Error: {e}")
        print()
        print("Posibles causas y soluciones:")
        print()
        print("1. ⚠️  Error 403: access_denied")
        print("   Causa: App en modo Testing sin tu email en usuarios de prueba")
        print("   Solución:")
        print("   a) Ve a https://console.cloud.google.com/apis/credentials/consent")
        print("   b) En 'Test users' → '+ ADD USERS' → Agrega tu email")
        print("   O publicar la app: 'PUBLISH APP' (no requiere verificación)")
        print()
        print("2. ⚠️  Credenciales creadas como 'Aplicación web'")
        print("   Solución: Crea nuevas como 'Aplicación de escritorio'")
        print("   https://console.cloud.google.com/apis/credentials")
        print()
        print("3. Puerto ocupado")
        print("   Solución: pkill -f run_local_server")
        print()
        return False

if __name__ == '__main__':
    import sys
    success = setup_calendar_auth()
    sys.exit(0 if success else 1)
