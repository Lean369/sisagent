import os
import shutil
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

#Steps:

#1)- source .venv/bin/activate o .\.venv\Scripts\activate
#2)- python ingest_knowledge.py --reset

# 1. Cargar variables de entorno (.env)
# Esto es CRÍTICO porque el script corre fuera de Flask
load_dotenv()

# Configuración
DOCS_PATH = os.path.join(os.path.dirname(__file__), "documentos_negocio")
DB_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")

def cargar_documentos():
    """Lee todos los PDF y CSV del directorio."""
    docs = []
    if not os.path.exists(DOCS_PATH):
        os.makedirs(DOCS_PATH)
        print(f"⚠️ Carpeta '{DOCS_PATH}' creada. Pon tus archivos ahí.")
        return []

    print(f"📂 Escaneando: {DOCS_PATH}")
    for filename in os.listdir(DOCS_PATH):
        file_path = os.path.join(DOCS_PATH, filename)
        
        if filename.endswith(".pdf"):
            print(f"   - Leyendo PDF: {filename}")
            loader = PyPDFLoader(file_path)
            docs.extend(loader.load())
            
        elif filename.endswith(".csv"):
            print(f"   - Leyendo CSV: {filename}")
            # Ajusta los argumentos del CSV según tu formato
            loader = CSVLoader(file_path, csv_args={'delimiter': ',', 'quotechar': '"'})
            docs.extend(loader.load())
            
    return docs

def ingest_data(reset_db=False):
    # 2. Limpieza Opcional (Borrar DB vieja)
    if reset_db and os.path.exists(DB_PATH):
        print(f"🗑️ Eliminando base de datos anterior en {DB_PATH}...")
        shutil.rmtree(DB_PATH)

    # 3. Cargar y Procesar
    raw_docs = cargar_documentos()
    if not raw_docs:
        print("❌ No hay documentos para procesar.")
        return

    # 4. Dividir en Chunks (Fragmentos)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        add_start_index=True
    )
    splits = text_splitter.split_documents(raw_docs)
    print(f"🧩 Se generaron {len(splits)} fragmentos de información.")

    # 5. Indexar (Crear Embeddings)
    # Asegúrate de tener OPENAI_API_KEY en tu .env
    embedding_function = OpenAIEmbeddings(model="text-embedding-3-small")

    print("💾 Guardando en ChromaDB vector store...")
    Chroma.from_documents(
        documents=splits,
        embedding=embedding_function,
        persist_directory=DB_PATH
    )
    print("✅ ¡Ingesta completada! Tu bot ahora es más inteligente.")

# --- PUNTO DE ENTRADA PRINCIPAL ---
if __name__ == "__main__":
    import argparse
    
    # Permitir argumentos desde la consola
    parser = argparse.ArgumentParser(description="Script de Ingesta de Datos para el Bot")
    parser.add_argument("--reset", action="store_true", help="Borra la DB existente antes de ingestar")
    
    args = parser.parse_args()
    
    ingest_data(reset_db=args.reset)