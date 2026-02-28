#!/usr/bin/env python3
"""
Script de prueba para las herramientas de Google Calendar
"""
import json
from langchain_core.runnables import RunnableConfig

# Importar las herramientas sin ejecutar main()
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# No ejecutar main al importar
import tools_calendar

print("✅ Módulo tools_calendar importado correctamente\n")

# Probar la función agendar_cita_calendar
print("=" * 80)
print("TEST 1: Intentar agendar cita sin autenticación")
print("=" * 80)

config = RunnableConfig(configurable={"business_id": "test_cliente"})

resultado = tools_calendar.agendar_cita_calendar.invoke({
    "nombre": "Juan Pérez",
    "email": "juan@example.com",
    "fecha_hora_iso": "2026-03-01T15:00:00",
    "descripcion": "Consulta inicial"
}, config=config)

print("\n📊 Resultado:")
resultado_json = json.loads(resultado)
print(json.dumps(resultado_json, indent=2, ensure_ascii=False))

if resultado_json.get("status") == "auth_required":
    print("\n✅ TEST 1 PASADO: Se requiere autenticación y se devolvió la URL")
    print(f"🔗 URL de autorización: {resultado_json.get('auth_url')[:80]}...")
else:
    print("\n⚠️  RESULTADO INESPERADO")

print("\n" + "=" * 80)
print("✅ Todas las pruebas completadas")
print("=" * 80)
