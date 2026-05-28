"""CRUD cartas fianza."""
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services import database_rrhh as db_rrhh
from app.config import BANCOS_FIANZA, UIT_VIGENTE, CARTA_FIANZA_MIN_SOLES, ANIO_UIT

logger = logging.getLogger(__name__)
router = APIRouter()

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(APP_DIR, 'templates'))


def _parse_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), '%Y-%m-%d').date()
    except Exception:
        return None


def _parse_float(s: str, default: float = 0.0):
    if not s:
        return default
    try:
        return float(str(s).replace(',', '').strip())
    except Exception:
        return default


@router.get('/cartas-fianza')
async def listar(request: Request):
    session = request.state.session
    proyecto = request.state.proyecto_activo
    fianzas = db_rrhh.listar_fianzas()
    return templates.TemplateResponse(
        request=request,
        name='fianzas_list.html',
        context={
            'session': session,
            'proyecto_activo': proyecto,
            'fianzas': fianzas,
            'uit_vigente': UIT_VIGENTE,
            'anio_uit': ANIO_UIT,
            'monto_minimo': CARTA_FIANZA_MIN_SOLES,
        },
    )


@router.get('/cartas-fianza/nueva')
async def form_nueva(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='fianzas_form.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'fianza': None,
            'bancos': BANCOS_FIANZA,
            'uit_vigente': UIT_VIGENTE,
            'monto_minimo': CARTA_FIANZA_MIN_SOLES,
        },
    )


@router.post('/cartas-fianza/nueva')
async def crear(
    request: Request,
    banco: str = Form(...),
    monto: str = Form(...),
    fecha_emision: str = Form(...),
    fecha_vencimiento: str = Form(...),
    numero_carta: str = Form(''),
    moneda: str = Form('PEN'),
    uit_referencia: str = Form(''),
    num_uit: str = Form(''),
    archivo_pdf_url: str = Form(''),
    observaciones: str = Form(''),
):
    # FIX auditoria Opus 4.8 (P1-1): carta fianza es nivel EMPRESA, no
    # requiere proyecto activo.
    session = request.state.session

    fe = _parse_date(fecha_emision)
    fv = _parse_date(fecha_vencimiento)
    if not fe or not fv:
        raise HTTPException(status_code=400, detail='Fechas requeridas y validas')
    if fv <= fe:
        raise HTTPException(status_code=400, detail='Vencimiento debe ser posterior a emision')

    fid = db_rrhh.crear_fianza(
        banco=banco.strip(),
        numero_carta=numero_carta.strip() or None,
        monto=_parse_float(monto),
        moneda=moneda.strip().upper(),
        uit_referencia=_parse_float(uit_referencia) or None,
        num_uit=_parse_float(num_uit) or None,
        fecha_emision=fe,
        fecha_vencimiento=fv,
        archivo_pdf_url=archivo_pdf_url.strip() or None,
        observaciones=observaciones.strip() or None,
        creada_por=session.get('usuario_id'),
    )
    return RedirectResponse(f'/cartas-fianza/{fid}', status_code=303)


@router.get('/cartas-fianza/{fianza_id}')
async def detalle(request: Request, fianza_id: int):
    f = db_rrhh.get_fianza(fianza_id)
    if not f:
        raise HTTPException(status_code=404, detail='Carta fianza no existe')
    return templates.TemplateResponse(
        request=request,
        name='fianzas_form.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'fianza': f,
            'bancos': BANCOS_FIANZA,
            'uit_vigente': UIT_VIGENTE,
            'monto_minimo': CARTA_FIANZA_MIN_SOLES,
        },
    )


@router.post('/cartas-fianza/{fianza_id}/editar')
async def editar(
    request: Request,
    fianza_id: int,
    banco: str = Form(...),
    monto: str = Form(...),
    fecha_emision: str = Form(...),
    fecha_vencimiento: str = Form(...),
    numero_carta: str = Form(''),
    moneda: str = Form('PEN'),
    uit_referencia: str = Form(''),
    num_uit: str = Form(''),
    archivo_pdf_url: str = Form(''),
    observaciones: str = Form(''),
    estado: str = Form('vigente'),
):
    f = db_rrhh.get_fianza(fianza_id)
    if not f:
        raise HTTPException(status_code=404, detail='Carta fianza no existe')

    fe = _parse_date(fecha_emision)
    fv = _parse_date(fecha_vencimiento)
    if not fe or not fv:
        raise HTTPException(status_code=400, detail='Fechas requeridas y validas')

    db_rrhh.actualizar_fianza(
        fianza_id,
        banco=banco.strip(),
        numero_carta=numero_carta.strip() or None,
        monto=_parse_float(monto),
        moneda=moneda.strip().upper(),
        uit_referencia=_parse_float(uit_referencia) or None,
        num_uit=_parse_float(num_uit) or None,
        fecha_emision=fe,
        fecha_vencimiento=fv,
        archivo_pdf_url=archivo_pdf_url.strip() or None,
        observaciones=observaciones.strip() or None,
        estado=estado.strip().lower(),
    )
    return RedirectResponse(f'/cartas-fianza/{fianza_id}', status_code=303)
