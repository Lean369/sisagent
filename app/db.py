from psycopg_pool import ConnectionPool
import os
from loguru import logger

_pool = None

def init_db(app):
    global _pool

    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_NAME = os.getenv('DB_NAME_AGENT', 'checkpointer_db')
    DB_USER = os.getenv('DB_USER', 'sisbot_user')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres_password')
    DB_PORT = os.getenv('DB_PORT', '5432')

    DB_URI = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    _pool = ConnectionPool(
        conninfo=DB_URI,
        min_size=1,
        max_size=20,
        kwargs={"autocommit": True},
        reconnect_timeout=30,
        max_waiting=20,
    )

    logger.info("✅ Pool de conexiones a la base de datos inicializado correctamente.")

def get_pool():
    return _pool