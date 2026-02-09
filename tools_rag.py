from langchain.tools import tool
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from loguru import logger

# Configuración (debe coincidir con el script de ingesta)
DB_PATH = "./chroma_db"
embedding_function = OpenAIEmbeddings(model="text-embedding-3-small")

# Cargamos la DB en memoria (lazy loading es mejor, pero esto sirve para demo)
vector_store = Chroma(persist_directory=DB_PATH, embedding_function=embedding_function)


@tool
def consultar_base_conocimiento(pregunta: str, business_id: str) -> str:
    """
    Útil para responder preguntas sobre productos, precios, políticas, manuales 
    o información específica del negocio que NO está en el prompt del sistema.
    """
    try:
        # 1. Buscamos los 3 fragmentos más parecidos a la pregunta
        resultados = vector_store.similarity_search(pregunta, k=3)
        
        if not resultados:
            return "No encontré información relevante en la base de conocimientos."

        # 2. Concatenamos el texto encontrado
        contexto = "\n\n".join([doc.page_content for doc in resultados])

        logger.info(f"🔍 Base de Conocimiento:  '{contexto}'")

        return f"Información encontrada en la base de datos:\n{contexto}"

    except Exception as e:
        return f"Error consultando base de conocimientos: {str(e)}"