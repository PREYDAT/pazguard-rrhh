"""Migrations aditivas + helpers SQL para tablas rrhh_*.

Fase 4.1: solo modalidades + carta fianza. Las demas tablas (personal,
vigencias, armas, etc.) vienen en fases siguientes.

Las migrations corren idempotentes con CREATE TABLE IF NOT EXISTS via
pazguard_core.db.get_conn (Postgres compartido con hub).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from pazguard_core.db import get_conn

from app.config import (
    TIPOS_VIGENCIA_OBLIGATORIAS,
    TIPOS_VIGENCIA_DICT,
    ARMA_ESTADO_OPERATIVA,
    HAB_NO_HABILITADO,
    MUNICION_MOV_SIGNO,
)

logger = logging.getLogger(__name__)


SCHEMA_RRHH = [
    # ── Modalidades SUCAMEC autorizadas a PAZGUARD ────────────
    """
    CREATE TABLE IF NOT EXISTS rrhh_modalidad (
        id                  SERIAL PRIMARY KEY,
        proyecto_id         INTEGER REFERENCES proyectos(id) ON DELETE CASCADE,
        codigo              TEXT NOT NULL,
        nombre              TEXT NOT NULL,
        resolucion_sucamec  TEXT,
        fecha_otorgamiento  DATE,
        fecha_vencimiento   DATE,
        alcance_geografico  TEXT,
        archivo_pdf_url     TEXT,
        observaciones       TEXT,
        activa              BOOLEAN NOT NULL DEFAULT TRUE,
        creada_en           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        creada_por          INTEGER REFERENCES usuarios_global(id),
        actualizada_en      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (proyecto_id, codigo)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_modalidad_vence ON rrhh_modalidad(fecha_vencimiento) WHERE activa",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_modalidad_proyecto ON rrhh_modalidad(proyecto_id) WHERE activa",

    # ── Carta Fianza (minimo 5 UIT, renovacion anual tipica) ──
    """
    CREATE TABLE IF NOT EXISTS rrhh_carta_fianza (
        id                  SERIAL PRIMARY KEY,
        proyecto_id         INTEGER REFERENCES proyectos(id) ON DELETE CASCADE,
        banco               TEXT NOT NULL,
        numero_carta        TEXT,
        monto               NUMERIC(14,2) NOT NULL,
        moneda              TEXT NOT NULL DEFAULT 'PEN',
        uit_referencia      NUMERIC(10,2),
        num_uit             NUMERIC(6,2),
        fecha_emision       DATE NOT NULL,
        fecha_vencimiento   DATE NOT NULL,
        archivo_pdf_url     TEXT,
        observaciones       TEXT,
        estado              TEXT NOT NULL DEFAULT 'vigente',
        creada_en           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        creada_por          INTEGER REFERENCES usuarios_global(id),
        actualizada_en      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_fianza_vence ON rrhh_carta_fianza(fecha_vencimiento) WHERE estado = 'vigente'",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_fianza_proyecto ON rrhh_carta_fianza(proyecto_id)",

    # ── Bitacora de alertas enviadas (idempotencia: 1 alerta por evento) ──
    """
    CREATE TABLE IF NOT EXISTS rrhh_alerta_enviada (
        id                  SERIAL PRIMARY KEY,
        entidad_tipo        TEXT NOT NULL,
        entidad_id          INTEGER NOT NULL,
        dias_restantes      INTEGER NOT NULL,
        canal               TEXT NOT NULL,
        destinatario        TEXT,
        enviada_en          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (entidad_tipo, entidad_id, dias_restantes, canal)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_alerta_entidad ON rrhh_alerta_enviada(entidad_tipo, entidad_id)",

    # ── FIX auditoria Opus 4.8 (P1-1): modalidades y carta fianza son
    #    NIVEL EMPRESA, no por proyecto. Normalizamos proyecto_id a NULL
    #    (idempotente) y agregamos UNIQUE parcial sobre codigo a nivel
    #    empresa (el UNIQUE(proyecto_id,codigo) original NO protege con
    #    proyecto_id=NULL porque en Postgres NULL != NULL en constraints).
    "UPDATE rrhh_modalidad SET proyecto_id = NULL WHERE proyecto_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rrhh_modalidad_codigo_empresa "
    "ON rrhh_modalidad (codigo) WHERE proyecto_id IS NULL",
    "UPDATE rrhh_carta_fianza SET proyecto_id = NULL WHERE proyecto_id IS NOT NULL",

    # ── FASE 4.2: Vigencias de PERSONAL vigilante ─────────────
    # El trabajador es empleados_pazguard (core, dni PK, compartido en toda
    # la suite). Aqui guardamos sus vigencias SUCAMEC/laborales. Cada vigencia
    # es de la PERSONA (no por proyecto): un carne SUCAMEC pertenece al
    # vigilante, no a un contrato. El filtro por proyecto (que vigilantes
    # estan en el contrato X) vendra de empleado_proyecto_asignacion (core).
    """
    CREATE TABLE IF NOT EXISTS rrhh_vigencia (
        id                  SERIAL PRIMARY KEY,
        dni                 TEXT NOT NULL REFERENCES empleados_pazguard(dni) ON DELETE CASCADE,
        tipo                TEXT NOT NULL,
        numero_doc          TEXT,
        entidad_emisora     TEXT,
        fecha_emision       DATE,
        fecha_vencimiento   DATE,
        archivo_pdf_url     TEXT,
        observaciones       TEXT,
        creada_en           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        creada_por          INTEGER REFERENCES usuarios_global(id),
        actualizada_en      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_vigencia_dni ON rrhh_vigencia(dni)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_vigencia_vence ON rrhh_vigencia(fecha_vencimiento)",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_vigencia_tipo ON rrhh_vigencia(dni, tipo)",
    # Una sola vigencia "viva" por (dni, tipo): al renovar se actualiza la
    # misma fila o se reemplaza. Evita 3 carnes SUCAMEC duplicados.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rrhh_vigencia_dni_tipo ON rrhh_vigencia(dni, tipo)",

    # ═══════════════ FASE 4.3: ARMERÍA SUCAMEC ═══════════════
    # Armas y munición son nivel EMPRESA (registradas a nombre de PAZGUARD
    # ante SUCAMEC). Trazabilidad forense: cada movimiento queda registrado.

    # Polvorín (almacén de armas/munición autorizado). vigencia_autorizacion
    # alimenta el dashboard de vencimientos.
    """
    CREATE TABLE IF NOT EXISTS rrhh_polvorin (
        id                      SERIAL PRIMARY KEY,
        nombre                  TEXT NOT NULL,
        direccion               TEXT,
        capacidad_max           INTEGER,
        autorizacion_sucamec    TEXT,
        vigencia_autorizacion   DATE,
        activo                  BOOLEAN NOT NULL DEFAULT TRUE,
        creado_en               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        creado_por              INTEGER REFERENCES usuarios_global(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_polvorin_vence ON rrhh_polvorin(vigencia_autorizacion) WHERE activo",

    # Inventario de armas. TPA (Tarjeta de Propiedad de Arma) único.
    """
    CREATE TABLE IF NOT EXISTS rrhh_arma (
        id                  SERIAL PRIMARY KEY,
        tpa                 TEXT UNIQUE,
        marca               TEXT,
        modelo              TEXT,
        calibre             TEXT,
        serie               TEXT,
        anio                INTEGER,
        estado              TEXT NOT NULL DEFAULT 'operativa',
        fecha_adquisicion   DATE,
        polvorin_id         INTEGER REFERENCES rrhh_polvorin(id) ON DELETE SET NULL,
        observaciones       TEXT,
        creado_en           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        creado_por          INTEGER REFERENCES usuarios_global(id),
        actualizado_en      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_arma_estado ON rrhh_arma(estado)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rrhh_arma_serie ON rrhh_arma(serie) WHERE serie IS NOT NULL",

    # Asignación nominal arma → vigilante (el "libro de armas" = historial).
    # fecha_retorno NULL = arma actualmente en poder del vigilante.
    """
    CREATE TABLE IF NOT EXISTS rrhh_asignacion_arma (
        id                  SERIAL PRIMARY KEY,
        arma_id             INTEGER NOT NULL REFERENCES rrhh_arma(id) ON DELETE CASCADE,
        dni                 TEXT NOT NULL REFERENCES empleados_pazguard(dni) ON DELETE CASCADE,
        puesto              TEXT,
        fecha_salida        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        fecha_retorno       TIMESTAMPTZ,
        municion_entregada  INTEGER,
        municion_devuelta   INTEGER,
        observaciones       TEXT,
        registrado_por      INTEGER REFERENCES usuarios_global(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_asig_arma_abierta ON rrhh_asignacion_arma(arma_id) WHERE fecha_retorno IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_rrhh_asig_arma_dni ON rrhh_asignacion_arma(dni)",
    # Un arma no puede tener 2 asignaciones abiertas a la vez (integridad).
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_rrhh_asig_arma_abierta ON rrhh_asignacion_arma(arma_id) WHERE fecha_retorno IS NULL",

    # Munición: lotes con saldo + movimientos que lo ajustan.
    """
    CREATE TABLE IF NOT EXISTS rrhh_municion_lote (
        id                  SERIAL PRIMARY KEY,
        calibre             TEXT NOT NULL,
        cantidad_inicial    INTEGER NOT NULL DEFAULT 0,
        cantidad_actual     INTEGER NOT NULL DEFAULT 0,
        fecha_ingreso       DATE,
        proveedor           TEXT,
        polvorin_id         INTEGER REFERENCES rrhh_polvorin(id) ON DELETE SET NULL,
        observaciones       TEXT,
        creado_en           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        creado_por          INTEGER REFERENCES usuarios_global(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_municion_calibre ON rrhh_municion_lote(calibre)",
    """
    CREATE TABLE IF NOT EXISTS rrhh_municion_movimiento (
        id                  SERIAL PRIMARY KEY,
        lote_id             INTEGER NOT NULL REFERENCES rrhh_municion_lote(id) ON DELETE CASCADE,
        tipo                TEXT NOT NULL,
        cantidad            INTEGER NOT NULL,
        fecha               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        dni                 TEXT REFERENCES empleados_pazguard(dni) ON DELETE SET NULL,
        motivo              TEXT,
        registrado_por      INTEGER REFERENCES usuarios_global(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rrhh_municion_mov_lote ON rrhh_municion_movimiento(lote_id, fecha DESC)",
]


def run_migrations():
    """Aplica migrations rrhh_* idempotentes. Safe para correr N veces."""
    aplicados = 0
    fallidos = 0
    for stmt in SCHEMA_RRHH:
        try:
            with get_conn() as conn:
                conn.execute("SET LOCAL statement_timeout = '5s'")
                conn.execute("SET LOCAL lock_timeout = '3s'")
                conn.execute(stmt)
            aplicados += 1
        except Exception as e:
            fallidos += 1
            preview = ' '.join(stmt.split())[:120]
            logger.warning(f"rrhh migration stmt fallo: {e} | stmt={preview}")
    logger.info(f"rrhh: migrations aplicadas (ok={aplicados} fail={fallidos}/{len(SCHEMA_RRHH)})")


# ═════════════════════════════════════════════════════════════
# CRUD: Modalidades SUCAMEC
# ═════════════════════════════════════════════════════════════

def listar_modalidades(solo_activas: bool = True):
    """Lista modalidades SUCAMEC (nivel empresa, sin filtro de proyecto)."""
    sql = "SELECT * FROM rrhh_modalidad WHERE 1=1"
    params = []
    if solo_activas:
        sql += " AND activa = TRUE"
    sql += " ORDER BY fecha_vencimiento NULLS LAST, nombre"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def get_modalidad(modalidad_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM rrhh_modalidad WHERE id = %s", (modalidad_id,)).fetchone()
        return dict(r) if r else None


def crear_modalidad(*, codigo: str, nombre: str,
                     resolucion_sucamec: Optional[str] = None,
                     fecha_otorgamiento: Optional[date] = None,
                     fecha_vencimiento: Optional[date] = None,
                     alcance_geografico: Optional[str] = None,
                     archivo_pdf_url: Optional[str] = None,
                     observaciones: Optional[str] = None,
                     creada_por: Optional[int] = None) -> int:
    """Crea una modalidad SUCAMEC. NIVEL EMPRESA (proyecto_id = NULL).

    FIX auditoria Opus 4.8 (P1-1): las modalidades SUCAMEC pertenecen a
    PAZGUARD como EMPRESA, no a un proyecto/contrato operativo. La columna
    proyecto_id queda como NULL (reservada). Si codigo ya existe lanza
    UniqueViolation -> el caller la captura y muestra mensaje amigable.
    """
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_modalidad
                (proyecto_id, codigo, nombre, resolucion_sucamec,
                 fecha_otorgamiento, fecha_vencimiento, alcance_geografico,
                 archivo_pdf_url, observaciones, creada_por)
               VALUES (NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (codigo, nombre, resolucion_sucamec,
             fecha_otorgamiento, fecha_vencimiento, alcance_geografico,
             archivo_pdf_url, observaciones, creada_por)
        ).fetchone()
        return r['id']


class ModalidadDuplicada(Exception):
    """El codigo de modalidad ya existe (UNIQUE)."""


def actualizar_modalidad(modalidad_id: int, **campos):
    if not campos:
        return False
    sets = []
    params = []
    for k, v in campos.items():
        sets.append(f"{k} = %s")
        params.append(v)
    sets.append("actualizada_en = NOW()")
    params.append(modalidad_id)
    with get_conn() as conn:
        r = conn.execute(
            f"UPDATE rrhh_modalidad SET {', '.join(sets)} WHERE id = %s",
            tuple(params)
        )
        return r.rowcount > 0


def desactivar_modalidad(modalidad_id: int) -> bool:
    return actualizar_modalidad(modalidad_id, activa=False)


# ═════════════════════════════════════════════════════════════
# CRUD: Carta Fianza
# ═════════════════════════════════════════════════════════════

def listar_fianzas(estado: Optional[str] = None):
    """Lista cartas fianza (nivel empresa, sin filtro de proyecto)."""
    sql = "SELECT * FROM rrhh_carta_fianza WHERE 1=1"
    params = []
    if estado:
        sql += " AND estado = %s"
        params.append(estado)
    sql += " ORDER BY fecha_vencimiento DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def get_fianza(fianza_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM rrhh_carta_fianza WHERE id = %s", (fianza_id,)).fetchone()
        return dict(r) if r else None


def crear_fianza(*, banco: str, monto: float,
                  fecha_emision: date, fecha_vencimiento: date,
                  numero_carta: Optional[str] = None,
                  moneda: str = 'PEN',
                  uit_referencia: Optional[float] = None,
                  num_uit: Optional[float] = None,
                  archivo_pdf_url: Optional[str] = None,
                  observaciones: Optional[str] = None,
                  creada_por: Optional[int] = None) -> int:
    """Crea una carta fianza. NIVEL EMPRESA (proyecto_id = NULL).

    FIX auditoria Opus 4.8 (P1-1): la carta fianza de 5 UIT respalda a
    PAZGUARD como empresa ante SUCAMEC, no a un contrato/proyecto.
    """
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_carta_fianza
                (proyecto_id, banco, numero_carta, monto, moneda,
                 uit_referencia, num_uit, fecha_emision, fecha_vencimiento,
                 archivo_pdf_url, observaciones, creada_por)
               VALUES (NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (banco, numero_carta, monto, moneda,
             uit_referencia, num_uit, fecha_emision, fecha_vencimiento,
             archivo_pdf_url, observaciones, creada_por)
        ).fetchone()
        return r['id']


def actualizar_fianza(fianza_id: int, **campos):
    if not campos:
        return False
    sets = []
    params = []
    for k, v in campos.items():
        sets.append(f"{k} = %s")
        params.append(v)
    sets.append("actualizada_en = NOW()")
    params.append(fianza_id)
    with get_conn() as conn:
        r = conn.execute(
            f"UPDATE rrhh_carta_fianza SET {', '.join(sets)} WHERE id = %s",
            tuple(params)
        )
        return r.rowcount > 0


# ═════════════════════════════════════════════════════════════
# Bitacora de alertas (idempotencia)
# ═════════════════════════════════════════════════════════════

def alerta_ya_enviada(entidad_tipo: str, entidad_id: int,
                       dias_restantes: int, canal: str = 'telegram') -> bool:
    with get_conn() as conn:
        r = conn.execute(
            """SELECT 1 FROM rrhh_alerta_enviada
               WHERE entidad_tipo=%s AND entidad_id=%s
                 AND dias_restantes=%s AND canal=%s""",
            (entidad_tipo, entidad_id, dias_restantes, canal)
        ).fetchone()
        return r is not None


def registrar_alerta(entidad_tipo: str, entidad_id: int,
                      dias_restantes: int, canal: str = 'telegram',
                      destinatario: Optional[str] = None):
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO rrhh_alerta_enviada
                    (entidad_tipo, entidad_id, dias_restantes, canal, destinatario)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (entidad_tipo, entidad_id, dias_restantes, canal, destinatario)
            )
    except Exception as e:
        logger.warning(f"registrar_alerta fallo: {e}")


# ═════════════════════════════════════════════════════════════
# Helpers de vencimientos
# ═════════════════════════════════════════════════════════════

def vencimientos_proximos(dias_horizonte: int = 90):
    """Retorna lista unificada de modalidades + fianzas que vencen pronto.

    Cada item es dict con: tipo, id, descripcion, fecha_vencimiento, dias_restantes.

    NIVEL EMPRESA (fix auditoria Opus 4.8 P1-1): modalidades y carta fianza son
    de PAZGUARD como empresa, NO por proyecto/contrato. Por eso NO se filtra por
    proyecto: una sola autorizacion y una sola fianza respaldan a toda la
    operacion. Cuando se agreguen vigencias de PERSONAL (Fase 4.2, que SI son
    por proyecto/asignacion), esas usaran su propio filtro por proyecto.
    """
    hoy = date.today()
    horizonte = hoy + timedelta(days=dias_horizonte)
    items = []

    with get_conn() as conn:
        # Modalidades (empresa)
        rows = conn.execute(
            """SELECT id, nombre, codigo, fecha_vencimiento, resolucion_sucamec
               FROM rrhh_modalidad
               WHERE activa = TRUE
                 AND fecha_vencimiento IS NOT NULL
                 AND fecha_vencimiento <= %s
               ORDER BY fecha_vencimiento""",
            (horizonte,)
        ).fetchall()
        for r in rows:
            items.append({
                'tipo': 'modalidad',
                'id': r['id'],
                'descripcion': f"Modalidad {r['nombre']} (Res. {r['resolucion_sucamec'] or 's/n'})",
                'fecha_vencimiento': r['fecha_vencimiento'],
                'dias_restantes': (r['fecha_vencimiento'] - hoy).days,
            })

        # Fianzas (empresa)
        rows = conn.execute(
            """SELECT id, banco, numero_carta, monto, moneda, fecha_vencimiento
               FROM rrhh_carta_fianza
               WHERE estado = 'vigente'
                 AND fecha_vencimiento <= %s
               ORDER BY fecha_vencimiento""",
            (horizonte,)
        ).fetchall()
        for r in rows:
            items.append({
                'tipo': 'fianza',
                'id': r['id'],
                'descripcion': f"Carta Fianza {r['banco']} #{r['numero_carta'] or 's/n'} "
                               f"({r['moneda']} {r['monto']:,.2f})",
                'fecha_vencimiento': r['fecha_vencimiento'],
                'dias_restantes': (r['fecha_vencimiento'] - hoy).days,
            })

        # Vigencias de PERSONAL (Fase 4.2) — nivel persona. Solo trabajadores
        # activos. El link del dashboard va a la ficha del trabajador.
        rows = conn.execute(
            """SELECT v.id, v.tipo, v.fecha_vencimiento, v.dni, e.nombre_completo
               FROM rrhh_vigencia v
               JOIN empleados_pazguard e ON e.dni = v.dni
               WHERE e.fecha_salida IS NULL
                 AND v.fecha_vencimiento IS NOT NULL
                 AND v.fecha_vencimiento <= %s
               ORDER BY v.fecha_vencimiento""",
            (horizonte,)
        ).fetchall()
        for r in rows:
            nombre_tipo = TIPOS_VIGENCIA_DICT.get(r['tipo'], r['tipo'])
            items.append({
                'tipo': 'vigencia',
                'id': r['id'],
                'dni': r['dni'],
                'descripcion': f"{nombre_tipo} — {r['nombre_completo']} (DNI {r['dni']})",
                'fecha_vencimiento': r['fecha_vencimiento'],
                'dias_restantes': (r['fecha_vencimiento'] - hoy).days,
            })

        # Polvorines (Fase 4.3) — vigencia de autorización SUCAMEC (empresa)
        rows = conn.execute(
            """SELECT id, nombre, autorizacion_sucamec, vigencia_autorizacion
               FROM rrhh_polvorin
               WHERE activo = TRUE
                 AND vigencia_autorizacion IS NOT NULL
                 AND vigencia_autorizacion <= %s
               ORDER BY vigencia_autorizacion""",
            (horizonte,)
        ).fetchall()
        for r in rows:
            items.append({
                'tipo': 'polvorin',
                'id': r['id'],
                'descripcion': f"Autorización polvorín {r['nombre']} "
                               f"({r['autorizacion_sucamec'] or 's/n'})",
                'fecha_vencimiento': r['vigencia_autorizacion'],
                'dias_restantes': (r['vigencia_autorizacion'] - hoy).days,
            })

    return sorted(items, key=lambda x: x['dias_restantes'])


def stats_compliance() -> dict:
    """Conteos para el dashboard del semaforo (nivel empresa).

    FIX auditoria Opus 4.8 (P3): de 6 queries separadas a 2 (una por tabla)
    usando COUNT(*) FILTER. modalidades/fianza son de empresa -> sin filtro
    de proyecto.
    """
    with get_conn() as conn:
        m = conn.execute(
            """SELECT
                 COUNT(*) FILTER (WHERE activa) AS vigentes,
                 COUNT(*) FILTER (WHERE activa AND fecha_vencimiento
                     BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days') AS por_vencer,
                 COUNT(*) FILTER (WHERE activa AND fecha_vencimiento < CURRENT_DATE) AS vencidas
               FROM rrhh_modalidad"""
        ).fetchone()
        f = conn.execute(
            """SELECT
                 COUNT(*) FILTER (WHERE estado = 'vigente') AS vigentes,
                 COUNT(*) FILTER (WHERE estado = 'vigente' AND fecha_vencimiento
                     BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days') AS por_vencer,
                 COUNT(*) FILTER (WHERE estado = 'vigente' AND fecha_vencimiento < CURRENT_DATE) AS vencidas
               FROM rrhh_carta_fianza"""
        ).fetchone()

        mod_vigentes = m['vigentes']
        mod_por_vencer = m['por_vencer']
        mod_vencidas = m['vencidas']
        fianzas_vigentes = f['vigentes']
        fianzas_por_vencer = f['por_vencer']
        fianzas_vencidas = f['vencidas']

    return {
        'modalidades': {
            'vigentes': mod_vigentes,
            'por_vencer': mod_por_vencer,
            'vencidas': mod_vencidas,
        },
        'fianzas': {
            'vigentes': fianzas_vigentes,
            'por_vencer': fianzas_por_vencer,
            'vencidas': fianzas_vencidas,
        },
    }


# ═════════════════════════════════════════════════════════════
# FASE 4.2 — PERSONAL VIGILANTE (empleados_pazguard del core)
# ═════════════════════════════════════════════════════════════
# El trabajador vive en empleados_pazguard (core, dni PK, compartido en toda
# la suite). El satelite RRHH lo gestiona aqui. Solo tocamos los campos
# relevantes a SUCAMEC; los de planilla (afp, banco, cts) se llenaran en
# Fase 4.4.

_CAMPOS_TRABAJADOR = (
    'nombre_completo', 'apellido_paterno', 'apellido_materno', 'nombres',
    'tipo_documento', 'fecha_nacimiento', 'sexo', 'telefono', 'email',
    'direccion', 'fecha_ingreso', 'fecha_salida', 'cargo_base', 'foto_url',
    'observaciones',
)


def listar_personal(solo_activos: bool = True):
    """Lista trabajadores. Activo = fecha_salida IS NULL."""
    sql = "SELECT * FROM empleados_pazguard WHERE 1=1"
    if solo_activos:
        sql += " AND fecha_salida IS NULL"
    sql += " ORDER BY apellido_paterno NULLS LAST, nombre_completo"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_trabajador(dni: str):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM empleados_pazguard WHERE dni = %s", (dni,)
        ).fetchone()
        return dict(r) if r else None


def crear_trabajador(*, dni: str, nombre_completo: str, **campos) -> str:
    """Crea un trabajador en empleados_pazguard. dni es PK (UniqueViolation
    si ya existe -> el caller la captura).
    """
    cols = ['dni', 'nombre_completo']
    vals = [dni, nombre_completo]
    for k, v in campos.items():
        if k in _CAMPOS_TRABAJADOR and v is not None:
            cols.append(k)
            vals.append(v)
    placeholders = ', '.join(['%s'] * len(vals))
    collist = ', '.join(cols)
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO empleados_pazguard ({collist}) VALUES ({placeholders})",
            tuple(vals)
        )
    return dni


def actualizar_trabajador(dni: str, **campos) -> bool:
    sets, params = [], []
    for k, v in campos.items():
        if k in _CAMPOS_TRABAJADOR:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return False
    sets.append("actualizado_en = NOW()")
    params.append(dni)
    with get_conn() as conn:
        r = conn.execute(
            f"UPDATE empleados_pazguard SET {', '.join(sets)} WHERE dni = %s",
            tuple(params)
        )
        return r.rowcount > 0


# ── Vigencias del trabajador ──────────────────────────────────

def listar_vigencias(dni: str):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM rrhh_vigencia WHERE dni = %s ORDER BY tipo", (dni,)
        ).fetchall()]


def get_vigencia(vigencia_id: int):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM rrhh_vigencia WHERE id = %s", (vigencia_id,)
        ).fetchone()
        return dict(r) if r else None


def upsert_vigencia(*, dni: str, tipo: str,
                     numero_doc: Optional[str] = None,
                     entidad_emisora: Optional[str] = None,
                     fecha_emision: Optional[date] = None,
                     fecha_vencimiento: Optional[date] = None,
                     archivo_pdf_url: Optional[str] = None,
                     observaciones: Optional[str] = None,
                     creada_por: Optional[int] = None) -> int:
    """Crea o actualiza la vigencia (dni, tipo). Por el indice unico
    (dni, tipo) usamos ON CONFLICT para renovar la misma fila (no duplicar
    carnes). Retorna el id de la fila.
    """
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_vigencia
                (dni, tipo, numero_doc, entidad_emisora, fecha_emision,
                 fecha_vencimiento, archivo_pdf_url, observaciones, creada_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (dni, tipo) DO UPDATE SET
                 numero_doc = EXCLUDED.numero_doc,
                 entidad_emisora = EXCLUDED.entidad_emisora,
                 fecha_emision = EXCLUDED.fecha_emision,
                 fecha_vencimiento = EXCLUDED.fecha_vencimiento,
                 archivo_pdf_url = EXCLUDED.archivo_pdf_url,
                 observaciones = EXCLUDED.observaciones,
                 actualizada_en = NOW()
               RETURNING id""",
            (dni, tipo, numero_doc, entidad_emisora, fecha_emision,
             fecha_vencimiento, archivo_pdf_url, observaciones, creada_por)
        ).fetchone()
        return r['id']


def eliminar_vigencia(vigencia_id: int) -> bool:
    with get_conn() as conn:
        r = conn.execute("DELETE FROM rrhh_vigencia WHERE id = %s", (vigencia_id,))
        return r.rowcount > 0


# ── Estado de HABILITACIÓN del vigilante ──────────────────────

def estado_habilitacion(dni: str) -> dict:
    """Calcula si un vigilante esta habilitado para operar.

    HABILITADO: todas las vigencias obligatorias presentes y vigentes.
    ATENCION:   todas presentes/vigentes pero alguna obligatoria vence < 60d.
    NO_HABILITADO: falta una obligatoria o hay alguna vencida.

    Una vigencia sin fecha_vencimiento (ej. DNI) se considera permanente.
    """
    hoy = date.today()
    vigencias = {v['tipo']: v for v in listar_vigencias(dni)}

    faltantes, vencidas, por_vencer = [], [], []
    for tipo in TIPOS_VIGENCIA_OBLIGATORIAS:
        v = vigencias.get(tipo)
        nombre = TIPOS_VIGENCIA_DICT.get(tipo, tipo)
        if not v:
            faltantes.append(nombre)
            continue
        fv = v.get('fecha_vencimiento')
        if fv is None:
            continue  # permanente
        if fv < hoy:
            vencidas.append({'nombre': nombre, 'fecha': fv})
        elif (fv - hoy).days <= 60:
            por_vencer.append({'nombre': nombre, 'fecha': fv, 'dias': (fv - hoy).days})

    from app.config import clasificar_habilitacion
    estado = clasificar_habilitacion(faltantes, vencidas, por_vencer)

    return {
        'estado': estado,
        'faltantes': faltantes,
        'vencidas': vencidas,
        'por_vencer': por_vencer,
        'total_obligatorias': len(TIPOS_VIGENCIA_OBLIGATORIAS),
        'registradas': len([t for t in TIPOS_VIGENCIA_OBLIGATORIAS if t in vigencias]),
    }


def stats_personal() -> dict:
    """Conteos de personal por estado de habilitacion (1 query agregada)."""
    n_oblig = len(TIPOS_VIGENCIA_OBLIGATORIAS)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT e.dni,
                 COUNT(v.id) FILTER (
                   WHERE v.tipo = ANY(%(ob)s)
                     AND (v.fecha_vencimiento IS NULL OR v.fecha_vencimiento >= CURRENT_DATE)
                 ) AS oblig_ok,
                 COUNT(v.id) FILTER (
                   WHERE v.tipo = ANY(%(ob)s)
                     AND v.fecha_vencimiento BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days'
                 ) AS oblig_pv
               FROM empleados_pazguard e
               LEFT JOIN rrhh_vigencia v ON v.dni = e.dni
               WHERE e.fecha_salida IS NULL
               GROUP BY e.dni""",
            {'ob': TIPOS_VIGENCIA_OBLIGATORIAS}
        ).fetchall()

    total = len(rows)
    habilitados = atencion = no_habilitados = 0
    for r in rows:
        if r['oblig_ok'] < n_oblig:
            no_habilitados += 1
        elif r['oblig_pv'] > 0:
            atencion += 1
        else:
            habilitados += 1

    return {
        'total': total,
        'habilitados': habilitados,
        'atencion': atencion,
        'no_habilitados': no_habilitados,
    }


# ═════════════════════════════════════════════════════════════
# FASE 4.3 — ARMERÍA SUCAMEC
# ═════════════════════════════════════════════════════════════

class ReglaArmeria(Exception):
    """Violación de una regla de negocio de armería (mensaje para el usuario)."""


# ── Polvorín ──────────────────────────────────────────────────

def listar_polvorines(solo_activos: bool = True):
    sql = "SELECT * FROM rrhh_polvorin"
    if solo_activos:
        sql += " WHERE activo = TRUE"
    sql += " ORDER BY nombre"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_polvorin(polvorin_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM rrhh_polvorin WHERE id = %s", (polvorin_id,)).fetchone()
        return dict(r) if r else None


def crear_polvorin(*, nombre: str, direccion=None, capacidad_max=None,
                    autorizacion_sucamec=None, vigencia_autorizacion=None,
                    creado_por=None) -> int:
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_polvorin
                (nombre, direccion, capacidad_max, autorizacion_sucamec,
                 vigencia_autorizacion, creado_por)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (nombre, direccion, capacidad_max, autorizacion_sucamec,
             vigencia_autorizacion, creado_por)
        ).fetchone()
        return r['id']


# ── Armas ─────────────────────────────────────────────────────

def listar_armas(estado: Optional[str] = None):
    """Lista armas con su asignación abierta (vigilante actual) si la hay."""
    sql = """
        SELECT a.*,
               aa.dni AS asignada_dni,
               e.nombre_completo AS asignada_a,
               aa.fecha_salida AS asignada_desde
        FROM rrhh_arma a
        LEFT JOIN rrhh_asignacion_arma aa
               ON aa.arma_id = a.id AND aa.fecha_retorno IS NULL
        LEFT JOIN empleados_pazguard e ON e.dni = aa.dni
        WHERE 1=1
    """
    params = []
    if estado:
        sql += " AND a.estado = %s"
        params.append(estado)
    sql += " ORDER BY a.marca NULLS LAST, a.modelo NULLS LAST, a.id"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def get_arma(arma_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM rrhh_arma WHERE id = %s", (arma_id,)).fetchone()
        return dict(r) if r else None


def crear_arma(*, marca=None, modelo=None, calibre=None, serie=None, anio=None,
                tpa=None, estado='operativa', fecha_adquisicion=None,
                polvorin_id=None, observaciones=None, creado_por=None) -> int:
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_arma
                (tpa, marca, modelo, calibre, serie, anio, estado,
                 fecha_adquisicion, polvorin_id, observaciones, creado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (tpa, marca, modelo, calibre, serie, anio, estado,
             fecha_adquisicion, polvorin_id, observaciones, creado_por)
        ).fetchone()
        return r['id']


def actualizar_arma(arma_id: int, **campos) -> bool:
    permitidos = {'tpa', 'marca', 'modelo', 'calibre', 'serie', 'anio', 'estado',
                  'fecha_adquisicion', 'polvorin_id', 'observaciones'}
    sets, params = [], []
    for k, v in campos.items():
        if k in permitidos:
            sets.append(f"{k} = %s")
            params.append(v)
    if not sets:
        return False
    sets.append("actualizado_en = NOW()")
    params.append(arma_id)
    with get_conn() as conn:
        r = conn.execute(
            f"UPDATE rrhh_arma SET {', '.join(sets)} WHERE id = %s", tuple(params))
        return r.rowcount > 0


def asignacion_abierta_de_arma(arma_id: int):
    with get_conn() as conn:
        r = conn.execute(
            """SELECT aa.*, e.nombre_completo
               FROM rrhh_asignacion_arma aa
               LEFT JOIN empleados_pazguard e ON e.dni = aa.dni
               WHERE aa.arma_id = %s AND aa.fecha_retorno IS NULL""",
            (arma_id,)
        ).fetchone()
        return dict(r) if r else None


def historial_asignaciones(arma_id: Optional[int] = None, dni: Optional[str] = None,
                            limite: int = 200):
    """Libro de armas: historial de salidas/retornos."""
    sql = """
        SELECT aa.*, e.nombre_completo,
               a.marca, a.modelo, a.calibre, a.serie, a.tpa
        FROM rrhh_asignacion_arma aa
        LEFT JOIN empleados_pazguard e ON e.dni = aa.dni
        LEFT JOIN rrhh_arma a ON a.id = aa.arma_id
        WHERE 1=1
    """
    params = []
    if arma_id:
        sql += " AND aa.arma_id = %s"
        params.append(arma_id)
    if dni:
        sql += " AND aa.dni = %s"
        params.append(dni)
    sql += " ORDER BY aa.fecha_salida DESC LIMIT %s"
    params.append(limite)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def asignar_arma(*, arma_id: int, dni: str, puesto=None, municion_entregada=None,
                  observaciones=None, registrado_por=None) -> int:
    """Entrega un arma a un vigilante. Reglas (compliance estricto):
      - El arma debe estar OPERATIVA.
      - El arma no puede tener otra asignación abierta.
      - El vigilante DEBE estar HABILITADO (vigencias SUCAMEC al día).
    Lanza ReglaArmeria con mensaje claro si no se cumple.
    """
    arma = get_arma(arma_id)
    if not arma:
        raise ReglaArmeria("El arma no existe.")
    if arma['estado'] != ARMA_ESTADO_OPERATIVA:
        raise ReglaArmeria(f"El arma no está operativa (estado: {arma['estado']}). No se puede asignar.")
    if asignacion_abierta_de_arma(arma_id):
        raise ReglaArmeria("El arma ya está asignada y no ha sido devuelta.")
    if not get_trabajador(dni):
        raise ReglaArmeria("El vigilante no existe.")
    hab = estado_habilitacion(dni)
    if hab['estado'] == HAB_NO_HABILITADO:
        detalle = []
        if hab['faltantes']:
            detalle.append("falta " + ", ".join(hab['faltantes']))
        if hab['vencidas']:
            detalle.append("vencido " + ", ".join(v['nombre'] for v in hab['vencidas']))
        raise ReglaArmeria(
            "El vigilante NO está habilitado para portar arma ("
            + "; ".join(detalle) + "). Regulariza sus vigencias antes de asignar."
        )
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_asignacion_arma
                (arma_id, dni, puesto, municion_entregada, observaciones, registrado_por)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (arma_id, dni, puesto, municion_entregada, observaciones, registrado_por)
        ).fetchone()
        return r['id']


def devolver_arma(asignacion_id: int, municion_devuelta=None, observaciones=None) -> bool:
    with get_conn() as conn:
        sets = ["fecha_retorno = NOW()"]
        params = []
        if municion_devuelta is not None:
            sets.append("municion_devuelta = %s")
            params.append(municion_devuelta)
        if observaciones:
            sets.append("observaciones = COALESCE(observaciones,'') || %s")
            params.append(f" | retorno: {observaciones}")
        params.append(asignacion_id)
        r = conn.execute(
            f"UPDATE rrhh_asignacion_arma SET {', '.join(sets)} "
            f"WHERE id = %s AND fecha_retorno IS NULL",
            tuple(params)
        )
        return r.rowcount > 0


# ── Munición ──────────────────────────────────────────────────

def listar_lotes_municion():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM rrhh_municion_lote ORDER BY calibre, fecha_ingreso DESC NULLS LAST"
        ).fetchall()]


