"""CRUD modalidades SUCAMEC."""
import logging
import os
from datetime import datetime

from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

try:
    from psycopg import errors as pg_errors
    _UNIQUE_EXC = pg_errors.UniqueViolation
except Exception:  # pragma: no cover
    _UNIQUE_EXC = Exception

from app.services import database_rrhh as db_rrhh
from app.config import MODALIDADES_SUCAMEC

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


@router.get('/modalidades')
async def listar(request: Request, error: str = ''):
    session = request.state.session
    modalidades = db_rrhh.listar_modalidades(solo_activas=False)
    return templates.TemplateResponse(
        request=request,
        name='modalidades_list.html',
        context={
            'session': session,
            'proyecto_activo': request.state.proyecto_activo,
            'modalidades': modalidades,
            'catalogo': MODALIDADES_SUCAMEC,
            'error': error,
        },
    )


@router.get('/modalidades/nueva')
async def form_nueva(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='modalidades_form.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'modalidad': None,
            'catalogo': MODALIDADES_SUCAMEC,
        },
    )


@router.post('/modalidades/nueva')
async def crear(
    request: Request,
    codigo: str = Form(...),
    nombre: str = Form(...),
    resolucion_sucamec: str = Form(''),
    fecha_otorgamiento: str = Form(''),
    fecha_vencimiento: str = Form(''),
    alcance_geografico: str = Form(''),
    archivo_pdf_url: str = Form(''),
    observaciones: str = Form(''),
):
    # FIX auditoria Opus 4.8 (P1-1): modalidades son nivel EMPRESA, no
    # requieren proyecto activo. (P2-2): capturar duplicado con mensaje claro.
    session = request.state.session
    cod = codigo.strip().upper()
    try:
        mid = db_rrhh.crear_modalidad(
            codigo=cod,
            nombre=nombre.strip(),
            resolucion_sucamec=resolucion_sucamec.strip() or None,
            fecha_otorgamiento=_parse_date(fecha_otorgamiento),
            fecha_vencimiento=_parse_date(fecha_vencimiento),
            alcance_geografico=alcance_geografico.strip() or None,
            archivo_pdf_url=archivo_pdf_url.strip() or None,
            observaciones=observaciones.strip() or None,
            creada_por=session.get('usuario_id'),
        )
    except _UNIQUE_EXC:
        msg = quote(f'La modalidad "{cod}" ya esta registrada.')
        return RedirectResponse(f'/modalidades?error={msg}', status_code=303)
    return RedirectResponse(f'/modalidades/{mid}', status_code=303)


@router.get('/modalidades/{modalidad_id}')
async def detalle(request: Request, modalidad_id: int):
    m = db_rrhh.get_modalidad(modalidad_id)
    if not m:
        raise HTTPException(status_code=404, detail='Modalidad no existe')
    return templates.TemplateResponse(
        request=request,
        name='modalidades_form.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'modalidad': m,
            'catalogo': MODALIDADES_SUCAMEC,
        },
    )


@router.post('/modalidades/{modalidad_id}/editar')
async def editar(
    request: Request,
    modalidad_id: int,
    codigo: str = Form(...),
    nombre: str = Form(...),
    resolucion_sucamec: str = Form(''),
    fecha_otorgamiento: str = Form(''),
    fecha_vencimiento: str = Form(''),
    alcance_geografico: str = Form(''),
    archivo_pdf_url: str = Form(''),
    observaciones: str = Form(''),
    activa: str = Form('on'),
):
    m = db_rrhh.get_modalidad(modalidad_id)
    if not m:
        raise HTTPException(status_code=404, detail='Modalidad no existe')
    db_rrhh.actualizar_modalidad(
        modalidad_id,
        codigo=codigo.strip().upper(),
        nombre=nombre.strip(),
        resolucion_sucamec=resolucion_sucamec.strip() or None,
        fecha_otorgamiento=_parse_date(fecha_otorgamiento),
        fecha_vencimiento=_parse_date(fecha_vencimiento),
        alcance_geografico=alcance_geografico.strip() or None,
        archivo_pdf_url=archivo_pdf_url.strip() or None,
        observaciones=observaciones.strip() or None,
        activa=(activa.lower() == 'on'),
    )
    return RedirectResponse(f'/modalidades/{modalidad_id}', status_code=303)
