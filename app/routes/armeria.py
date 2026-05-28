"""Armería SUCAMEC (Fase 4.3): armas, asignación nominal, libro, munición, polvorín."""
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
from app.services.database_rrhh import ReglaArmeria
from app.config import (
    ARMA_ESTADOS, CALIBRES_COMUNES, MUNICION_MOV_TIPOS, MUNICION_MOV_DICT,
)

logger = logging.getLogger(__name__)
router = APIRouter()

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(APP_DIR, 'templates'))


def _d(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), '%Y-%m-%d').date()
    except Exception:
        return None


def _int(s, default=None):
    try:
        return int(str(s).strip())
    except Exception:
        return default


# ── Inventario de armas ───────────────────────────────────────

@router.get('/armeria')
async def listar(request: Request, error: str = '', ok: str = ''):
    armas = db_rrhh.listar_armas()
    stats = db_rrhh.stats_armeria()
    return templates.TemplateResponse(
        request=request, name='armeria_list.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'armas': armas, 'stats': stats, 'estados': ARMA_ESTADOS,
            'error': error, 'ok': ok,
        },
    )


@router.get('/armeria/nueva')
async def form_nueva(request: Request):
    return templates.TemplateResponse(
        request=request, name='arma_form.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'arma': None, 'estados': ARMA_ESTADOS, 'calibres': CALIBRES_COMUNES,
            'polvorines': db_rrhh.listar_polvorines(),
        },
    )


@router.post('/armeria/nueva')
async def crear(
    request: Request,
    marca: str = Form(''), modelo: str = Form(''), calibre: str = Form(''),
    serie: str = Form(''), anio: str = Form(''), tpa: str = Form(''),
    estado: str = Form('operativa'), fecha_adquisicion: str = Form(''),
    polvorin_id: str = Form(''), observaciones: str = Form(''),
):
    session = request.state.session
    try:
        arma_id = db_rrhh.crear_arma(
            tpa=tpa.strip() or None, marca=marca.strip() or None,
            modelo=modelo.strip() or None, calibre=calibre.strip() or None,
            serie=serie.strip() or None, anio=_int(anio),
            estado=estado.strip() or 'operativa',
            fecha_adquisicion=_d(fecha_adquisicion),
            polvorin_id=_int(polvorin_id), observaciones=observaciones.strip() or None,
            creado_por=session.get('usuario_id'),
        )
    except _UNIQUE_EXC:
        return RedirectResponse(
            f'/armeria?error={quote("Ya existe un arma con ese TPA o serie.")}', status_code=303)
    return RedirectResponse(f'/armeria/{arma_id}', status_code=303)


@router.get('/armeria/libro')
async def libro(request: Request):
    movimientos = db_rrhh.historial_asignaciones(limite=300)
    return templates.TemplateResponse(
        request=request, name='armeria_libro.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'movimientos': movimientos,
        },
    )


@router.get('/armeria/municion')
async def municion(request: Request, error: str = '', ok: str = ''):
    lotes = db_rrhh.listar_lotes_municion()
    for lote in lotes:
        lote['_movs'] = db_rrhh.movimientos_de_lote(lote['id'], limite=8)
    return templates.TemplateResponse(
        request=request, name='municion.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'lotes': lotes, 'calibres': CALIBRES_COMUNES,
            'mov_tipos': MUNICION_MOV_TIPOS, 'mov_dict': MUNICION_MOV_DICT,
            'error': error, 'ok': ok,
        },
    )


@router.post('/armeria/municion/nuevo-lote')
async def crear_lote(
    request: Request,
    calibre: str = Form(...), cantidad_inicial: str = Form(...),
    fecha_ingreso: str = Form(''), proveedor: str = Form(''),
    observaciones: str = Form(''),
):
    session = request.state.session
    cant = _int(cantidad_inicial, 0)
    if cant <= 0:
        return RedirectResponse(
            f'/armeria/municion?error={quote("Cantidad inicial inválida.")}', status_code=303)
    db_rrhh.crear_lote_municion(
        calibre=calibre.strip(), cantidad_inicial=cant,
        fecha_ingreso=_d(fecha_ingreso), proveedor=proveedor.strip() or None,
        observaciones=observaciones.strip() or None, creado_por=session.get('usuario_id'),
    )
    return RedirectResponse(f'/armeria/municion?ok={quote("Lote registrado.")}', status_code=303)


@router.post('/armeria/municion/{lote_id}/movimiento')
async def mov_municion(
    request: Request, lote_id: int,
    tipo: str = Form(...), cantidad: str = Form(...), motivo: str = Form(''),
):
    session = request.state.session
    try:
        db_rrhh.registrar_movimiento_municion(
            lote_id=lote_id, tipo=tipo, cantidad=_int(cantidad, 0),
            motivo=motivo.strip() or None, registrado_por=session.get('usuario_id'),
        )
    except ReglaArmeria as e:
        return RedirectResponse(f'/armeria/municion?error={quote(str(e))}', status_code=303)
    return RedirectResponse(f'/armeria/municion?ok={quote("Movimiento registrado.")}', status_code=303)


