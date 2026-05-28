"""Tests del CSRF (ASGI puro) — el bug que la auditoria Opus 4.8 encontro.

Cubre:
- generar/verificar token (HMAC, constant-time, longitud)
- extraccion de csrf_token de body urlencoded y multipart
- middleware ASGI end-to-end: el body llega INTACTO al handler (regresion
  del bug BaseHTTPMiddleware + request.form() -> 422), y CSRF invalido
  es rechazado.
"""
from fastapi import FastAPI, Form
from fastapi.responses import PlainTextResponse
from starlette.testclient import TestClient

from app.csrf import (
    CSRFMiddleware,
    generar_csrf_token,
    verificar_csrf,
    _extract_csrf_from_body,
)

COOKIE = "pazguard_session"


# ── funciones puras ───────────────────────────────────────────

def test_token_vacio_si_no_hay_sesion():
    assert generar_csrf_token(None) == ""
    assert generar_csrf_token("") == ""


def test_token_determinista_y_largo_fijo():
    t1 = generar_csrf_token("sess-abc")
    t2 = generar_csrf_token("sess-abc")
    assert t1 == t2
    assert len(t1) == 32


def test_token_distinto_por_sesion():
    assert generar_csrf_token("sess-a") != generar_csrf_token("sess-b")


def test_verificar_ok_y_falla():
    tok = "sess-xyz"
    good = generar_csrf_token(tok)
    assert verificar_csrf(tok, good) is True
    assert verificar_csrf(tok, "malo") is False
    assert verificar_csrf(tok, "") is False
    assert verificar_csrf(None, good) is False


def test_extract_urlencoded():
    body = b"nombre=Vigilancia&csrf_token=abc123&codigo=VP"
    assert _extract_csrf_from_body(body, "application/x-www-form-urlencoded") == "abc123"


def test_extract_multipart():
    boundary = "----X"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="csrf_token"\r\n\r\n'
        "tok999\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    ct = f"multipart/form-data; boundary={boundary}"
    assert _extract_csrf_from_body(body, ct) == "tok999"


# ── middleware end-to-end ──────────────────────────────────────

def _app():
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/crear")
    async def crear(codigo: str = Form(...), nombre: str = Form(...)):
        return PlainTextResponse(f"{codigo}|{nombre}")

    @app.get("/")
    async def home():
        return PlainTextResponse("ok")

    return app


def test_post_con_csrf_valido_llega_al_handler():
    """Regresion del bug 422: el body debe llegar completo al handler."""
    c = TestClient(_app())
    c.cookies.set(COOKIE, "sess-1")
    good = generar_csrf_token("sess-1")
    r = c.post("/crear", data={"codigo": "VP", "nombre": "Vigilancia", "csrf_token": good})
    assert r.status_code == 200
    assert r.text == "VP|Vigilancia"


def test_post_con_csrf_invalido_rechazado():
    c = TestClient(_app())
    c.cookies.set(COOKIE, "sess-1")
    r = c.post(
        "/crear",
        data={"codigo": "VP", "nombre": "X", "csrf_token": "malo"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "csrf_invalido" in r.headers.get("location", "")


def test_post_sin_sesion_pasa(  ):
    """Sin cookie de sesion no hay nada que proteger (auth lo maneja aparte)."""
    c = TestClient(_app())
    r = c.post("/crear", data={"codigo": "VP", "nombre": "Y"})
    # Sin sesion, el CSRF no valida; el handler corre (200).
    assert r.status_code == 200


def test_get_no_validado():
    c = TestClient(_app())
    c.cookies.set(COOKIE, "sess-1")
    r = c.get("/")
    assert r.status_code == 200
