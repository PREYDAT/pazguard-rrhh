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

    # FIX auditoria Opus 4.8 (P1-1): modalidades y carta fianza son nivel
    # EMPRESA (una autorizacion SUCAMEC, una fianza para toda la operacion),
    # no por proyecto/contrato. Por eso stats y vencimientos NO se filtran por
    # proyecto. Las vigencias de PERSONAL (Fase 4.2) si seran por proyecto.
    stats = db_rrhh.stats_compliance()
    stats_personal = db_rrhh.stats_personal()
    vencimientos = db_rrhh.vencimientos_proximos(dias_horizonte=90)

    # Semaforo global. Distingue documentos vencidos (modalidad/fianza) de
    # personal no habilitado, para que el texto sea preciso (compliance).
    docs_vencidos = stats['modalidades']['vencidas'] + stats['fianzas']['vencidas']
    docs_por_vencer = stats['modalidades']['por_vencer'] + stats['fianzas']['por_vencer']
    no_habilitados = stats_personal['no_habilitados']
    personal_atencion = stats_personal['atencion']

    if docs_vencidos > 0 or no_habilitados > 0:
        semaforo = 'rojo'
        partes = []
        if docs_vencidos:
            partes.append(f'{docs_vencidos} documento(s) vencido(s)')
        if no_habilitados:
            partes.append(f'{no_habilitados} vigilante(s) NO habilitado(s)')
        semaforo_texto = ' · '.join(partes)
    elif docs_por_vencer > 0 or personal_atencion > 0:
        semaforo = 'ambar'
        partes = []
        if docs_por_vencer:
            partes.append(f'{docs_por_vencer} por vencer (60d)')
        if personal_atencion:
            partes.append(f'{personal_atencion} vigilante(s) en atención')
        semaforo_texto = ' · '.join(partes)
    else:
        semaforo = 'verde'
        semaforo_texto = 'Todo vigente y habilitado'

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
            'stats_personal': stats_personal,
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
