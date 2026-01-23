import os
from datetime import datetime, timedelta
from typing import Dict, List
from fastapi import FastAPI, Request
import logging
import httpx
import requests
from langchain_anthropic import ChatAnthropic
from langchain_community.llms import HuggingFaceHub
from langchain_community.chat_models import ChatHuggingFace
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
import pickle
import json
from dotenv import load_dotenv

# Importar prompts personalizados
try:
    from prompts import AGENT_INSTRUCTION, SESSION_INSTRUCTION
    USE_FRIDAY_PROMPTS = False
except ImportError:
    USE_FRIDAY_PROMPTS = False
    AGENT_INSTRUCTION = ""
    SESSION_INSTRUCTION = ""

# Cargar variables de entorno
load_dotenv()

# Configuración
app = FastAPI()
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "your_api_key")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "default")
EVOLUTION_INSTANCE_ID = os.getenv("EVOLUTION_INSTANCE_ID", "")

# Configuración del LLM - Elige uno de estos proveedores
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # opciones: gemini, anthropic, huggingface, openai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "your_gemini_key")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "your_anthropic_key")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "your_hf_key")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_openai_key")

# Límite de mensajes en memoria por conversación
MAX_MESSAGES_PER_CONVERSATION = int(os.getenv("MAX_MESSAGES", "50"))  # Límite de mensajes en memoria

# Scopes para Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Almacenamiento simple de memoria por usuario
user_memories: Dict[str, Dict] = {}

# Configurar logging más verboso para el agente
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('agent_verbose.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('python-agent')


def get_calendar_service():
    """Autentica y retorna el servicio de Google Calendar"""
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    
    return build('calendar', 'v3', credentials=creds)


def agendar_cita(titulo: str, fecha: str, hora: str, duracion_minutos: int = 60, descripcion: str = "") -> str:
    """
    Agenda una cita en Google Calendar
    
    Args:
        titulo: Título del evento
        fecha: Fecha en formato YYYY-MM-DD
        hora: Hora en formato HH:MM
        duracion_minutos: Duración en minutos (default 60)
        descripcion: Descripción del evento
    
    Returns:
        Mensaje de confirmación o error
    """
    try:
        service = get_calendar_service()
        
        # Parsear fecha y hora
        inicio = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
        fin = inicio + timedelta(minutes=duracion_minutos)
        
        evento = {
            'summary': titulo,
            'description': descripcion,
            'start': {
                'dateTime': inicio.isoformat(),
                'timeZone': 'America/Argentina/Buenos_Aires',
            },
            'end': {
                'dateTime': fin.isoformat(),
                'timeZone': 'America/Argentina/Buenos_Aires',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 30},
                ],
            },
        }
        
        evento_creado = service.events().insert(calendarId='primary', body=evento).execute()
        
        return f"✅ Cita agendada exitosamente para {fecha} a las {hora}. ID: {evento_creado.get('id')}"
    
    except Exception as e:
        return f"❌ Error al agendar la cita: {str(e)}"


async def enviar_mensaje_whatsapp(numero: str, mensaje: str, instance_id: str = None, instance_name: str = None):
    """Envía un mensaje a través de Evolution API.

    Intentará varios identificadores en orden: `instance_id` (UUID), `instance_name` (friendly name),
    y finalmente la configuración `EVOLUTION_INSTANCE_ID`/`EVOLUTION_INSTANCE` desde el entorno.
    Devuelve el JSON de respuesta en caso de éxito o el dict con status/text en error.
    """
    headers = {
        "Content-Type": "application/json",
        "apikey": EVOLUTION_API_KEY
    }
    payload = {
        "number": numero,
        "text": mensaje
    }

    # Construir lista de candidatos para probar
    candidates = []
    if instance_id:
        candidates.append(str(instance_id))
    if instance_name:
        candidates.append(str(instance_name))
    # Añadir configuración desde entorno como último recurso
    if EVOLUTION_INSTANCE_ID:
        candidates.append(str(EVOLUTION_INSTANCE_ID))
    if EVOLUTION_INSTANCE and EVOLUTION_INSTANCE not in candidates:
        candidates.append(str(EVOLUTION_INSTANCE))

    # Deduplicate preserving order
    seen = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    async with httpx.AsyncClient(verify=False) as client:
        for candidate in candidates:
            url = f"{EVOLUTION_API_URL}/message/sendText/{candidate}"
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)
                status = response.status_code
                # Log full body for non-2xx to help debugging
                text = None
                try:
                    text = response.json()
                except Exception:
                    text = response.text

                logger.debug("Tried sendText with candidate=%s status=%s response=%s", candidate, status, text)

                if 200 <= status < 300:
                    return text
                # Continue trying next candidate on 4xx/5xx
            except Exception as e:
                logger.exception("Exception when sending with candidate %s: %s", candidate, e)

    # If none succeeded, return an informative structure
    logger.error("All sendText attempts failed for number=%s; tried=%s", numero, candidates)
    return {"status": "failed", "tried": candidates}


