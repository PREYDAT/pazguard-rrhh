"""Tests de la config/lógica de negocio del RRHH (sin DB)."""
from datetime import date, timedelta

from app import config


def test_estado_por_fecha():
    hoy = date.today()
    assert config.estado_por_fecha(hoy + timedelta(days=100)) == config.ESTADO_VIGENTE
    assert config.estado_por_fecha(hoy + timedelta(days=30)) == config.ESTADO_POR_VENCER
    assert config.estado_por_fecha(hoy - timedelta(days=1)) == config.ESTADO_VENCIDO
    # exactamente 60 dias = aun por_vencer (umbral inclusivo)
    assert config.estado_por_fecha(hoy + timedelta(days=60)) == config.ESTADO_POR_VENCER
    # 61 dias = vigente
    assert config.estado_por_fecha(hoy + timedelta(days=61)) == config.ESTADO_VIGENTE


def test_carta_fianza_minimo_5_uit():
    assert config.CARTA_FIANZA_MIN_UIT == 5
    assert config.CARTA_FIANZA_MIN_SOLES == config.UIT_VIGENTE * 5


def test_modalidades_incluye_vigilancia_privada():
    codigos = [c for c, _ in config.MODALIDADES_SUCAMEC]
    assert "VIGILANCIA_PRIVADA" in codigos
    assert "TRANSPORTE_VALORES" in codigos
    # 7 modalidades SUCAMEC
    assert len(config.MODALIDADES_SUCAMEC) >= 7


def test_scheduler_hora_peru_a_utc():
    # 9am Peru (UTC-5) = 14:00 UTC
    assert config.SCHEDULER_HORA_UTC == (config.SCHEDULER_HORA_PERU + 5) % 24


def test_escalones_alerta_ordenados_desc():
    # los escalones deben incluir el dia del vencimiento (0) y avisos previos
    assert 0 in config.ALERTA_DIAS
    assert 60 in config.ALERTA_DIAS
    assert 7 in config.ALERTA_DIAS


# ── Fase 4.2: vigencias de personal ──

def test_tipos_vigencia_obligatorias():
    # las 6 del plan + SCTR son obligatorias; DNI y brevete no
    assert 'carne_sucamec' in config.TIPOS_VIGENCIA_OBLIGATORIAS
    assert 'curso_basico' in config.TIPOS_VIGENCIA_OBLIGATORIAS
    assert 'sctr' in config.TIPOS_VIGENCIA_OBLIGATORIAS
    assert 'dni' not in config.TIPOS_VIGENCIA_OBLIGATORIAS
    assert 'brevete' not in config.TIPOS_VIGENCIA_OBLIGATORIAS
    assert config.TIPOS_VIGENCIA_DICT['carne_sucamec'] == 'Carné SUCAMEC'


def test_clasificar_habilitacion():
    H, A, N = config.HAB_HABILITADO, config.HAB_ATENCION, config.HAB_NO_HABILITADO
    # todo OK
    assert config.clasificar_habilitacion([], [], []) == H
    # algo por vencer pero nada faltante/vencido
    assert config.clasificar_habilitacion([], [], [{'nombre': 'x'}]) == A
    # falta una obligatoria -> no habilitado (gana sobre por_vencer)
    assert config.clasificar_habilitacion(['Carné SUCAMEC'], [], [{'nombre': 'x'}]) == N
    # hay vencida -> no habilitado
    assert config.clasificar_habilitacion([], [{'nombre': 'y'}], []) == N
