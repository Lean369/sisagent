import os
from dotenv import load_dotenv

# 1. Cargamos el entorno tal como lo hace tu app
load_dotenv()

print("--- REPORTE DE DIAGNÓSTICO GOOGLE ---")

# Chequeo 1: ¿Existe la variable maldita dentro de Python?
# (Aunque no salga en printenv, puede estar aquí)
creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
creds_custom = os.environ.get("GOOGLE_CREDENTIALS_FILE")

if creds:
    print(f"[PELIGRO] GOOGLE_APPLICATION_CREDENTIALS detectada: {creds}")
    print("-> CAUSA DEL ERROR: Esta variable está forzando a LangChain a usar Vertex.")
else:
    print("[OK] GOOGLE_APPLICATION_CREDENTIALS no detectada.")

if creds_custom:
    print(f"[AVISO] GOOGLE_CREDENTIALS_FILE detectada: {creds_custom}")

# Chequeo 2: ¿Tenemos API Key?
api_key = os.environ.get("GOOGLE_API_KEY")

if api_key:
    # Mostramos solo los primeros 4 caracteres por seguridad
    print(f"[OK] GOOGLE_API_KEY detectada: {api_key[:4]}...")
else:
    print("[ERROR CRÍTICO] NO se detectó GOOGLE_API_KEY.")
    print("-> CAUSA DEL ERROR: Sin API Key, Google intenta conectarse como Enterprise (Vertex).")

# Chequeo 3: Prueba de Importación
print("\n--- PRUEBA DE IMPORTACIÓN ---")
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    print("[OK] Importación de ChatGoogleGenerativeAI exitosa.")
    
    # Intentamos instanciar (sin llamar a la API aún)
    llm = ChatGoogleGenerativeAI(google_api_key=api_key or "test", model="gemini-pro")
    print("[OK] Instanciación exitosa.")
    
except ImportError:
    print("[ERROR] Falló la importación. ¿Está instalado langchain-google-genai?")
except Exception as e:
    print(f"[ERROR] Error al instanciar: {e}")