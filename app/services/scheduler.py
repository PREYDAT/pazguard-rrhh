"""APScheduler para jobs diarios.

- 9am Peru (14 UTC): revisar vencimientos modalidades + fianzas, alertar Telegram.

Idempotente: cada (entidad, dias_restantes) genera 1 sola alerta gracias a
rrhh_alerta_enviada UNIQUE.
"""
import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import SCHEDULER_HORA_UTC, SCHEDULER_MINUTO, ALERTA_DIAS
from app.services import database_rrhh as db_rrhh
from app.services.telegram import enviar_mensaje

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def revisar_vencimientos_y_alertar():
    """Job diario: lista vencimientos proximos y notifica si toca escalon."""
    try:
        items = db_rrhh.vencimientos_proximos(dias_horizonte=120)
    except Exception as e:
        logger.warning(f"vencimientos_proximos fallo: {e}")
        return

    if not items:
        logger.info("No hay vencimientos en horizonte 120d. OK.")
        return

    enviados = 0
    omitidos = 0
    for item in items:
        d = item['dias_restantes']
        # Solo notificar en los escalones definidos
        if d not in ALERTA_DIAS and not (d < 0 and d % 7 == 0):
            # Si paso el vencimiento, alertar 1 vez por semana
            continue

        ya = db_rrhh.alerta_ya_enviada(item['tipo'], item['id'], d)
        if ya:
            omitidos += 1
            continue

        # Componer mensaje
        if d > 0:
            urgencia = '🟡' if d > 15 else '🟠' if d > 7 else '🔴'
            cuando = f"vence en <b>{d} dia(s)</b>"
        elif d == 0:
            urgencia = '🔴'
            cuando = '<b>VENCE HOY</b>'
        else:
            urgencia = '🚨'
            cuando = f'<b>VENCIDO hace {abs(d)} dia(s)</b>'

        texto = (
            f"{urgencia} <b>Alerta SUCAMEC/PAZGUARD</b>\n\n"
            f"{item['descripcion']}\n"
            f"{cuando}\n"
            f"Fecha vencimiento: {item['fecha_vencimiento'].strftime('%d/%m/%Y')}\n\n"
            f"<i>Sistema RRHH/SUCAMEC — Pazguard</i>"
        )

        ok = enviar_mensaje(texto)
        if ok:
            enviados += 1
            db_rrhh.registrar_alerta(item['tipo'], item['id'], d)
        else:
            logger.info(f"No se pudo enviar Telegram para {item['tipo']}#{item['id']}")

    logger.info(f"Job vencimientos: {enviados} enviados, {omitidos} ya estaban registrados")


def start_scheduler():
    """Arranca el scheduler si no esta corriendo."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone='UTC')
    trigger = CronTrigger(hour=SCHEDULER_HORA_UTC, minute=SCHEDULER_MINUTO)
    _scheduler.add_job(
        revisar_vencimientos_y_alertar,
        trigger=trigger,
        id='rrhh_alertas_diarias',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(
        f"Scheduler iniciado: revisar_vencimientos diario a las "
        f"{SCHEDULER_HORA_UTC:02d}:{SCHEDULER_MINUTO:02d} UTC"
    )


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
