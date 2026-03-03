from datetime import timedelta
from decimal import Decimal, ROUND_UP
from typing import Optional

from app.db.models import BitacoraVentas
from app.utils.fechas import formatear_fecha_larga, sumar_meses


SEMANAS_POR_MES = Decimal("4.33")
PLAZO_MESES_INFO_PAGOS = 18  # se puede ajustar en el futuro


# Tabla simple de planes por SKU y meses, basada en la imagen.
# Valores en pesos mexicanos.
PLANES_POR_SKU = {
    "PC-MAXICA": {
        18: {
            "precio": Decimal("16999"),
            "descuento": Decimal("0"),
            "enganche": Decimal("229"),
            "semanas": 78,
            "pago_semanal": Decimal("215"),
        },
        15: {
            "precio": Decimal("15299"),
            "descuento": Decimal("10"),
            "enganche": Decimal("349"),
            "semanas": 65,
            "pago_semanal": Decimal("230"),
        },
        12: {
            "precio": Decimal("13599"),
            "descuento": Decimal("20"),
            "enganche": Decimal("443"),
            "semanas": 52,
            "pago_semanal": Decimal("253"),
        },
        9: {
            "precio": Decimal("11899"),
            "descuento": Decimal("30"),
            "enganche": Decimal("511"),
            "semanas": 39,
            "pago_semanal": Decimal("292"),
        },
        6: {
            "precio": Decimal("10199"),
            "descuento": Decimal("40"),
            "enganche": Decimal("605"),
            "semanas": 26,
            "pago_semanal": Decimal("369"),
        },
        3: {
            "precio": Decimal("8499"),
            "descuento": Decimal("50"),
            "enganche": Decimal("699"),
            "semanas": 13,
            "pago_semanal": Decimal("600"),
        },
    }
}


def _redondear_importe(importe: Decimal) -> Decimal:
    """Redondea siempre hacia arriba a 2 decimales."""
    return importe.quantize(Decimal("0.01"), rounding=ROUND_UP)


def _redondear_entero_amigable(importe: Decimal) -> int:
    """
    Redondeo \"amigable\" para montos en pesos:
    - Redondea hacia arriba al entero más cercano.
    - Si el resultado es impar, se suma 1 para dejarlo en número par,
      facilitando que los montos quincenales sean también números cerrados.
    """
    entero = int(importe.to_integral_value(rounding=ROUND_UP))
    if entero % 2 == 1:
        entero += 1
    return entero


def calcular_info_pagos(venta: BitacoraVentas) -> Optional[dict[str, str]]:
    """
    Calcula los datos necesarios para el mensaje INFO_PAGOS.

    Reglas actuales (solo PC-MAXICA, plan de PLAZO_MESES_INFO_PAGOS meses):
    - fecha_limite = fecha_venta + 7 días.
    - pago_minimo = pago_semanal del plan.
    - importe_mensual = pago_minimo * 4.33 (semanas/mes), redondeando hacia arriba.
    - importe_quincenal = importe_mensual / 2, redondeando hacia arriba.
    """
    if not venta or not venta.fecha_venta or not venta.sku_bitacora_v:
        return None

    sku_normalizado = venta.sku_bitacora_v.strip().upper()
    planes_sku = PLANES_POR_SKU.get(sku_normalizado)
    if not planes_sku:
        return None

    plan_info_pagos = planes_sku.get(PLAZO_MESES_INFO_PAGOS)
    if not plan_info_pagos:
        return None

    pago_semanal = plan_info_pagos["pago_semanal"]

    fecha_limite = venta.fecha_venta + timedelta(days=7)

    # Cálculo base en decimales
    importe_mensual_base = pago_semanal * SEMANAS_POR_MES
    importe_mensual_entero = _redondear_entero_amigable(importe_mensual_base)

    # Quincenal como la mitad del mensual (ya par), manteniendo números fáciles
    importe_quincenal_entero = importe_mensual_entero // 2

    return {
        "fecha_limite": formatear_fecha_larga(fecha_limite),
        "pago_minimo": f"{pago_semanal:.2f}",
        "importe_quincenal": f"{Decimal(importe_quincenal_entero):.2f}",
        "importe_mensual": f"{Decimal(importe_mensual_entero):.2f}",
    }


def calcular_info_plan_3_meses(venta: BitacoraVentas) -> Optional[dict[str, str]]:
    """
    Calcula los datos necesarios para el mensaje INFO_PLAN_3_MESES
    para el SKU PC-MAXICA a 3 meses.

    - saldo = precio_plan_3m - subsidio - pago
      (subsidio y pago: NULL o 0 se tratan como 0)
    - fecha_limite_3_meses = fecha_venta + 3 meses exactos
    - importe_semanal_3m = saldo / semanas_plan_3m

    Tanto saldo como importe semanal se redondean a enteros amigables.
    """
    if not venta or not venta.fecha_venta or not venta.sku_bitacora_v:
        return None

    sku_normalizado = venta.sku_bitacora_v.strip().upper()
    planes_sku = PLANES_POR_SKU.get(sku_normalizado)
    if not planes_sku:
        return None

    plan_3_meses = planes_sku.get(3)
    if not plan_3_meses:
        return None

    precio_plan = plan_3_meses["precio"]

    # Subsidio y pago desde la venta; NULL o 0 se tratan como 0
    subsidio_raw = getattr(venta, "subsidio", None)
    pago_raw = getattr(venta, "pago", None)

    subsidio = Decimal(str(subsidio_raw)) if subsidio_raw else Decimal("0")
    pago = Decimal(str(pago_raw)) if pago_raw else Decimal("0")

    saldo_bruto = precio_plan - subsidio - pago
    if saldo_bruto < 0:
        saldo_bruto = Decimal("0")

    saldo_entero = _redondear_entero_amigable(saldo_bruto)

    semanas_plan = plan_3_meses["semanas"]
    if semanas_plan <= 0:
        return None

    importe_semanal_base = Decimal(saldo_entero) / Decimal(semanas_plan)
    importe_semanal_entero = _redondear_entero_amigable(importe_semanal_base)

    fecha_limite = sumar_meses(venta.fecha_venta, 3)

    tiene_subsidio = subsidio > 0

    return {
        "tiene_subsidio": tiene_subsidio,
        "subsidio": f"{subsidio:.2f}",
        "saldo_3_meses": f"{Decimal(saldo_entero):.2f}",
        "fecha_limite_3_meses": formatear_fecha_larga(fecha_limite),
        "importe_semanal_3m": f"{Decimal(importe_semanal_entero):.2f}",
    }

