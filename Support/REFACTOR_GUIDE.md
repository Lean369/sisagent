# Guía de Refactorización — Proyecto SisAgent

Objetivo
- Mejorar la mantenibilidad separando responsabilidades del monolito `app.py` en módulos y blueprints, manteniendo compatibilidad y permitiendo pruebas unitarias.

Estructura recomendada
```
project-root/
├── app/
│   ├── __init__.py          # create_app factory, blueprints registration
│   ├── config.py            # carga de configuración/entorno
│   ├── db.py                # wrapper ConnectionPool, init/get_pool
│   ├── routes/              # blueprints (dashboard, admin, webhooks, config)
│   │   ├── __init__.py
│   │   ├── dashboard.py
│   │   ├── admin.py
│   │   └── webhooks.py
│   ├── services/            # lógica de negocio y llamadas a DB/externos
│   │   ├── analytics.py
│   │   ├── tiendanube.py
│   │   └── notifications.py
│   ├── workers/             # workers en hilos o tasks separados
│   ├── utils/               # helpers, serializadores, validaciones
│   └── templates/
├── tools/                   # tools langchain u otras herramientas aisladas
├── scripts/                 # utilidades operacionales (backup, wipe)
├── tests/
├── Support/
│   └── REFACTOR_GUIDE.md    # este documento
└── .env                   
```

Principios de diseño
- Rutas delgadas (thin controllers): solo parseo de request/response y llamadas a servicios.
- Servicios: contienen la lógica pesada (SQL, transformaciones, llamadas externas).
- DB centralizada: `app.db` expone `init_db(app)` y `get_pool()` o similar.
- Blueprints por dominio para agrupar rutas relacionadas.
- Evitar imports circulares usando la factory `create_app()`.
- Pruebas: cada service tiene tests unitarios; los endpoints tienen tests de integración ligeros.

Pasos prácticos de migración (sugeridos, seguros)
1. Crear la estructura de carpetas (local):
```bash
mkdir -p app/{routes,services,workers,utils}
mkdir -p scripts tests
```

2. Añadir `app/__init__.py` (factory mínima):
```python
from flask import Flask

def create_app(config_object=None):
    app = Flask(__name__, template_folder='templates', static_folder='static')
    if config_object:
        app.config.from_object(config_object)

    # inicializar DB/pools/servicios globales aquí
    from .db import init_db
    init_db(app)

    # registrar blueprints
    from .routes.dashboard import dashboard_bp
    from .routes.admin import admin_bp
    app.register_blueprint(dashboard_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/admin')

    return app
```

3. Extraer y convertir el endpoint admin `wipe-analytics` a `app/routes/admin.py` como blueprint:
```python
from flask import Blueprint, request, jsonify
from ..db import get_pool
import os, logging
admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/wipe-analytics', methods=['POST'])
def wipe_analytics():
    admin_token = os.getenv('ADMIN_TOKEN','')
    if admin_token and request.headers.get('X-Admin-Token')!=admin_token:
        return jsonify({'error':'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    if data.get('confirm')!='I UNDERSTAND':
        return jsonify({'error':'Missing confirmation'}), 400
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute('TRUNCATE TABLE analytics_events RESTART IDENTITY CASCADE')
    return jsonify({'status':'ok'}), 200
```

4. Mover `analytics.py` a `app/services/analytics.py` y adaptar:
- Cambiar `registrar_evento(pool, ...)` a `registrar_evento(result, thread_id, ...)` y obtener pool con `from app.db import get_pool; pool = get_pool()` dentro de la función o pasar pool desde la inicialización.
- Mantener `cargar_pricing()` intacto en el service.

5. Extraer `get_dashboard` a `app/routes/dashboard.py` y delegar consultas SQL pesadas a `app/services/analytics.py` (funciones: `dashboard_summary(start,end,biz)` que retornen dict).

6. Mover workers (Instagram, audio) a `app/workers/*.py` y exponer una función `start_workers(app)` que `create_app()` llame si la variable `WORKER_INSTAGRAM_ENABLED` está activa.

7. DB: crear `app/db.py` con funciones:
```python
from psycopg_pool import ConnectionPool
_pool = None

def init_db(app):
    global _pool
    _pool = ConnectionPool(conninfo=app.config.get('DATABASE_URL'))

def get_pool():
    return _pool
```

8. Actualizar entrypoint (root `app.py` → `run.py` o `wsgi.py`):
```python
from app import create_app
app = create_app()
if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('APP_PORT', 5000)))
```

9. Tests rápidos (import smoke test):
```bash
.venv/bin/python -c "from app import create_app; app=create_app(); print('create-app-ok')"
```

10. Implementar `scripts/manage_db.py` para operaciones seguras de DB (backup + wipe) y preferir su uso en lugar de endpoints destructivos. Ejemplo breve:
```python
# scripts/manage_db.py
# usage: python manage_db.py --backup /tmp/backup.dump --wipe-analytics
```

Checklist de validación tras migración
- [ ] `create_app()` importa sin errores
- [ ] Todas las rutas principales funcionan (curl /health, /api/dashboard)
- [ ] Workers arrancan bajo flag de entorno
- [ ] Tests unitarios para `app/services/analytics.py` y `app/routes/admin.py`

Consideraciones operativas
- Mantener `ADMIN_TOKEN` y doble confirmación para acciones destructivas.
- Guardar backups automáticos antes de cualquier script de wipe (`pg_dump -Fc`).
- Añadir logging y auditoría para operaciones admin.
- Documentar en `Support/` cada cambio de estructura.

Siguiente paso que puedo hacer ahora
- Mover `analytics.py` → `app/services/analytics.py` y `wipe-analytics` → `app/routes/admin.py`, añadir `app/__init__.py` y ajustar el entrypoint; correr el smoke test.

---
*Generado automáticamente por el asistente — puedes pedirme que aplique la reestructuración paso a paso.*
