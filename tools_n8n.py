import requests
from langchain_core.tools import tool
import os
from dotenv import load_dotenv

load_dotenv(override=True)
URL_WEBHOOK_N8N = os.getenv("URL_WEBHOOK_N8N", "http://localhost:5678/webhook/tu_webhook_aqui")

@tool
def invoke_n8n(nombre: str, telefono: str) -> str:
    """
    Útil para crear un nuevo cliente potencial o lead.
    Usa esta herramienta cuando el usuario quiera registrarse.
    """

    try:
        # Hacemos el request HTTP tradicional
        respuesta = requests.post(URL_WEBHOOK_N8N, json={
            "nombre": nombre,
            "telefono": telefono
        }, timeout=10) # Siempre usa timeouts!
        
        # Le devolvemos el resultado al LLM
        if respuesta.status_code == 200:
            return f"Éxito: {respuesta.text}"
        else:
            return f"Error en n8n: {respuesta.status_code}"
            
    except Exception as e:
        return f"Error de conexión con n8n: {e}"