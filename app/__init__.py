from flask import Flask, request
from dotenv import load_dotenv
from loguru import logger
from .logger_config import inicializar_logger
from .db import init_db
import threading
import os
from .workers.instagram import worker_secuencial_instagram  
from .utils.utilities import get_app_configs

# Compat shim para Flask 3: exponer `Markup` en el módulo `flask` si falta
try:
    import flask as _flask_mod
    from markupsafe import Markup as _Markup
    if not hasattr(_flask_mod, 'Markup'):
        _flask_mod.Markup = _Markup
except Exception:
    pass

# Intentar importar Flasgger solo si está disponible y es compatible
try:
    from flasgger import Swagger
    _HAS_FLASGGER = True
except Exception:
    _HAS_FLASGGER = False
    # no inicializamos Swagger si la librería no está disponible o es incompatible


# 🚀 1. Inicializar el logger ANTES que el resto del sistema
inicializar_logger()

def create_app(config_object=None):
    # Load .env into environment so init_db can pick DB_HOST etc.
    load_dotenv()

    app = Flask(__name__, template_folder='templates', static_folder='static')
    
    # Initialize Swagger only if Flasgger is available and compatible
    if config_object:
        app.config.from_object(config_object)

    # inicializar DB/pools/servicios globales aquí
    init_db(app)

    #Obtengo las configuraciones de la app
    get_app_configs()

    if _HAS_FLASGGER:
        # Initialize Flasgger Swagger UI
        try:
            template = {
                "swagger": "2.0",
                "info": {"title": "Sisagent API", "version": "0.1"},
                "basePath": "/api",
                "schemes": ["http", "https"],
            }

            # Config mínima para Flasgger: necesita al menos una entrada en 'specs'
            swagger_config = {
                "specs": [
                    {
                        "endpoint": "apispec_1",
                        "route": "/apispec_1.json",
                        "rule_filter": (lambda rule: True),
                        "model_filter": (lambda tag: True),
                    }
                ],
                "static_url_path": "/flasgger_static",
                "headers": [],
                "specs_route": "/api/apidocs/",
            }

            Swagger(app, config=swagger_config, template=template)
        except Exception:
            # Si ocurre cualquier error en la inicialización de Swagger, lo ignoramos
            logger.warning("Flasgger initialization failed; continuing without Swagger")

    # registrar blueprints
    from .routes.frontend import frontend_bp
    from .routes.admin import admin_bp
    from .routes.chatwoot import chatwoot_bp
    from .routes.evolution import evolution_bp
    from .routes.instagram import instagram_bp
    from .routes.hitl_tool_enable import hitl_tool_enable_bp
    from .routes.meta_onboarding import meta_onboarding_bp
    from .routes.calendar import calendar_bp

    app.register_blueprint(frontend_bp, url_prefix='')
    app.register_blueprint(admin_bp, url_prefix='/api')
    app.register_blueprint(chatwoot_bp, url_prefix='')
    app.register_blueprint(evolution_bp, url_prefix='')
    app.register_blueprint(instagram_bp, url_prefix='')
    app.register_blueprint(hitl_tool_enable_bp, url_prefix='')
    app.register_blueprint(meta_onboarding_bp, url_prefix='')
    app.register_blueprint(calendar_bp, url_prefix='')

    # 3. Arrancar el Hilo Demonio junto con Flask para procesar tareas de contestación de comentarios de Instagram (si está habilitado)
    # 'daemon=True' asegura que el hilo muera automáticamente si apagas Flask
    # worker import ya presente arriba
    def _start_instagram_worker():
        hilo_ig = threading.Thread(target=worker_secuencial_instagram, daemon=True)
        hilo_ig.start()

    if os.getenv('WORKER_INSTAGRAM_ENABLED', 'false').lower() == 'true':
        if hasattr(app, "before_first_request"):
            logger.info("🚀 Instagram worker habilitado. Se iniciará en el primer request...")
            app.before_first_request(_start_instagram_worker)
        else:
            # Ejecutar inmediatamente sólo en el proceso principal (evita doble arranque con el reloader)
            if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
                logger.info("🚀 Instagram worker habilitado. Iniciando inmediatamente...")
                _start_instagram_worker()

    return app