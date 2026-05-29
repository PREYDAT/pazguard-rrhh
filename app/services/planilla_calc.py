"""Motor de cálculo de planilla — DL 728 + SCTR Riesgo III.

Función PURA (sin DB, testeable) que dado un sueldo base y parámetros legales
calcula la boleta mensual: ingresos, descuentos al trabajador, aportes del
empleador y provisiones (gratificación, CTS, vacaciones) prorrateadas.

⚠ Es una ESTIMACIÓN con los supuestos estándar de ley peruana. No reemplaza
el cálculo oficial de un contador para el PLAME; sirve para presupuesto,
control y boletas internas. Renta de 5ta categoría NO se incluye aquí
(depende de proyección anual y deducciones; se ajusta manualmente).
"""
from __future__ import annotations


def _r(x: float) -> float:
    return round(float(x or 0), 2)


def calcular_boleta(*, sueldo_base: float, sistema_pension: str = 'ONP',
                     tiene_asig_familiar: bool = False,
                     otros_ingresos: float = 0.0,
                     otros_descuentos: float = 0.0,
                     params: dict) -> dict:
    """Calcula la boleta mensual de un trabajador.

    Returns dict con ingresos, descuentos, aportes empleador, provisiones,
    neto y costo total para la empresa.
    """
    sueldo_base = float(sueldo_base or 0)
    asig = params['asignacion_familiar'] if tiene_asig_familiar else 0.0
    otros_ingresos = float(otros_ingresos or 0)
    total_ingresos = sueldo_base + asig + otros_ingresos
    base = total_ingresos  # remuneración computable (aprox)

    sp = (sistema_pension or 'ONP').upper()
    if sp == 'ONP':
        aporte = base * params['onp']
        comision = 0.0
        prima = 0.0
        desc_pension = aporte
    elif sp == 'AFP':
        aporte = base * params['afp_aporte']
        comision = base * params['afp_comision']
        prima = base * params['afp_prima']
        desc_pension = aporte + comision + prima
    else:  # SIN sistema
        aporte = comision = prima = desc_pension = 0.0

    otros_descuentos = float(otros_descuentos or 0)
    total_descuentos = desc_pension + otros_descuentos
    neto = total_ingresos - total_descuentos

    # Aportes del empleador (no se descuentan al trabajador)
    essalud = base * params['essalud']
    sctr_salud = base * params['sctr_salud']
    sctr_pension = base * params['sctr_pension']
    aportes_empleador = essalud + sctr_salud + sctr_pension

    # Provisiones mensuales (prorrateadas) — costo diferido real
    # Gratificación: 2 sueldos/año => sueldo/6 por mes; + 9% bonif extraordinaria.
    grati_mensual = total_ingresos / 6.0
    grati_bonif = grati_mensual * params['grati_bonif_extra']
    # CTS: ~ (sueldo + 1/6 grati) / 12 por mes.
    cts_mensual = (total_ingresos + total_ingresos / 6.0) / 12.0
    # Vacaciones: 1 sueldo/año => sueldo/12 por mes.
    vac_mensual = total_ingresos / 12.0
    provisiones = grati_mensual + grati_bonif + cts_mensual + vac_mensual

    costo_empresa = total_ingresos + aportes_empleador + provisiones

    return {
        'sueldo_base': _r(sueldo_base),
        'asig_familiar': _r(asig),
        'otros_ingresos': _r(otros_ingresos),
        'total_ingresos': _r(total_ingresos),
        'sistema_pension': sp,
        'aporte_pension': _r(aporte),
        'comision_afp': _r(comision),
        'prima_seguro': _r(prima),
        'desc_pension': _r(desc_pension),
        'otros_descuentos': _r(otros_descuentos),
        'total_descuentos': _r(total_descuentos),
        'neto': _r(neto),
        'essalud': _r(essalud),
        'sctr_salud': _r(sctr_salud),
        'sctr_pension': _r(sctr_pension),
        'aportes_empleador': _r(aportes_empleador),
        'provision_grati': _r(grati_mensual + grati_bonif),
        'provision_cts': _r(cts_mensual),
        'provision_vacaciones': _r(vac_mensual),
        'provisiones': _r(provisiones),
        'costo_empresa': _r(costo_empresa),
    }


MESES_ES = [
    '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre',
]