# ── Polvorines ────────────────────────────────────────────────

@router.get('/armeria/polvorines')
async def polvorines(request: Request, ok: str = ''):
    return templates.TemplateResponse(
        request=request, name='polvorines.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'polvorines': db_rrhh.listar_polvorines(solo_activos=False),
            'ok': ok,
        },
    )


@router.post('/armeria/polvorines/nuevo')
async def crear_polvorin(
    request: Request,
    nombre: str = Form(...), direccion: str = Form(''), capacidad_max: str = Form(''),
    autorizacion_sucamec: str = Form(''), vigencia_autorizacion: str = Form(''),
):
    session = request.state.session
    db_rrhh.crear_polvorin(
        nombre=nombre.strip(), direccion=direccion.strip() or None,
        capacidad_max=_int(capacidad_max), autorizacion_sucamec=autorizacion_sucamec.strip() or None,
        vigencia_autorizacion=_d(vigencia_autorizacion), creado_por=session.get('usuario_id'),
    )
    return RedirectResponse(f'/armeria/polvorines?ok={quote("Polvorín registrado.")}', status_code=303)


# ── Detalle de un arma (asignar / devolver / historial) ───────
# NOTA: esta ruta {arma_id:int} va al final para no capturar /libro, /municion, etc.

@router.get('/armeria/{arma_id}')
async def detalle(request: Request, arma_id: int, error: str = '', ok: str = ''):
    arma = db_rrhh.get_arma(arma_id)
    if not arma:
        raise HTTPException(status_code=404, detail='Arma no existe')
    asignacion = db_rrhh.asignacion_abierta_de_arma(arma_id)
    historial = db_rrhh.historial_asignaciones(arma_id=arma_id)
    # Vigilantes habilitados/activos para el selector de asignación
    personal = db_rrhh.listar_personal(solo_activos=True)
    for t in personal:
        t['_hab'] = db_rrhh.estado_habilitacion(t['dni'])
    return templates.TemplateResponse(
        request=request, name='arma_detalle.html',
        context={
            'session': request.state.session,
            'proyecto_activo': request.state.proyecto_activo,
            'arma': arma, 'asignacion': asignacion, 'historial': historial,
            'personal': personal, 'estados': ARMA_ESTADOS, 'calibres': CALIBRES_COMUNES,
            'polvorines': db_rrhh.listar_polvorines(),
            'error': error, 'ok': ok,
        },
    )


@router.post('/armeria/{arma_id}/editar')
async def editar(
    request: Request, arma_id: int,
    marca: str = Form(''), modelo: str = Form(''), calibre: str = Form(''),
    serie: str = Form(''), anio: str = Form(''), tpa: str = Form(''),
    estado: str = Form('operativa'), fecha_adquisicion: str = Form(''),
    polvorin_id: str = Form(''), observaciones: str = Form(''),
):
    if not db_rrhh.get_arma(arma_id):
        raise HTTPException(status_code=404, detail='Arma no existe')
    try:
        db_rrhh.actualizar_arma(
            arma_id, tpa=tpa.strip() or None, marca=marca.strip() or None,
            modelo=modelo.strip() or None, calibre=calibre.strip() or None,
            serie=serie.strip() or None, anio=_int(anio), estado=estado.strip(),
            fecha_adquisicion=_d(fecha_adquisicion), polvorin_id=_int(polvorin_id),
            observaciones=observaciones.strip() or None,
        )
    except _UNIQUE_EXC:
        return RedirectResponse(
            f'/armeria/{arma_id}?error={quote("TPA o serie duplicados.")}', status_code=303)
    return RedirectResponse(f'/armeria/{arma_id}?ok={quote("Arma actualizada.")}', status_code=303)


@router.post('/armeria/{arma_id}/asignar')
async def asignar(
    request: Request, arma_id: int,
    dni: str = Form(...), puesto: str = Form(''),
    municion_entregada: str = Form(''), observaciones: str = Form(''),
):
    session = request.state.session
    try:
        db_rrhh.asignar_arma(
            arma_id=arma_id, dni=dni.strip(), puesto=puesto.strip() or None,
            municion_entregada=_int(municion_entregada),
            observaciones=observaciones.strip() or None,
            registrado_por=session.get('usuario_id'),
        )
    except ReglaArmeria as e:
        return RedirectResponse(f'/armeria/{arma_id}?error={quote(str(e))}', status_code=303)
    return RedirectResponse(
        f'/armeria/{arma_id}?ok={quote("Arma asignada y registrada en el libro.")}', status_code=303)


@router.post('/armeria/{arma_id}/devolver')
async def devolver(
    request: Request, arma_id: int,
    asignacion_id: int = Form(...), municion_devuelta: str = Form(''),
    observaciones: str = Form(''),
):
    db_rrhh.devolver_arma(
        asignacion_id, municion_devuelta=_int(municion_devuelta),
        observaciones=observaciones.strip() or None,
    )
    return RedirectResponse(
        f'/armeria/{arma_id}?ok={quote("Arma devuelta y registrada.")}', status_code=303)