def get_memory(user_id: str):
    """Obtiene o crea memoria para un usuario"""
    logger.debug("get_memory called for user_id=%s", user_id)
    if user_id not in user_memories:
        # Intentar usar ConversationBufferMemory si está disponible
        try:
            from langchain.memory import ConversationBufferMemory
            user_memories[user_id] = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True
            )
        except Exception:
            # Fallback simple: almacenar mensajes en memoria con la misma API mínima
            class _SimpleChatMemory:
                def __init__(self):
                    self.messages: List = []

                def add_user_message(self, text: str):
                    self.messages.append(HumanMessage(content=text))

                def add_ai_message(self, text: str):
                    self.messages.append(AIMessage(content=text))

            class _SimpleMemory:
                def __init__(self):
                    self.chat_memory = _SimpleChatMemory()

            user_memories[user_id] = _SimpleMemory()
            logger.debug("Created simple in-memory conversation memory for user_id=%s", user_id)

    return user_memories[user_id]


def truncate_memory(memory) -> None:
    """
    Trunca la memoria para mantener solo los últimos MAX_MESSAGES_PER_CONVERSATION mensajes.
    Modifica la memoria in-place.
    """
    try:
        current_count = len(memory.chat_memory.messages)
        if current_count > MAX_MESSAGES_PER_CONVERSATION:
            # Mantener solo los últimos N mensajes
            memory.chat_memory.messages = memory.chat_memory.messages[-MAX_MESSAGES_PER_CONVERSATION:]
            logger.info(
                f"Truncated memory: {current_count} → {MAX_MESSAGES_PER_CONVERSATION} messages"
            )
    except Exception as e:
        logger.warning(f"Failed to truncate memory: {e}")


def crear_agente():
    """Crea el LLM para el agente"""
    # Seleccionar modelo de lenguaje según el proveedor
    llm = get_llm_model()
    logger.debug("LLM instance created: %s", type(llm).__name__)
    return llm


def get_llm_model():
    """Retorna el modelo LLM según la configuración"""
    provider = LLM_PROVIDER.lower()
    logger.debug("Configuring LLM provider: %s", provider)
    
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        logger.debug("Using Google Gemini")
        return ChatGoogleGenerativeAI(
            model="gemini-3-flash-preview",
            google_api_key=GEMINI_API_KEY,
            temperature=0.8,
            max_tokens=512,
        )
    
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=ANTHROPIC_API_KEY,
            temperature=0.7
        )
    
    elif provider == "huggingface":
        # Usar HuggingFace Inference API con chat_completion
        model_id = os.getenv("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        logger.debug("Using HuggingFace API for model %s", model_id)
        
        from huggingface_hub import InferenceClient
        
        # Wrapper para HuggingFace con chat_completion
        class HFChatWrapper:
            def __init__(self, model, token):
                self.model = model
                self.client = InferenceClient(token=token)
            
            def invoke(self, messages: List):
                # Convertir mensajes al formato de HuggingFace
                hf_messages = []
                for m in messages:
                    role = type(m).__name__
                    if role == 'SystemMessage':
                        hf_messages.append({"role": "system", "content": m.content})
                    elif role == 'HumanMessage':
                        hf_messages.append({"role": "user", "content": m.content})
                    elif role == 'AIMessage':
                        hf_messages.append({"role": "assistant", "content": m.content})
                
                try:
                    response = self.client.chat_completion(
                        messages=hf_messages,
                        model=self.model,
                        max_tokens=512,
                        temperature=0.7,
                    )
                    content = response.choices[0].message.content
                    return type("Resp", (), {"content": content})()
                except Exception as e:
                    logger.error(f"Error calling HuggingFace: {e}")
                    return type("Resp", (), {"content": "Lo siento, hubo un error al procesar tu solicitud."})()
        
        return HFChatWrapper(model_id, HUGGINGFACE_API_KEY)
    
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4"),
            api_key=OPENAI_API_KEY,
            temperature=0.7
        )
    
    elif provider == "ollama":
        # Para modelos locales con Ollama
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=os.getenv("OLLAMA_MODEL", "llama2"),
            base_url=os.getenv("OLLAMA_URL", "http://localhost:11434")
        )
    
    elif provider == "local_huggingface":
        # Opción 2: Modelo local de HuggingFace (requiere más recursos)
        from langchain_community.llms import HuggingFacePipeline
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
        
        model_id = os.getenv("HF_LOCAL_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            device_map="auto",
            load_in_8bit=True  # Reduce uso de memoria
        )
        
        pipe = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=512,
            temperature=0.7,
            top_p=0.95,
            repetition_penalty=1.15
        )
        
        return HuggingFacePipeline(pipeline=pipe)
    
    else:
        raise ValueError(f"Proveedor LLM no soportado: {provider}")



