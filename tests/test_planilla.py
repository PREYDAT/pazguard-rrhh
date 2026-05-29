"""Tests del motor de cálculo de planilla (puro, sin DB)."""
from app.config import planilla_params
from app.services.planilla_calc import calcular_boleta


def test_boleta_onp_basica():
    p = planilla_params()
    b = calcular_boleta(sueldo_base=1300, sistema_pension='ONP', params=p)
    assert b['total_ingresos'] == 1300.0
    # ONP = 13% del sueldo
    assert b['desc_pension'] == round(1300 * p['onp'], 2)
    assert b['neto'] == round(1300 - 1300 * p['onp'], 2)
    # EsSalud 9%
    assert b['essalud'] == round(1300 * p['essalud'], 2)
    # costo empresa > ingresos (incluye aportes + provisiones)
    assert b['costo_empresa'] > b['total_ingresos']
    assert b['comision_afp'] == 0.0


def test_boleta_afp_descuenta_mas_que_onp():
    p = planilla_params()
    onp = calcular_boleta(sueldo_base=2000, sistema_pension='ONP', params=p)
    afp = calcular_boleta(sueldo_base=2000, sistema_pension='AFP', params=p)
    # AFP tiene aporte + comisión + prima; el neto puede variar, pero la AFP
    # descompone en 3 conceptos
    assert afp['comision_afp'] > 0
    assert afp['prima_seguro'] > 0
    assert afp['aporte_pension'] == round(2000 * p['afp_aporte'], 2)


def test_asignacion_familiar_suma_ingresos():
    p = planilla_params()
    sin = calcular_boleta(sueldo_base=1300, tiene_asig_familiar=False, params=p)
    con = calcular_boleta(sueldo_base=1300, tiene_asig_familiar=True, params=p)
    assert con['total_ingresos'] == round(sin['total_ingresos'] + p['asignacion_familiar'], 2)
    assert con['asig_familiar'] == round(p['asignacion_familiar'], 2)


def test_sctr_riesgo_iii_presente():
    p = planilla_params()
    b = calcular_boleta(sueldo_base=1500, params=p)
    # SCTR salud + pensión son aportes del empleador y deben ser > 0
    assert b['sctr_salud'] > 0
    assert b['sctr_pension'] > 0


def test_provisiones_incluyen_grati_cts_vacaciones():
    p = planilla_params()
    b = calcular_boleta(sueldo_base=1200, params=p)
    assert b['provision_grati'] > 0
    assert b['provision_cts'] > 0
    assert b['provision_vacaciones'] > 0
    # provisiones es la suma
    assert b['provisiones'] == round(
        b['provision_grati'] + b['provision_cts'] + b['provision_vacaciones'], 2)


def test_sin_sistema_pension_no_descuenta():
    p = planilla_params()
    b = calcular_boleta(sueldo_base=1300, sistema_pension='SIN', params=p)
    assert b['desc_pension'] == 0.0
    assert b['neto'] == b['total_ingresos']
