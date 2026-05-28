"""CSRF protection (copia del hub pazguard).

Pattern: synchronizer token derivado por HMAC del session token.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

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


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        from pazguard_core.config import SESSION_COOKIE_NAME
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        request.state.csrf_token = generar_csrf_token(session_token)

        if request.method not in _METHODS_PROTECTED:
            return await call_next(request)
        path = request.url.path
        if path in CSRF_EXEMPT_PATHS or any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES):
            return await call_next(request)
        if not session_token:
            return await call_next(request)

        submitted = ''
        ct = request.headers.get('content-type', '')
        if 'application/x-www-form-urlencoded' in ct or 'multipart/form-data' in ct:
            try:
                form = await request.form()
                submitted = (form.get('csrf_token') or '').strip()
            except Exception:
                submitted = ''
        if not submitted:
            submitted = (request.headers.get('x-csrf-token') or '').strip()

        if not verificar_csrf(session_token, submitted):
            logger.warning(
                f"CSRF reject: path={path} method={request.method} "
                f"has_token={bool(submitted)} ip={request.client.host if request.client else '?'}"
            )
            if path.startswith('/api/'):
                return JSONResponse(
                    {'error': 'csrf_invalid', 'detail': 'CSRF token requerido o invalido'},
                    status_code=403
                )
            return RedirectResponse(
                f'/?error=csrf_invalido&from={path}', status_code=303
            )

        return await call_next(request)
