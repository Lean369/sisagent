import os
import json
import uuid
import logging
import requests
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

from agent_metrics import metricas_db

# Logger compartido
logger = logging.getLogger(os.getenv('LOGGER_NAME', 'agent'))

webhooks_bp = Blueprint('webhooks', __name__)


def _get_monitoring_config():
    url = os.getenv('MONITORING_WEBHOOK_URL', '').strip()
    enabled = bool(url)
    interval = int(os.getenv('MONITORING_WEBHOOK_INTERVAL_MINUTES', '60'))
    mode = os.getenv('MONITORING_WEBHOOK_MODE', 'pull').strip().lower()
    return url, enabled, interval, mode


def enviar_metricas_a_webhook(usar_mes_actual: bool = False, horas: int = None) -> dict:
    MONITORING_WEBHOOK_URL, MONITORING_WEBHOOK_ENABLED, MONITORING_WEBHOOK_INTERVAL_MINUTES, MONITORING_WEBHOOK_MODE = _get_monitoring_config()

    if not MONITORING_WEBHOOK_ENABLED:
        return {"error": "Webhook de monitoreo no configurado", "enabled": False}

    try:
        if MONITORING_WEBHOOK_MODE == 'push':
            logger.info("⏸️  Modo 'push' activo: no se enviarán métricas salientes desde el agente")
            return {"success": False, "error": "agent_in_push_mode", "message": "El agente está en modo 'push' y no envía métricas salientes"}

        if usar_mes_actual:
            now = datetime.now()
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                end_of_month = now.replace(year=now.year+1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                end_of_month = now.replace(month=now.month+1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end_of_month = end_of_month - timedelta(seconds=1)
            start_iso = start_of_month.isoformat()
            end_iso = end_of_month.isoformat()
            stats_general = metricas_db.obtener_estadisticas_por_rango(start_iso, end_iso)
            stats_hourly = metricas_db.obtener_metricas_por_hora_rango(start_iso, end_iso)
            periodo_str = f"mes_{now.strftime('%Y-%m')}"
            logger.debug(f"[WEBHOOK] Enviando métricas del mes en curso: {start_iso} a {end_iso}")
        else:
            if horas is None:
                horas = 24
            stats_general = metricas_db.obtener_estadisticas_generales(horas)
            stats_hourly = metricas_db.obtener_metricas_por_hora(horas)
            periodo_str = f"{horas}h"
            logger.debug(f"[WEBHOOK] Enviando métricas de las últimas {horas} horas")

        top_users = metricas_db.obtener_top_usuarios(limit=10)

        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "source": "sisagent",
            "stats_general": stats_general,
            "stats_hourly": stats_hourly,
            "top_users": top_users,
            "periodo": periodo_str
        }

        response = requests.post(
            MONITORING_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        if response.status_code in [200, 201, 202, 204]:
            logger.info(f"✅ Métricas enviadas al webhook de monitoreo: status={response.status_code} periodo={periodo_str}")
            return {"success": True, "status_code": response.status_code, "webhook_url": MONITORING_WEBHOOK_URL, "periodo": periodo_str}
        else:
            logger.warning(f"⚠️  Webhook respondió con status {response.status_code}: {response.text[:200]}")
            return {"success": False, "status_code": response.status_code, "error": response.text[:500]}

    except requests.exceptions.Timeout:
        logger.error("❌ Timeout al enviar métricas al webhook de monitoreo")
        return {"success": False, "error": "Timeout (>10s)"}
    except Exception as e:
        logger.exception(f"❌ Error enviando métricas al webhook: {e}")
        return {"success": False, "error": str(e)}


@webhooks_bp.route('/admin/metrics/webhook', methods=['POST'])
def trigger_monitoring_webhook():
    usar_mes_actual = request.args.get('mes_actual', 'false').lower() == 'true'
    horas = request.args.get('horas', type=int) if not usar_mes_actual else None
    try:
        resultado = enviar_metricas_a_webhook(usar_mes_actual=usar_mes_actual, horas=horas)
        status_code = 200 if resultado.get('success') else 500
        return jsonify(resultado), status_code
    except Exception as e:
        logger.exception("Error al disparar webhook de monitoreo")
        return jsonify({"error": str(e)}), 500


@webhooks_bp.route('/monitoring/push', methods=['POST'])
def monitoring_push_receiver():
    push_token_cfg = os.getenv('MONITORING_PUSH_TOKEN', '').strip()
    if push_token_cfg:
        incoming_token = request.headers.get('X-MONITORING-TOKEN', '')
        if incoming_token != push_token_cfg:
            logger.warning("Intento de push con token inválido")
            return jsonify({"error": "invalid_token"}), 401

    try:
        payload = request.get_json(force=True)
    except Exception as e:
        logger.warning(f"Payload inválido en monitoring/push: {e}")
        return jsonify({"error": "invalid_json", "details": str(e)}), 400

    try:
        dirpath = os.path.join('logs', 'monitoring_received')
        os.makedirs(dirpath, exist_ok=True)
        filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex}.json"
        filepath = os.path.join(dirpath, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({'received_at': datetime.utcnow().isoformat(), 'source': request.remote_addr, 'payload': payload}, f, ensure_ascii=False, indent=2)

        logger.info(f"📥 Monitoring push recibido y guardado en {filepath}")
        return jsonify({"accepted": True, "stored_at": filepath}), 200
    except Exception as e:
        logger.exception(f"Error guardando payload recibido en monitoring/push: {e}")
        return jsonify({"error": "storage_failed", "details": str(e)}), 500


def iniciar_scheduler_webhook():
    _, MONITORING_WEBHOOK_ENABLED, MONITORING_WEBHOOK_INTERVAL_MINUTES, MONITORING_WEBHOOK_MODE = _get_monitoring_config()

    if MONITORING_WEBHOOK_MODE == 'push':
        logger.info("Scheduler omitido: el agente está en modo 'push' y no inicia envíos automáticos")
        return None

    if not MONITORING_WEBHOOK_ENABLED:
        logger.info("⏸️  Scheduler de webhook no iniciado (webhook deshabilitado)")
        return None

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BackgroundScheduler()
    scheduler.add_job(func=lambda: enviar_metricas_a_webhook(usar_mes_actual=True), trigger=IntervalTrigger(minutes=MONITORING_WEBHOOK_INTERVAL_MINUTES), id='webhook_metricas_mes', name='Envío automático de métricas del mes al webhook', replace_existing=True)
    scheduler.start()
    logger.info(f"✅ Scheduler iniciado: enviará métricas del mes cada {MONITORING_WEBHOOK_INTERVAL_MINUTES} minutos")
    return scheduler