# Instancia global del agente
agente = crear_agente()


@app.post("/webhook")
async def webhook(request: Request):
    """Endpoint para recibir webhooks de Evolution API"""
    try:
        payload = await request.json()
        logger.info("Received webhook payload: %s", json.dumps(payload)[:500])
        
        # Extraer información del mensaje
        if payload.get('event') == 'messages.upsert':
            mensaje_data = payload.get('data', {})
            mensaje = mensaje_data.get('message', {}).get('conversation') or \
                     mensaje_data.get('message', {}).get('extendedTextMessage', {}).get('text', '')
            
            remitente = mensaje_data.get('key', {}).get('remoteJid', '')
            from_me = mensaje_data.get('key', {}).get('fromMe', False)
            # Intentar obtener instance/id proporcionado en el webhook
            webhook_instance = payload.get('instance') or mensaje_data.get('instanceId') or None
            
            if mensaje and remitente and not from_me:
                logger.info("Processing message from %s: %s", remitente, mensaje)
                # Procesar mensaje
                respuesta = procesar_mensaje(remitente, mensaje)
                
                # Enviar respuesta (pasando la instancia recibida para intentar usarla)
                await enviar_mensaje_whatsapp(remitente, respuesta, instance_id=webhook_instance, instance_name=payload.get('instance'))
        
        # Soporte alternativo para formato con lista de mensajes
        for msg in payload.get("messages", []):
            if msg.get("type") == "conversation":
                from_jid = msg["key"]["remoteJid"]
                text = msg["message"]["conversation"]
                from_me = msg["key"].get("fromMe", False)
                
                if text and from_jid and not from_me:
                    logger.info("Processing message from %s: %s", from_jid, text)
                    respuesta = procesar_mensaje(from_jid, text)
                    # If the msg contains instance info, prefer it
                    msg_instance = msg.get('instance') or msg.get('instanceId')
                    await enviar_mensaje_whatsapp(from_jid, respuesta, instance_id=msg_instance, instance_name=msg.get('instance'))
        
        return {"status": "success"}
    
    except Exception as e:
        logger.exception("Error en webhook: %s", e)
        return {"status": "error", "message": str(e)}


