import os
from app import create_app
from loguru import logger

app = create_app()

logger.info("✅ App Flask iniciada.")

if __name__ == "__main__":
    # Flask es WSGI, no ASGI - usar app.run() directamente
    try:
        app.run(
            host='0.0.0.0',
            port=int(os.getenv('APP_PORT', 5000)),
            threaded=True,  # Importante para manejar concurrencia
            debug=False
        )
    except Exception as e:
        logger.exception(f"🔴 Error iniciando Flask: {e}")


# En producción, es recomendable usar Gunicorn con workers y threads configurados para manejar la concurrencia de manera eficiente:
# gunicorn -w 4 --threads 10 -b 0.0.0.0:5000 app:app
    #finally:
        # Detener scheduler al cerrar la aplicación
        # if scheduler:
        #     scheduler.shutdown()
        #     logger.info("🔴 🟢 y 🟡, o 🟩 y 🟨, o ✅ y ⚠️Scheduler detenido")
