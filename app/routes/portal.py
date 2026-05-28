"""Portal/dashboard del sistema RRHH: semaforo compliance + vencimientos."""
import logging
import os
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.services import database_rrhh as db_rrhh
from app.config import UIT_VIGENTE, CARTA_FIANZA_MIN_SOLES, ANIO_UIT

logger = logging.getLogger(__name__)
router = APIRouter()

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(APP_DIR, 'templates'))


@router.get('/')
async def portal(request: Request):
    session = request.state.session
    proyecto = request.state.proyecto_activo
    proyecto_id = proyecto['id'] if proyecto else None

    stats = db_rrhh.stats_compliance(proyecto_id=proyecto_id)
    # FIX auditoria Opus 4.8: pasar proyecto_id para no filtrar vencimientos
    # de otros proyectos/contratos (fuga cross-tenant).
    vencimientos = db_rrhh.vencimientos_proximos(dias_horizonte=90, proyecto_id=proyecto_id)

    # Calcular semaforo global
    vencidos = stats['modalidades']['vencidas'] + stats['fianzas']['vencidas']
    por_vencer = stats['modalidades']['por_vencer'] + stats['fianzas']['por_vencer']

    if vencidos > 0:
        semaforo = 'rojo'
        semaforo_texto = f'{vencidos} item(s) vencido(s)'
    elif por_vencer > 0:
        semaforo = 'ambar'
        semaforo_texto = f'{por_vencer} item(s) por vencer (60d)'
    else:
        semaforo = 'verde'
        semaforo_texto = 'Todo vigente'

    # Saludo segun hora Peru
    hora_peru = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-5))).hour
    if hora_peru < 6:
        saludo = 'Madrugada'
    elif hora_peru < 12:
        saludo = 'Buenos dias'
    elif hora_peru < 19:
        saludo = 'Buenas tardes'
    else:
        saludo = 'Buenas noches'

    return templates.TemplateResponse(
        request=request,
        name='portal.html',
        context={
            'session': session,
            'proyecto_activo': proyecto,
            'stats': stats,
            'vencimientos': vencimientos[:10],  # top 10
            'vencimientos_total': len(vencimientos),
            'semaforo': semaforo,
            'semaforo_texto': semaforo_texto,
            'saludo': saludo,
            'uit_vigente': UIT_VIGENTE,
            'anio_uit': ANIO_UIT,
            'fianza_min_soles': CARTA_FIANZA_MIN_SOLES,
        },
    )
