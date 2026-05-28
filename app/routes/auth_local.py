"""Login local fallback + logout. SSO handover ya se maneja en main.AuthMiddleware.

Login local solo aplica si el usuario llega directo a /login (no via hub).
Se valida contra pazguard-core (mismo Postgres, misma tabla usuarios_global).
"""
import logging
import os
import time
from collections import deque
from threading import Lock

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from pazguard_core import auth as core_auth, projects as core_projects
from pazguard_core.config import SESSION_COOKIE_NAME, SESSION_TTL_HOURS

logger = logging.getLogger(__name__)
router = APIRouter()

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(APP_DIR, 'templates'))


# Rate limit por IP (mismo patron que hub)
_LOGIN_RATE_LIMIT = 10
_LOGIN_RATE_WINDOW = 60
_LOGIN_ATTEMPTS: dict = {}
_LOGIN_LOCK = Lock()


def _client_ip(request: Request) -> str:
    xff = request.headers.get('x-forwarded-for', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'


def _check_login_rate(ip: str) -> bool:
    now = time.time()
    with _LOGIN_LOCK:
        attempts = _LOGIN_ATTEMPTS.get(ip)
        if attempts is None:
            attempts = deque(maxlen=_LOGIN_RATE_LIMIT + 1)
            _LOGIN_ATTEMPTS[ip] = attempts
        cutoff = now - _LOGIN_RATE_WINDOW
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= _LOGIN_RATE_LIMIT:
            return False
        attempts.append(now)
        return True


@router.get('/login')
async def login_form(request: Request, next: str = '/', error: str = ''):
    hub_url = os.environ.get('PAZGUARD_HUB_URL', '').rstrip('/')
    return templates.TemplateResponse(
        request=request,
        name='login.html',
        context={'next': next, 'error': error, 'hub_url': hub_url},
    )


@router.post('/login')
async def login_submit(
    request: Request,
    username: str = Form(...),
    pin: str = Form(...),
    next: str = Form('/'),
):
    ip = _client_ip(request)
    ua = request.headers.get('user-agent', '')[:200]

    if not _check_login_rate(ip):
        logger.warning(f"Rate limit login: ip={ip} username={username[:30]}")
        return RedirectResponse(
            '/login?error=Demasiados+intentos.+Espera+1+minuto.', status_code=303
        )

    user = core_auth.login(username.strip(), pin.strip(), ip=ip, user_agent=ua)
    if not user:
        return RedirectResponse(
            f'/login?next={next}&error=Usuario o PIN incorrectos', status_code=303
        )

    ps = core_projects.list_for_user(user['id'])
    proyecto_activo_id = ps[0]['id'] if ps else None

    token = core_auth.create_session(
        usuario_id=user['id'],
        sistema='rrhh',
        proyecto_activo_id=proyecto_activo_id,
        ip=ip,
        user_agent=ua,
    )

    next_url = next if (next.startswith('/') and not next.startswith('//')) else '/'
    resp = RedirectResponse(next_url, status_code=303)
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=True,
        samesite='lax',
    )
    return resp


@router.get('/logout')
@router.post('/logout')
async def logout(request: Request):
    if request.method == 'GET':
        sfs = request.headers.get('sec-fetch-site', '')
        if sfs and sfs not in ('same-origin', 'same-site', 'none'):
            return RedirectResponse('/', status_code=303)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        core_auth.logout(token)
    hub_url = os.environ.get('PAZGUARD_HUB_URL', '').rstrip('/')
    target = f'{hub_url}/login' if hub_url else '/login'
    resp = RedirectResponse(target, status_code=303)
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp
