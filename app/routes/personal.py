"""CRUD de personal vigilante + vigencias SUCAMEC (Fase 4.2)."""
import logging
import os
from datetime import datetime, date
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
from app.config import TIPOS_VIGENCIA, HAB_HABILITADO, HAB_ATENCION, HAB_NO_HABILITADO

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


def _solo_digitos(s: str) -> str:
    return ''.join(ch for ch in (s or '') if ch.isdigit())


@router.get('/personal')
async def listar(request: Request, error: str = '', ok: str = ''):
    personal = db_rrhh.listar_personal(solo_activos=True)
    # Adjuntar estado de habilitacion a cada trabajador (para el semaforo)
    for t in personal:
        t['_hab'] = db_rrhh.estado_habilitacion(t['dni'])
    stats = db_rrhh.stats_personal()
    return templates.TemplateResponse(
        request=request,
        name='personal_list.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'personal': personal,
            'stats': stats,
            'error': error,
            'ok': ok,
            'HAB_HABILITADO': HAB_HABILITADO,
            'HAB_ATENCION': HAB_ATENCION,
            'HAB_NO_HABILITADO': HAB_NO_HABILITADO,
        },
    )


@router.get('/personal/nuevo')
async def form_nuevo(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='personal_form.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'trabajador': None,
        },
    )


@router.post('/personal/nuevo')
async def crear(
    request: Request,
    dni: str = Form(...),
    apellido_paterno: str = Form(''),
    apellido_materno: str = Form(''),
    nombres: str = Form(''),
    fecha_nacimiento: str = Form(''),
    sexo: str = Form(''),
    telefono: str = Form(''),
    email: str = Form(''),
    direccion: str = Form(''),
    fecha_ingreso: str = Form(''),
    cargo_base: str = Form(''),
    foto_url: str = Form(''),
    observaciones: str = Form(''),
):
    session = request.state.session
    dni_clean = _solo_digitos(dni)
    if len(dni_clean) < 8:
        return RedirectResponse(
            f'/personal/nuevo?error={quote("DNI invalido (8 digitos).")}', status_code=303)

    nombre_completo = ' '.join(
        p for p in [apellido_paterno.strip(), apellido_materno.strip(), nombres.strip()] if p
    ).strip() or dni_clean

    try:
        db_rrhh.crear_trabajador(
            dni=dni_clean,
            nombre_completo=nombre_completo,
            apellido_paterno=apellido_paterno.strip() or None,
            apellido_materno=apellido_materno.strip() or None,
            nombres=nombres.strip() or None,
            fecha_nacimiento=_parse_date(fecha_nacimiento),
            sexo=(sexo.strip().upper()[:1] or None),
            telefono=telefono.strip() or None,
            email=email.strip() or None,
            direccion=direccion.strip() or None,
            fecha_ingreso=_parse_date(fecha_ingreso),
            cargo_base=cargo_base.strip() or None,
            foto_url=foto_url.strip() or None,
            observaciones=observaciones.strip() or None,
        )
    except _UNIQUE_EXC:
        return RedirectResponse(
            f'/personal?error={quote(f"Ya existe un trabajador con DNI {dni_clean}.")}',
            status_code=303)
    return RedirectResponse(f'/personal/{dni_clean}', status_code=303)


@router.get('/personal/{dni}')
async def detalle(request: Request, dni: str, error: str = '', ok: str = ''):
    trabajador = db_rrhh.get_trabajador(dni)
    if not trabajador:
        raise HTTPException(status_code=404, detail='Trabajador no existe')
    vigencias = {v['tipo']: v for v in db_rrhh.listar_vigencias(dni)}
    hab = db_rrhh.estado_habilitacion(dni)
    return templates.TemplateResponse(
        request=request,
        name='personal_detalle.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'trabajador': trabajador,
            'vigencias': vigencias,
            'tipos_vigencia': TIPOS_VIGENCIA,
            'hab': hab,
            'hoy': date.today(),
            'error': error,
            'ok': ok,
            'HAB_HABILITADO': HAB_HABILITADO,
            'HAB_ATENCION': HAB_ATENCION,
            'HAB_NO_HABILITADO': HAB_NO_HABILITADO,
        },
    )


