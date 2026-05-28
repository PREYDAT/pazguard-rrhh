"""Config del sistema pazguard-rrhh.

Tipos de vencimiento manejados, UIT vigente, escalones de alerta, etc.
"""
import os
from datetime import date


# ── UIT vigente (actualizar cada anio fiscal) ─────────────────
# La carta fianza minima son 5 UIT. UIT 2025 = S/ 5,350 -> 5 UIT = S/ 26,750
# UIT 2026 se publica en diciembre 2025 via DS.
UIT_VIGENTE = float(os.environ.get('UIT_VIGENTE', '5350'))
ANIO_UIT = int(os.environ.get('ANIO_UIT', '2025'))
CARTA_FIANZA_MIN_UIT = 5
CARTA_FIANZA_MIN_SOLES = UIT_VIGENTE * CARTA_FIANZA_MIN_UIT


# ── Escalones de alerta de vencimiento (dias antes) ───────────
# Job APScheduler diario revisa y notifica si la fecha de vencimiento
# cae en alguno de estos thresholds.
ALERTA_DIAS = [90, 60, 30, 15, 7, 1, 0]
# 0 = el dia que vence
# -N = N dias vencido (post-vencimiento sigue alertando hasta resolverse)


# ── Modalidades SUCAMEC (DL 1213 + DS 005-2023-IN) ────────────
# Mapeo codigo interno -> nombre oficial. Usar codigo en URLs/filtros.
MODALIDADES_SUCAMEC = [
    ('VIGILANCIA_PRIVADA', 'Vigilancia Privada'),
    ('PROTECCION_PERSONAL', 'Proteccion Personal'),
    ('TRANSPORTE_VALORES', 'Transporte de Valores'),
    ('PROTECCION_CUENTA_PROPIA', 'Proteccion por Cuenta Propia'),
    ('TECNOLOGIA_CONSULTORIA', 'Tecnologia y Consultoria de Seguridad'),
    ('SERVICIOS_INDIVIDUALES', 'Servicios Individuales de Seguridad'),
    ('SEGURIDAD_CANES', 'Seguridad con Canes (K-9)'),
]


# ── Bancos peruanos comunes para carta fianza ─────────────────
BANCOS_FIANZA = [
    'BCP', 'BBVA', 'Interbank', 'Scotiabank', 'BanBif', 'Pichincha',
    'GNB', 'Banco de la Nacion', 'Mibanco', 'Falabella', 'Ripley',
    'Comercio', 'Citibank', 'Santander', 'ICBC', 'Otros',
]


# ── Estados ────────────────────────────────────────────────────
ESTADO_VIGENTE = 'vigente'
ESTADO_POR_VENCER = 'por_vencer'
ESTADO_VENCIDO = 'vencido'
ESTADO_RENOVADA = 'renovada'  # archivada, ya hay otra vigente


# ── Tipos de vigencia de PERSONAL vigilante (SUCAMEC + laboral) ───
# (codigo, nombre, obligatoria_para_habilitacion, vigencia_meses_tipica)
# Marco normativo: DL 1213, DS 005-2023-IN (carné, cursos), DL 728 + SCTR
# Riesgo III (vigilancia es actividad de alto riesgo).
TIPOS_VIGENCIA = [
    ('carne_sucamec',     'Carné SUCAMEC',                         True,  36),
    ('curso_basico',      'Curso Básico de Seguridad',             True,  36),
    ('perfeccionamiento', 'Curso de Perfeccionamiento',            True,  24),
    ('examen_medico',     'Examen Médico Ocupacional',             True,  12),
    ('examen_psicologico','Examen Psicológico',                    True,  12),
    ('antecedentes',      'Antecedentes (penales/policiales/jud.)', True,   6),
    ('sctr',              'SCTR (Salud + Pensión, Riesgo III)',    True,  12),
    ('dni',               'DNI',                                   False, None),
    ('brevete',           'Licencia de conducir (brevete)',        False, None),
]

# Codigos obligatorios para que un vigilante este HABILITADO a operar.
TIPOS_VIGENCIA_OBLIGATORIAS = [c for c, _, oblig, _ in TIPOS_VIGENCIA if oblig]
TIPOS_VIGENCIA_DICT = {c: n for c, n, _, _ in TIPOS_VIGENCIA}
TIPOS_VIGENCIA_MESES = {c: m for c, _, _, m in TIPOS_VIGENCIA}


# ── Estado de habilitación del vigilante (para operar) ────────
HAB_HABILITADO = 'habilitado'      # todas las obligatorias vigentes
HAB_ATENCION = 'atencion'          # todas presentes pero alguna vence < 60d
HAB_NO_HABILITADO = 'no_habilitado'  # falta una obligatoria o hay vencida


def clasificar_habilitacion(faltantes, vencidas, por_vencer) -> str:
    """Función pura (testeable sin DB) que decide el estado de habilitación.

    - NO_HABILITADO si falta alguna obligatoria o hay alguna vencida.
    - ATENCION si todas presentes/vigentes pero alguna vence pronto.
    - HABILITADO en otro caso.
    """
    if faltantes or vencidas:
        return HAB_NO_HABILITADO
    if por_vencer:
        return HAB_ATENCION
    return HAB_HABILITADO


def estado_por_fecha(fecha_vencimiento: date) -> str:
    """Devuelve el estado segun la fecha de vencimiento vs hoy."""
    if not fecha_vencimiento:
        return ESTADO_VIGENTE
    hoy = date.today()
    if fecha_vencimiento < hoy:
        return ESTADO_VENCIDO
    dias = (fecha_vencimiento - hoy).days
    if dias <= 60:
        return ESTADO_POR_VENCER
    return ESTADO_VIGENTE


# ── Sistemas validos para SSO handover ────────────────────────
SISTEMA_CODIGO = 'rrhh'  # cuando el hub llame /ir/rrhh, llega aqui


# ── Telegram ───────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_IDS = [
    s.strip() for s in (os.environ.get('TELEGRAM_CHAT_IDS', '')).split(',')
    if s.strip()
]


def telegram_listo() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS)


# ── Job scheduler ──────────────────────────────────────────────
SCHEDULER_HORA_PERU = int(os.environ.get('SCHEDULER_HORA_PERU', '9'))  # 9am Peru
SCHEDULER_MINUTO = int(os.environ.get('SCHEDULER_MINUTO', '0'))
# Peru = UTC-5
SCHEDULER_HORA_UTC = (SCHEDULER_HORA_PERU + 5) % 24
