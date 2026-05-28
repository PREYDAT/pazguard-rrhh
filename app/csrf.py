"""CSRF protection (pure ASGI middleware).

Pattern: synchronizer token derivado por HMAC del session token.

NOTA: este middleware es ASGI puro (no BaseHTTPMiddleware) para evitar el
bug conocido de Starlette donde `await request.form()` dentro de un
BaseHTTPMiddleware consume el body stream y el handler subsecuente recibe
422 RequestValidationError porque los Form(...) llegan vacios.

En su lugar bufferamos el body en el receive callable, parseamos el CSRF
token manualmente (urlencoded) y re-inyectamos el body para el handler.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional
from urllib.parse import parse_qs

logger = logging.getLogger(__name__)

_CSRF_SECRET_ENV = (
    os.environ.get('CSRF_SECRET', '').strip()
    or os.environ.get('PAZGUARD_CORE_SECRET', '').strip()
)
_CSRF_FALLBACK = 'dev-csrf-fallback-NOT-FOR-PRODUCTION'
_CSRF_SECRET = _CSRF_SECRET_ENV or _CSRF_FALLBACK


def _verificar_secret_safe():
    if _CSRF_SECRET == _CSRF_FALLBACK:
        is_debug = os.environ.get('DEBUG', '0').strip() in ('1', 'true', 'True', 'yes')
        if is_debug:
            logger.warning(
                "[CSRF] Usando secret fallback hardcoded (DEBUG mode). "
                "OK para desarrollo. NO usar en produccion."
            )
        else:
            logger.error(
                "[CSRF FATAL] NI CSRF_SECRET NI PAZGUARD_CORE_SECRET estan seteados. "
                "Configurar al menos PAZGUARD_CORE_SECRET en Railway env vars."
            )
            import sys
            sys.exit(1)


_verificar_secret_safe()


def generar_csrf_token(session_token: Optional[str]) -> str:
    if not session_token:
        return ''
    sig = hmac.new(
        _CSRF_SECRET.encode('utf-8'),
        (session_token + ':csrf-v1').encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return sig[:32]


def verificar_csrf(session_token: Optional[str], submitted: Optional[str]) -> bool:
    if not session_token or not submitted:
        return False
    expected = generar_csrf_token(session_token)
    if len(submitted) != len(expected):
        return False
    return hmac.compare_digest(expected, submitted)


CSRF_EXEMPT_PATHS = {
    '/login',
    '/logout',
    '/sso',
}
CSRF_EXEMPT_PREFIXES = (
    '/api/externo/',
)
_METHODS_PROTECTED = {'POST', 'PUT', 'PATCH', 'DELETE'}


def _cookie_from_scope(scope) -> Optional[str]:
    """Extrae la cookie de sesion del header Cookie en scope."""
    from pazguard_core.config import SESSION_COOKIE_NAME
    cookie_header = None
    for name, value in scope.get('headers', []):
        if name == b'cookie':
            cookie_header = value.decode('latin-1', 'replace')
            break
    if not cookie_header:
        return None
    for part in cookie_header.split(';'):
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        if k.strip() == SESSION_COOKIE_NAME:
            return v.strip()
    return None


def _content_type_from_scope(scope) -> str:
    for name, value in scope.get('headers', []):
        if name == b'content-type':
            return value.decode('latin-1', 'replace').lower()
    return ''


def _header_value(scope, header_name: bytes) -> Optional[str]:
    for name, value in scope.get('headers', []):
        if name == header_name:
            return value.decode('latin-1', 'replace')
    return None


def _extract_csrf_from_body(body: bytes, content_type: str) -> str:
    """Parsea body urlencoded o multipart para extraer csrf_token."""
    if not body:
        return ''
    if 'application/x-www-form-urlencoded' in content_type:
        try:
            decoded = parse_qs(body.decode('utf-8', 'replace'), keep_blank_values=True)
            vals = decoded.get('csrf_token', [])
            return (vals[0] if vals else '').strip()
        except Exception:
            return ''
    if 'multipart/form-data' in content_type:
        # Parseo minimo de multipart: buscar boundary y campo csrf_token
        try:
            # boundary=...
            ct_lower = content_type.lower()
            idx = ct_lower.find('boundary=')
            if idx == -1:
                return ''
            boundary = content_type[idx + 9:].strip().strip('"').encode()
            parts = body.split(b'--' + boundary)
            for part in parts:
                if b'name="csrf_token"' in part:
                    # encontrar \r\n\r\n separador
                    sep = part.find(b'\r\n\r\n')
                    if sep == -1:
                        continue
                    val = part[sep + 4:]
                    # quitar trailing \r\n
                    val = val.rstrip(b'\r\n').rstrip(b'--').rstrip(b'\r\n')
                    return val.decode('utf-8', 'replace').strip()
        except Exception:
            return ''
    return ''


class CSRFMiddleware:
    """Pure ASGI middleware para CSRF protection.

    Setea request.state.csrf_token (HMAC del session cookie) y valida los
    POST/PUT/PATCH/DELETE no exentos. Cuando hay form body, lo lee y lo
    re-inyecta para que el handler reciba el body intacto (evita el bug
    de BaseHTTPMiddleware que consume el stream).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        session_token = _cookie_from_scope(scope)
        csrf_token = generar_csrf_token(session_token)

        # Inyectar csrf_token en scope.state (Starlette lee de aqui)
        # state existe en scope['state'] segun el ASGI lifespan del FastAPI app
        state = scope.setdefault('state', {})
        state['csrf_token'] = csrf_token

        method = scope.get('method', '').upper()
        path = scope.get('path', '')

        # Sin validacion: pasar directo
        if (method not in _METHODS_PROTECTED
                or path in CSRF_EXEMPT_PATHS
                or any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES)
                or not session_token):
            await self.app(scope, receive, send)
            return

        # Validacion CSRF: bufferamos el body y luego lo re-inyectamos
        body_parts = []
        more_body = True
        while more_body:
            msg = await receive()
            if msg['type'] == 'http.disconnect':
                # Cliente desconecto - reenviar y salir
                async def replay():
                    return msg
                await self.app(scope, replay, send)
                return
            body_parts.append(msg.get('body', b''))
            more_body = msg.get('more_body', False)

        full_body = b''.join(body_parts)

        # Extraer CSRF token: primero de form body, sino de header
        content_type = _content_type_from_scope(scope)
        submitted = _extract_csrf_from_body(full_body, content_type)
        if not submitted:
            submitted = (_header_value(scope, b'x-csrf-token') or '').strip()

        if not verificar_csrf(session_token, submitted):
            client = scope.get('client') or ('?', 0)
            logger.warning(
                f"CSRF reject: path={path} method={method} "
                f"has_token={bool(submitted)} ip={client[0]}"
            )
            # 403 si /api/, sino redirect a portal
            if path.startswith('/api/'):
                body = (
                    b'{"error":"csrf_invalid",'
                    b'"detail":"CSRF token requerido o invalido"}'
                )
                await send({
                    'type': 'http.response.start',
                    'status': 403,
                    'headers': [
                        (b'content-type', b'application/json'),
                        (b'content-length', str(len(body)).encode()),
                    ],
                })
                await send({'type': 'http.response.body', 'body': body})
                return
            redirect_url = f'/?error=csrf_invalido&from={path}'.encode()
            await send({
                'type': 'http.response.start',
                'status': 303,
                'headers': [
                    (b'location', redirect_url),
                    (b'content-length', b'0'),
                ],
            })
            await send({'type': 'http.response.body', 'body': b''})
            return

        # CSRF OK: re-inyectar body para el handler
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {
                    'type': 'http.request',
                    'body': full_body,
                    'more_body': False,
                }
            # Despues del body, mantener al cliente "vivo" (handler quizas
            # llame receive de nuevo). Devolvemos disconnect para terminar
            # limpiamente.
            return {'type': 'http.disconnect'}

        await self.app(scope, replay_receive, send)
