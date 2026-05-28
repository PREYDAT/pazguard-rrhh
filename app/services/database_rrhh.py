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

def listar_modalidades(proyecto_id: Optional[int] = None, solo_activas: bool = True):
    """Lista modalidades. Filtra por proyecto y activas."""
    sql = "SELECT * FROM rrhh_modalidad WHERE 1=1"
    params = []
    if proyecto_id is not None:
        sql += " AND proyecto_id = %s"
        params.append(proyecto_id)
    if solo_activas:
        sql += " AND activa = TRUE"
    sql += " ORDER BY fecha_vencimiento NULLS LAST, nombre"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def get_modalidad(modalidad_id: int):
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM rrhh_modalidad WHERE id = %s", (modalidad_id,)).fetchone()
        return dict(r) if r else None


def crear_modalidad(*, proyecto_id: int, codigo: str, nombre: str,
                     resolucion_sucamec: Optional[str] = None,
                     fecha_otorgamiento: Optional[date] = None,
                     fecha_vencimiento: Optional[date] = None,
                     alcance_geografico: Optional[str] = None,
                     archivo_pdf_url: Optional[str] = None,
                     observaciones: Optional[str] = None,
                     creada_por: Optional[int] = None) -> int:
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_modalidad
                (proyecto_id, codigo, nombre, resolucion_sucamec,
                 fecha_otorgamiento, fecha_vencimiento, alcance_geografico,
                 archivo_pdf_url, observaciones, creada_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (proyecto_id, codigo, nombre, resolucion_sucamec,
             fecha_otorgamiento, fecha_vencimiento, alcance_geografico,
             archivo_pdf_url, observaciones, creada_por)
        ).fetchone()
        return r['id']


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

def listar_fianzas(proyecto_id: Optional[int] = None, estado: Optional[str] = None):
    sql = "SELECT * FROM rrhh_carta_fianza WHERE 1=1"
    params = []
    if proyecto_id is not None:
        sql += " AND proyecto_id = %s"
        params.append(proyecto_id)
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


def crear_fianza(*, proyecto_id: int, banco: str, monto: float,
                  fecha_emision: date, fecha_vencimiento: date,
                  numero_carta: Optional[str] = None,
                  moneda: str = 'PEN',
                  uit_referencia: Optional[float] = None,
                  num_uit: Optional[float] = None,
                  archivo_pdf_url: Optional[str] = None,
                  observaciones: Optional[str] = None,
                  creada_por: Optional[int] = None) -> int:
    with get_conn() as conn:
        r = conn.execute(
            """INSERT INTO rrhh_carta_fianza
                (proyecto_id, banco, numero_carta, monto, moneda,
                 uit_referencia, num_uit, fecha_emision, fecha_vencimiento,
                 archivo_pdf_url, observaciones, creada_por)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (proyecto_id, banco, numero_carta, monto, moneda,
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

def vencimientos_proximos(dias_horizonte: int = 90, proyecto_id: Optional[int] = None):
    """Retorna lista unificada de modalidades + fianzas que vencen pronto.

    Cada item es dict con: tipo, id, descripcion, fecha_vencimiento, dias_restantes.

    FIX auditoria Opus 4.8 (fuga cross-tenant): si se pasa proyecto_id, filtra
    SOLO los vencimientos de ese proyecto. El dashboard debe pasar siempre el
    proyecto activo para no mostrar vencimientos de otros proyectos/contratos.
    El scheduler de alertas pasa proyecto_id=None a proposito (alerta de todos).
    """
    hoy = date.today()
    horizonte = hoy + timedelta(days=dias_horizonte)
    items = []

    # Filtro de proyecto opcional (mismo patron para ambas queries)
    filtro_proy = " AND proyecto_id = %s" if proyecto_id is not None else ""

    with get_conn() as conn:
        # Modalidades
        params = [horizonte] + ([proyecto_id] if proyecto_id is not None else [])
        rows = conn.execute(
            f"""SELECT id, nombre, codigo, fecha_vencimiento, resolucion_sucamec
               FROM rrhh_modalidad
               WHERE activa = TRUE
                 AND fecha_vencimiento IS NOT NULL
                 AND fecha_vencimiento <= %s{filtro_proy}
               ORDER BY fecha_vencimiento""",
            tuple(params)
        ).fetchall()
        for r in rows:
            items.append({
                'tipo': 'modalidad',
                'id': r['id'],
                'descripcion': f"Modalidad {r['nombre']} (Res. {r['resolucion_sucamec'] or 's/n'})",
                'fecha_vencimiento': r['fecha_vencimiento'],
                'dias_restantes': (r['fecha_vencimiento'] - hoy).days,
            })

        # Fianzas
        params = [horizonte] + ([proyecto_id] if proyecto_id is not None else [])
        rows = conn.execute(
            f"""SELECT id, banco, numero_carta, monto, moneda, fecha_vencimiento
               FROM rrhh_carta_fianza
               WHERE estado = 'vigente'
                 AND fecha_vencimiento <= %s{filtro_proy}
               ORDER BY fecha_vencimiento""",
            tuple(params)
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

    return sorted(items, key=lambda x: x['dias_restantes'])


def stats_compliance(proyecto_id: Optional[int] = None) -> dict:
    """Retorna conteos para el dashboard del semaforo."""
    with get_conn() as conn:
        where_proy = "AND proyecto_id = %s" if proyecto_id else ""
        params = (proyecto_id,) if proyecto_id else ()

        mod_vigentes = conn.execute(
            f"SELECT COUNT(*) AS n FROM rrhh_modalidad "
            f"WHERE activa = TRUE {where_proy}",
            params
        ).fetchone()['n']

        mod_por_vencer = conn.execute(
            f"SELECT COUNT(*) AS n FROM rrhh_modalidad "
            f"WHERE activa = TRUE AND fecha_vencimiento BETWEEN CURRENT_DATE "
            f"AND CURRENT_DATE + INTERVAL '60 days' {where_proy}",
            params
        ).fetchone()['n']

        mod_vencidas = conn.execute(
            f"SELECT COUNT(*) AS n FROM rrhh_modalidad "
            f"WHERE activa = TRUE AND fecha_vencimiento < CURRENT_DATE {where_proy}",
            params
        ).fetchone()['n']

        fianzas_vigentes = conn.execute(
            f"SELECT COUNT(*) AS n FROM rrhh_carta_fianza "
            f"WHERE estado = 'vigente' {where_proy}",
            params
        ).fetchone()['n']

        fianzas_por_vencer = conn.execute(
            f"SELECT COUNT(*) AS n FROM rrhh_carta_fianza "
            f"WHERE estado = 'vigente' AND fecha_vencimiento BETWEEN CURRENT_DATE "
            f"AND CURRENT_DATE + INTERVAL '60 days' {where_proy}",
            params
        ).fetchone()['n']

        fianzas_vencidas = conn.execute(
            f"SELECT COUNT(*) AS n FROM rrhh_carta_fianza "
            f"WHERE estado = 'vigente' AND fecha_vencimiento < CURRENT_DATE {where_proy}",
            params
        ).fetchone()['n']

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
