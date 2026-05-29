"""Planilla DL 728 + SCTR (Fase 4.4): periodos, cálculo, boletas."""
import logging
import os
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import database_rrhh as db_rrhh
from app.services.database_rrhh import ReglaPlanilla
from app.services.planilla_calc import MESES_ES
from app.config import planilla_params, RMV

logger = logging.getLogger(__name__)
router = APIRouter()

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(APP_DIR, 'templates'))


def _int(s, default=None):
    try:
        return int(str(s).strip())
    except Exception:
        return default


@router.get('/planilla')
async def listar(request: Request, error: str = '', ok: str = ''):
    periodos = db_rrhh.listar_periodos_planilla()
    for p in periodos:
        p['_mes_nombre'] = MESES_ES[p['mes']] if 1 <= p['mes'] <= 12 else p['mes']
        p['_tot'] = db_rrhh.totales_planilla(p['id'])
    hoy = datetime.now()
    return templates.TemplateResponse(
        request=request, name='planilla_list.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'periodos': periodos, 'meses': MESES_ES,
            'anio_actual': hoy.year, 'mes_actual': hoy.month,
            'params': planilla_params(), 'rmv': RMV,
            'error': error, 'ok': ok,
        },
    )


@router.post('/planilla/generar')
async def generar(request: Request, anio: str = Form(...), mes: str = Form(...)):
    session = request.state.session
    a, m = _int(anio), _int(mes)
    if not a or not m:
        return RedirectResponse(f'/planilla?error={quote("Periodo inválido.")}', status_code=303)
    try:
        periodo_id = db_rrhh.calcular_periodo_planilla(
            anio=a, mes=m, calculado_por=session.get('usuario_id'))
    except ReglaPlanilla as e:
        return RedirectResponse(f'/planilla?error={quote(str(e))}', status_code=303)
    return RedirectResponse(f'/planilla/{periodo_id}?ok={quote("Planilla calculada.")}', status_code=303)


@router.get('/planilla/{periodo_id}')
async def detalle(request: Request, periodo_id: int):
    periodo = db_rrhh.get_periodo_planilla(periodo_id)
    if not periodo:
        raise HTTPException(status_code=404, detail='Periodo no existe')
    boletas = db_rrhh.detalle_planilla(periodo_id)
    totales = db_rrhh.totales_planilla(periodo_id)
    return templates.TemplateResponse(
        request=request, name='planilla_periodo.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'periodo': periodo, 'boletas': boletas, 'totales': totales,
            'mes_nombre': MESES_ES[periodo['mes']] if 1 <= periodo['mes'] <= 12 else periodo['mes'],
        },
    )


@router.get('/planilla/boleta/{detalle_id}')
async def boleta(request: Request, detalle_id: int):
    b = db_rrhh.get_boleta(detalle_id)
    if not b:
        raise HTTPException(status_code=404, detail='Boleta no existe')
    return templates.TemplateResponse(
        request=request, name='boleta.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'b': b,
            'mes_nombre': MESES_ES[b['mes']] if 1 <= b['mes'] <= 12 else b['mes'],
        },
    )
