"""CRUD modalidades SUCAMEC."""
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

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
async def listar(request: Request):
    session = request.state.session
    proyecto = request.state.proyecto_activo
    proyecto_id = proyecto['id'] if proyecto else None
    modalidades = db_rrhh.listar_modalidades(proyecto_id=proyecto_id, solo_activas=False)
    return templates.TemplateResponse(
        request=request,
        name='modalidades_list.html',
        context={
            'session': session,
            'proyecto_activo': proyecto,
            'modalidades': modalidades,
            'catalogo': MODALIDADES_SUCAMEC,
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
    session = request.state.session
    proyecto = request.state.proyecto_activo
    if not proyecto:
        raise HTTPException(status_code=400, detail='Selecciona un proyecto antes')
    mid = db_rrhh.crear_modalidad(
        proyecto_id=proyecto['id'],
        codigo=codigo.strip().upper(),
        nombre=nombre.strip(),
        resolucion_sucamec=resolucion_sucamec.strip() or None,
        fecha_otorgamiento=_parse_date(fecha_otorgamiento),
        fecha_vencimiento=_parse_date(fecha_vencimiento),
        alcance_geografico=alcance_geografico.strip() or None,
        archivo_pdf_url=archivo_pdf_url.strip() or None,
        observaciones=observaciones.strip() or None,
        creada_por=session.get('usuario_id'),
    )
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