def get_lote_municion(lote_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM rrhh_municion_lote WHERE id = %s", (lote_id,)).fetchone()
        return dict(r) if r else None


def crear_lote_municion(*, calibre: str, cantidad_inicial: int, fecha_ingreso=None,
                         proveedor=None, polvorin_id=None, observaciones=None,
                         creado_por=None) -> int:
    """Crea lote + movimiento 'ingreso' inicial."""
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_municion_lote
                (calibre, cantidad_inicial, cantidad_actual, fecha_ingreso,
                 proveedor, polvorin_id, observaciones, creado_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (calibre, cantidad_inicial, cantidad_inicial, fecha_ingreso,
             proveedor, polvorin_id, observaciones, creado_por)
        ).fetchone()
        lote_id = r['id']
        conn.execute(
            """INSERT INTO rrhh_municion_movimiento (lote_id, tipo, cantidad, motivo, registrado_por)
               VALUES (%s, 'ingreso', %s, 'Ingreso inicial del lote', %s)""",
            (lote_id, cantidad_inicial, creado_por)
        )
        return lote_id


def registrar_movimiento_municion(*, lote_id: int, tipo: str, cantidad: int,
                                    dni=None, motivo=None, registrado_por=None) -> int:
    """Registra movimiento y ajusta cantidad_actual segun el signo del tipo.
    No permite dejar saldo negativo.
    """
    if cantidad <= 0:
        raise ReglaArmeria("La cantidad debe ser mayor a cero.")
    signo = MUNICION_MOV_SIGNO.get(tipo)
    if signo is None:
        raise ReglaArmeria("Tipo de movimiento inválido.")
    delta = signo * cantidad
    with get_conn() as conn:
        lote = conn.execute(
            "SELECT cantidad_actual FROM rrhh_municion_lote WHERE id = %s", (lote_id,)
        ).fetchone()
        if not lote:
            raise ReglaArmeria("El lote no existe.")
        nuevo = lote['cantidad_actual'] + delta
        if nuevo < 0:
            raise ReglaArmeria(
                f"Saldo insuficiente: hay {lote['cantidad_actual']} y se intentó descontar {cantidad}.")
        conn.execute(
            "UPDATE rrhh_municion_lote SET cantidad_actual = %s WHERE id = %s",
            (nuevo, lote_id))
        r = conn.execute(
            """INSERT INTO rrhh_municion_movimiento
                (lote_id, tipo, cantidad, dni, motivo, registrado_por)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (lote_id, tipo, cantidad, dni, motivo, registrado_por)
        ).fetchone()
        return r['id']


def movimientos_de_lote(lote_id: int, limite: int = 100):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT m.*, e.nombre_completo
               FROM rrhh_municion_movimiento m
               LEFT JOIN empleados_pazguard e ON e.dni = m.dni
               WHERE m.lote_id = %s ORDER BY m.fecha DESC LIMIT %s""",
            (lote_id, limite)
        ).fetchall()]


# ── Stats armería ─────────────────────────────────────────────

def stats_armeria() -> dict:
    with get_conn() as conn:
        a = conn.execute(
            """SELECT
                 COUNT(*) AS total,
                 COUNT(*) FILTER (WHERE estado = 'operativa') AS operativas,
                 COUNT(*) FILTER (WHERE estado = 'mantenimiento') AS mantenimiento,
                 COUNT(*) FILTER (WHERE estado IN ('baja','perdida')) AS fuera
               FROM rrhh_arma"""
        ).fetchone()
        asignadas = conn.execute(
            "SELECT COUNT(*) AS n FROM rrhh_asignacion_arma WHERE fecha_retorno IS NULL"
        ).fetchone()['n']
        muni = conn.execute(
            "SELECT COALESCE(SUM(cantidad_actual),0) AS saldo FROM rrhh_municion_lote"
        ).fetchone()['saldo']
    return {
        'total': a['total'],
        'operativas': a['operativas'],
        'mantenimiento': a['mantenimiento'],
        'fuera': a['fuera'],
        'asignadas': asignadas,
        'municion_saldo': int(muni),
    }
