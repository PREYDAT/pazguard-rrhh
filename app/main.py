"""pazguard-rrhh — Sistema RRHH/SUCAMEC.

Satelite de la suite PAZGUARD. Consume pazguard-core para auth/SSO.
Maneja modalidades SUCAMEC + carta fianza (Fase 4.1).
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from pazguard_core import auth as core_auth
from pazguard_core.logging_json import setup_logging

setup_logging(level=os.environ.get('LOG_LEVEL', 'INFO'), service='pazguard-rrhh')
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("pazguard-rrhh - iniciando...")

    # Migraciones: solo si RUN_MIGRATIONS_ON_BOOT=1.
    if os.environ.get('RUN_MIGRATIONS_ON_BOOT', '').lower() in ('1', 'true', 'yes'):
        import threading

        def _bg_migrate():
            try:
                from app.services.database_rrhh import run_migrations
                run_migrations()
                logger.info("Migrations rrhh_* OK")
            except Exception as e:
                logger.warning(f"rrhh migrations fallo (no-fatal): {e}")

        threading.Thread(target=_bg_migrate, daemon=True, name="rrhh-migrate").start()
        logger.info("Migrations rrhh_* lanzadas en background")
    else:
        logger.info("Migrations skip (RUN_MIGRATIONS_ON_BOOT!=1)")

    # Scheduler de alertas vencimientos
    try:
        from app.services.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scheduler de alertas iniciado")
    except Exception as e:
        logger.warning(f"Scheduler no se inicio (no-fatal): {e}")

    logger.info("pazguard-rrhh listo")
    yield

    logger.info("pazguard-rrhh - cerrando")
    try:
        from app.services.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    try:
        from pazguard_core.db import close_pool
        close_pool()
    except Exception:
        pass


app = FastAPI(title="PAZGUARD RRHH/SUCAMEC", lifespan=lifespan)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, 'static')
if os.path.isdir(STATIC_DIR):
    app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


# ── Middleware de auth ────────────────────────────────────────

PUBLIC_PATHS = {'/login', '/logout', '/health', '/favicon.ico', '/sso'}
PUBLIC_PREFIXES = ('/static/',)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            request.state.session = None
            request.state.proyecto_activo = None
            return await call_next(request)

        from pazguard_core.config import SESSION_COOKIE_NAME

        # SSO handover: si llega ?kt=<token>, validate_session lo consume y
        # crea sesion normal. Setear cookie nueva y redirigir limpiando query.
        kt = request.query_params.get('kt')
        if kt:
            session = core_auth.validate_session(kt)
            if session and session.get('_from_handover'):
                # Redirigir a la misma URL pero sin ?kt= y con cookie nueva
                from urllib.parse import urlencode
                params = dict(request.query_params)
                params.pop('kt', None)
                qs = ('?' + urlencode(params)) if params else ''
                resp = RedirectResponse(path + qs, status_code=303)
                from pazguard_core.config import SESSION_TTL_HOURS
                resp.set_cookie(
                    key=SESSION_COOKIE_NAME,
                    value=session['token'],
                    max_age=SESSION_TTL_HOURS * 3600,
                    httponly=True,
                    secure=True,
                    samesite='lax',
                )
                return resp

        token = request.cookies.get(SESSION_COOKIE_NAME)
        session = core_auth.validate_session(token)

        if not session:
            if path.startswith('/api/'):
                return JSONResponse({'error': 'unauthenticated'}, status_code=401)
            # Redirigir al hub para login centralizado
            hub_url = os.environ.get('PAZGUARD_HUB_URL', '').rstrip('/')
            if hub_url:
                return RedirectResponse(f'{hub_url}/login?sistema=rrhh', status_code=303)
            return RedirectResponse('/login?next=' + path, status_code=303)

        request.state.session = session
        request.state.proyecto_activo = None
        if session.get('proyecto_activo_id'):
            try:
                from pazguard_core import projects as core_projects
                request.state.proyecto_activo = core_projects.get(session['proyecto_activo_id'])
            except Exception as e:
                logger.warning(f"No se pudo cargar proyecto activo: {e}")

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response


from app.csrf import CSRFMiddleware

# Orden inverso: SecurityHeaders (mas externo) → CSRF → Auth → handler
app.add_middleware(CSRFMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


# ── Health ────────────────────────────────────────────────────

@app.get('/health')
async def health():
    from pazguard_core.db import ping
    return {'status': 'ok', 'service': 'pazguard-rrhh', 'core_db': ping()}


@app.get('/favicon.ico')
async def favicon():
    return RedirectResponse('/static/favicon.ico', status_code=301)


# ── Routers ───────────────────────────────────────────────────

from app.routes import portal, modalidades, fianzas, auth_local

app.include_router(auth_local.router)
app.include_router(portal.router)
app.include_router(modalidades.router)
app.include_router(fianzas.router)


# ── Exception handlers ────────────────────────────────────────

_SISTEMA_NOMBRE = "PAZGUARD RRHH"


async def _suite_http_exc(request, exc):
    from starlette.exceptions import HTTPException as _SE
    code = getattr(exc, 'status_code', 500)
    accepts_json = 'application/json' in (request.headers.get('accept') or '')
    if request.url.path.startswith('/api/') or accepts_json:
        return JSONResponse({'error': getattr(exc, 'detail', 'error'), 'status': code}, status_code=code)
    titulos = {
        404: ('Pagina no encontrada', 'La URL que buscas no existe.', '🔍'),
        403: ('Sin permiso', 'No tenes permisos para ver esto.', '🔒'),
        401: ('Sesion expirada', 'Necesitas iniciar sesion.', '🔑'),
        422: ('Datos invalidos', 'Algun parametro no es valido.', '⚠️'),
    }
    titulo, msg, icono = titulos.get(code, (f'Error {code}', getattr(exc, 'detail', 'Algo salio mal.'), '⚠️'))
    html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{titulo} · {_SISTEMA_NOMBRE}</title>
<style>body{{font-family:-apple-system,Segoe UI,sans-serif;background:#0F172A;color:#E2E8F0;
margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
.card{{background:#1E293B;padding:40px 48px;border-radius:14px;max-width:540px;text-align:center}}
.icon{{font-size:64px;margin-bottom:16px}}
h1{{margin:0 0 12px;font-size:24px;color:#D4A03E}}
p{{margin:0 0 24px;color:#94A3B8}}
a.btn{{display:inline-block;padding:10px 22px;border-radius:8px;font-weight:600;
text-decoration:none;margin:0 6px;font-size:14px;background:#1E3A5F;color:#fff}}
code{{background:#0F172A;padding:2px 8px;border-radius:4px;font-size:13px}}</style></head><body>
<div class="card"><div class="icon">{icono}</div><h1>{titulo}</h1><p>{msg}</p>
<p><code>{request.url.path}</code></p>
<a class="btn" href="/">← Volver al inicio</a></div></body></html>"""
    return HTMLResponse(html, status_code=code)


from starlette.exceptions import HTTPException as _StarletteHTTPExc
from fastapi.exceptions import RequestValidationError as _ReqValErr


async def _suite_val(request, exc):
    class _F:
        status_code = 422
        detail = 'Datos invalidos'
    return await _suite_http_exc(request, _F())


app.add_exception_handler(_StarletteHTTPExc, _suite_http_exc)
app.add_exception_handler(404, _suite_http_exc)
app.add_exception_handler(_ReqValErr, _suite_val)
app.add_exception_handler(422, _suite_val)
