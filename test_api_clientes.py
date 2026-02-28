#!/usr/bin/env python3
"""
Script de prueba para los endpoints de gestión de clientes.
Ejecuta una serie de tests para verificar que los endpoints funcionan correctamente.
"""

import requests
import json
import sys
from colorama import Fore, Style, init

# Inicializar colorama
init(autoreset=True)

BASE_URL = "http://localhost:5000"
TEST_CLIENTE_ID = "test_cliente_temporal"

def print_success(msg):
    print(f"{Fore.GREEN}✅ {msg}{Style.RESET_ALL}")

def print_error(msg):
    print(f"{Fore.RED}❌ {msg}{Style.RESET_ALL}")

def print_info(msg):
    print(f"{Fore.CYAN}ℹ️  {msg}{Style.RESET_ALL}")

def print_header(msg):
    print(f"\n{Fore.YELLOW}{'='*60}")
    print(f"{msg}")
    print(f"{'='*60}{Style.RESET_ALL}\n")


def test_listar_clientes():
    """Test: GET /api/config/clientes"""
    print_info("Test 1: Listar todos los clientes")
    
    try:
        response = requests.get(f"{BASE_URL}/api/config/clientes")
        
        if response.status_code == 200:
            clientes = response.json()
            print_success(f"Clientes listados correctamente. Total: {len(clientes)}")
            print(f"  Clientes: {list(clientes.keys())}")
            return True
        else:
            print_error(f"Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False


def test_crear_cliente():
    """Test: POST /api/config/clientes"""
    print_info("Test 2: Crear nuevo cliente de prueba")
    
    nuevo_cliente = {
        "business_id": TEST_CLIENTE_ID,
        "nombre": "Test Store - Temporal",
        "ttl_sesion_minutos": 30,
        "admin_phone": "5491111111111",
        "system_prompt": ["Eres un asistente de prueba"],
        "tools_habilitadas": ["test_tool"]
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/config/clientes",
            json=nuevo_cliente
        )
        
        if response.status_code == 201:
            data = response.json()
            print_success(f"Cliente creado: {data['message']}")
            print(f"  Nombre: {data['data']['nombre']}")
            return True
        elif response.status_code == 409:
            print_info("Cliente ya existe (probablemente de una ejecución anterior)")
            return True
        else:
            print_error(f"Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False


def test_obtener_cliente():
    """Test: GET /api/config/clientes/<id>"""
    print_info("Test 3: Obtener cliente específico")
    
    try:
        response = requests.get(f"{BASE_URL}/api/config/clientes/{TEST_CLIENTE_ID}")
        
        if response.status_code == 200:
            cliente = response.json()
            print_success(f"Cliente obtenido correctamente")
            print(f"  Nombre: {cliente['nombre']}")
            print(f"  TTL: {cliente['ttl_sesion_minutos']} minutos")
            print(f"  Admin: {cliente['admin_phone']}")
            return True
        else:
            print_error(f"Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False


def test_actualizar_parcial():
    """Test: PATCH /api/config/clientes/<id>"""
    print_info("Test 4: Actualizar parcialmente (PATCH)")
    
    actualizaciones = {
        "nombre": "Test Store - Actualizado",
        "ttl_sesion_minutos": 45
    }
    
    try:
        response = requests.patch(
            f"{BASE_URL}/api/config/clientes/{TEST_CLIENTE_ID}",
            json=actualizaciones
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"Cliente actualizado: {data['message']}")
            print(f"  Campos actualizados: {data['updated_fields']}")
            print(f"  Nuevo nombre: {data['data']['nombre']}")
            return True
        else:
            print_error(f"Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False


def test_actualizar_completo():
    """Test: PUT /api/config/clientes/<id>"""
    print_info("Test 5: Actualizar completamente (PUT)")
    
    cliente_completo = {
        "nombre": "Test Store - PUT Update",
        "ttl_sesion_minutos": 60,
        "admin_phone": "5491122334455",
        "fuera_de_servicio": {
            "activo": True,
            "horario_inicio": "10:00",
            "horario_fin": "20:00",
            "dias_laborales": [1, 2, 3, 4, 5],
            "zona_horaria": "America/Argentina/Buenos_Aires",
            "mensaje": ["Test cerrado"]
        },
        "system_prompt": ["Soy un asistente de prueba actualizado"],
        "mensaje_HITL": "Derivando...",
        "mensaje_usuario_1": ["Hola desde PUT"],
        "tools_habilitadas": ["tool1", "tool2"]
    }
    
    try:
        response = requests.put(
            f"{BASE_URL}/api/config/clientes/{TEST_CLIENTE_ID}",
            json=cliente_completo
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"Cliente actualizado completamente")
            print(f"  Nuevo nombre: {data['data']['nombre']}")
            print(f"  Fuera de servicio: {data['data']['fuera_de_servicio']['activo']}")
            return True
        else:
            print_error(f"Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False


def test_eliminar_cliente():
    """Test: DELETE /api/config/clientes/<id>"""
    print_info("Test 6: Eliminar cliente de prueba")
    
    try:
        response = requests.delete(f"{BASE_URL}/api/config/clientes/{TEST_CLIENTE_ID}")
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"Cliente eliminado: {data['message']}")
            print(f"  Datos eliminados: {data['deleted_data']['nombre']}")
            return True
        else:
            print_error(f"Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False


def test_cliente_no_existe():
    """Test: Verificar respuesta 404 para cliente inexistente"""
    print_info("Test 7: Verificar respuesta 404 (cliente inexistente)")
    
    try:
        response = requests.get(f"{BASE_URL}/api/config/clientes/cliente_no_existe_999")
        
        if response.status_code == 404:
            print_success("Respuesta 404 correcta para cliente inexistente")
            return True
        else:
            print_error(f"Se esperaba 404, se recibió: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Excepción: {e}")
        return False


def main():
    print_header("🧪 TESTS DE API - GESTIÓN DE CLIENTES")
    
    # Verificar que el servidor esté corriendo
    try:
        response = requests.get(f"{BASE_URL}/api/metrics", timeout=2)
        print_success("Servidor Flask está corriendo")
    except:
        print_error(f"No se puede conectar al servidor en {BASE_URL}")
        print_info("Asegúrate de que el servidor Flask esté corriendo:")
        print("  python app.py")
        sys.exit(1)
    
    # Ejecutar tests
    tests = [
        ("Listar clientes", test_listar_clientes),
        ("Crear cliente", test_crear_cliente),
        ("Obtener cliente", test_obtener_cliente),
        ("Actualizar parcial", test_actualizar_parcial),
        ("Actualizar completo", test_actualizar_completo),
        ("Eliminar cliente", test_eliminar_cliente),
        ("Cliente no existe", test_cliente_no_existe),
    ]
    
    resultados = []
    
    for nombre, test_func in tests:
        resultado = test_func()
        resultados.append((nombre, resultado))
        print()
    
    # Resumen
    print_header("📊 RESUMEN DE TESTS")
    
    exitosos = sum(1 for _, r in resultados if r)
    total = len(resultados)
    
    for nombre, resultado in resultados:
        if resultado:
            print(f"{Fore.GREEN}✅{Style.RESET_ALL} {nombre}")
        else:
            print(f"{Fore.RED}❌{Style.RESET_ALL} {nombre}")
    
    print(f"\n{Fore.CYAN}Total: {exitosos}/{total} tests exitosos{Style.RESET_ALL}")
    
    if exitosos == total:
        print(f"\n{Fore.GREEN}🎉 Todos los tests pasaron correctamente!{Style.RESET_ALL}\n")
        return 0
    else:
        print(f"\n{Fore.RED}⚠️  Algunos tests fallaron{Style.RESET_ALL}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