def procesar_mensaje(user_id: str, mensaje: str) -> str:
    """Procesa un mensaje usando el LLM"""
    try:
        # Obtener memoria del usuario
        memory = get_memory(user_id)
        
        # Detectar si es el primer mensaje (saludo inicial)
        is_first_message = len(memory.chat_memory.messages) == 0
        
        # Crear sistema de prompt
        if USE_FRIDAY_PROMPTS:
            # Usar prompt personalizado de Friday
            system_prompt = f"""{AGENT_INSTRUCTION}

# Capabilities
You can help with:
- Natural conversations
- Scheduling appointments in Google Calendar (ask for title, date YYYY-MM-DD, time HH:MM, duration in minutes)
- Remembering conversation context

Today's date is {datetime.now().strftime("%Y-%m-%d")}.

If the user wants to schedule an appointment and provides all necessary information, respond with a JSON:
{{"accion": "agendar", "titulo": "...", "fecha": "YYYY-MM-DD", "hora": "HH:MM", "duracion": 60, "descripcion": "..."}}

{SESSION_INSTRUCTION if is_first_message else ''}"""
        else:
            # Prompt por defecto
            system_prompt = f"""Eres un asistente virtual amigable que ayuda a los usuarios a gestionar sus citas.

Puedes:
- Mantener conversaciones naturales
- Agendar citas en Google Calendar (pregunta por título, fecha YYYY-MM-DD, hora HH:MM, duración en minutos)
- Recordar el contexto de la conversación

La fecha de hoy es {datetime.now().strftime("%Y-%m-%d")}.

Si el usuario quiere agendar una cita y proporciona toda la información necesaria, responde con un JSON:
{{"accion": "agendar", "titulo": "...", "fecha": "YYYY-MM-DD", "hora": "HH:MM", "duracion": 60, "descripcion": "..."}}"""
        
        # Construir mensajes
        messages = [SystemMessage(content=system_prompt)]
        messages.extend(memory.chat_memory.messages)
        messages.append(HumanMessage(content=mensaje))
        
        # Invocar LLM
        respuesta_llm = agente.invoke(messages)
        respuesta = respuesta_llm.content
        
        # Verificar si es una acción de agendar
        if "accion" in respuesta and "agendar" in respuesta:
            try:
                datos = json.loads(respuesta)
                if datos.get("accion") == "agendar":
                    resultado = agendar_cita(
                        datos["titulo"],
                        datos["fecha"],
                        datos["hora"],
                        datos.get("duracion", 60),
                        datos.get("descripcion", "")
                    )
                    respuesta = resultado
            except json.JSONDecodeError:
                pass
        
        # Guardar en memoria
        memory.chat_memory.add_user_message(mensaje)
        memory.chat_memory.add_ai_message(respuesta)
        
        # Truncar memoria si excede el límite
        truncate_memory(memory)
        
        return respuesta
    
    except Exception as e:
        print(f"Error procesando mensaje: {e}")
        import traceback
        traceback.print_exc()
        return "Lo siento, ocurrió un error al procesar tu mensaje. Por favor intenta de nuevo."


@app.get("/health")
async def health():
    """Endpoint de salud"""
    return {"status": "ok"}


@app.get("/memory")
async def memory_index():
    """Lista los user_ids en memoria y la cantidad de mensajes guardados por cada uno."""
    result = {}
    for uid, mem in user_memories.items():
        try:
            count = len(mem.chat_memory.messages)
        except Exception:
            # Soporte para otras implementaciones de memoria
            try:
                count = len(mem.chat_memory._get_messages())
            except Exception:
                count = 0
        result[uid] = count
    return result


@app.get("/memory/{user_id}")
async def memory_detail(user_id: str):
    """Devuelve detalle de la memoria para un usuario: conteo y los últimos 10 mensajes."""
    mem = user_memories.get(user_id)
    if not mem:
        return {"user_id": user_id, "count": 0, "messages": []}

    msgs = []
    try:
        # Intentar leer la lista estándar creada en el fallback
        raw = mem.chat_memory.messages
        for m in raw[-20:]:
            role = type(m).__name__
            msgs.append({"role": role, "content": getattr(m, 'content', str(m))})
    except Exception:
        try:
            # Intento alternativo para ConversationBufferMemory
            raw = mem.load_memory_variables({}).get('chat_history', [])
            for m in raw[-20:]:
                msgs.append({"role": type(m).__name__, "content": getattr(m, 'content', str(m))})
        except Exception:
            msgs = []

    return {"user_id": user_id, "count": len(msgs), "messages": msgs}


if __name__ == '__main__':
    import uvicorn
    print("🤖 Iniciando chatbot con LangChain...")
    print(f"🧠 Usando LLM: {LLM_PROVIDER}")
    print(f"🔑 Instance ID: {EVOLUTION_INSTANCE_ID or EVOLUTION_INSTANCE}")
    print("📅 Herramienta de Google Calendar configurada")
    print("💬 Esperando mensajes de Evolution API...")
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")