@router.get('/personal/{dni}/editar')
async def form_editar(request: Request, dni: str):
    trabajador = db_rrhh.get_trabajador(dni)
    if not trabajador:
        raise HTTPException(status_code=404, detail='Trabajador no existe')
    return templates.TemplateResponse(
        request=request,
        name='personal_form.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'trabajador': trabajador,
        },
    )


@router.post('/personal/{dni}/editar')
async def editar(
    request: Request,
    dni: str,
    apellido_paterno: str = Form(''),
    apellido_materno: str = Form(''),
    nombres: str = Form(''),
    fecha_nacimiento: str = Form(''),
    sexo: str = Form(''),
    telefono: str = Form(''),
    email: str = Form(''),
    direccion: str = Form(''),
    fecha_ingreso: str = Form(''),
    cargo_base: str = Form(''),
    foto_url: str = Form(''),
    observaciones: str = Form(''),
):
    if not db_rrhh.get_trabajador(dni):
        raise HTTPException(status_code=404, detail='Trabajador no existe')
    nombre_completo = ' '.join(
        p for p in [apellido_paterno.strip(), apellido_materno.strip(), nombres.strip()] if p
    ).strip() or dni
    db_rrhh.actualizar_trabajador(
        dni,
        nombre_completo=nombre_completo,
        apellido_paterno=apellido_paterno.strip() or None,
        apellido_materno=apellido_materno.strip() or None,
        nombres=nombres.strip() or None,
        fecha_nacimiento=_parse_date(fecha_nacimiento),
        sexo=(sexo.strip().upper()[:1] or None),
        telefono=telefono.strip() or None,
        email=email.strip() or None,
        direccion=direccion.strip() or None,
        fecha_ingreso=_parse_date(fecha_ingreso),
        cargo_base=cargo_base.strip() or None,
        foto_url=foto_url.strip() or None,
        observaciones=observaciones.strip() or None,
    )
    return RedirectResponse(f'/personal/{dni}?ok={quote("Datos actualizados.")}', status_code=303)


@router.post('/personal/{dni}/baja')
async def dar_baja(request: Request, dni: str, fecha_salida: str = Form('')):
    if not db_rrhh.get_trabajador(dni):
        raise HTTPException(status_code=404, detail='Trabajador no existe')
    fs = _parse_date(fecha_salida) or datetime.now().date()
    db_rrhh.actualizar_trabajador(dni, fecha_salida=fs)
    return RedirectResponse(f'/personal?ok={quote("Trabajador dado de baja.")}', status_code=303)


# ── Vigencias ──────────────────────────────────────────────────

@router.post('/personal/{dni}/vigencias')
async def guardar_vigencia(
    request: Request,
    dni: str,
    tipo: str = Form(...),
    numero_doc: str = Form(''),
    entidad_emisora: str = Form(''),
    fecha_emision: str = Form(''),
    fecha_vencimiento: str = Form(''),
    archivo_pdf_url: str = Form(''),
    observaciones: str = Form(''),
):
    session = request.state.session
    if not db_rrhh.get_trabajador(dni):
        raise HTTPException(status_code=404, detail='Trabajador no existe')
    tipos_validos = {c for c, _, _, _ in TIPOS_VIGENCIA}
    if tipo not in tipos_validos:
        return RedirectResponse(
            f'/personal/{dni}?error={quote("Tipo de vigencia invalido.")}', status_code=303)
    db_rrhh.upsert_vigencia(
        dni=dni,
        tipo=tipo,
        numero_doc=numero_doc.strip() or None,
        entidad_emisora=entidad_emisora.strip() or None,
        fecha_emision=_parse_date(fecha_emision),
        fecha_vencimiento=_parse_date(fecha_vencimiento),
        archivo_pdf_url=archivo_pdf_url.strip() or None,
        observaciones=observaciones.strip() or None,
        creada_por=session.get('usuario_id'),
    )
    return RedirectResponse(
        f'/personal/{dni}?ok={quote("Vigencia guardada.")}', status_code=303)


@router.post('/personal/{dni}/vigencias/{vigencia_id}/eliminar')
async def eliminar_vigencia(request: Request, dni: str, vigencia_id: int):
    db_rrhh.eliminar_vigencia(vigencia_id)
    return RedirectResponse(
        f'/personal/{dni}?ok={quote("Vigencia eliminada.")}', status_code=303)
