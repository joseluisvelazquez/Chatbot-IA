from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_UP
from typing import Any, Optional

from app.db.models import BitacoraVentas
from app.utils.date_formatter import formatear_fecha_larga, sumar_meses


SEMANAS_POR_MES = Decimal("4.33")
PLAZO_MESES_INFO_PAGOS = 18  # se puede ajustar en el futuro

PLANES_POR_MESES = {
    
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


def _redondear_importe(importe: Decimal) -> Decimal:
    """Redondea siempre hacia arriba a 2 decimales."""
    return importe.quantize(Decimal("0.01"), rounding=ROUND_UP)


def _redondear_entero_amigable(importe: Decimal) -> int:
    """
    Redondeo "amigable" para montos en pesos:
    - Redondea hacia arriba al entero más cercano.
    - Si el resultado es impar, se suma 1 para dejarlo en número par,
      facilitando que los montos quincenales sean también números cerrados.
    """
    entero = int(importe.to_integral_value(rounding=ROUND_UP))
    if entero % 2 == 1:
        entero += 1
    return entero


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money_or_none(value: Any) -> str | None:
    decimal_value = _decimal_or_none(value)
    return f"{decimal_value:.2f}" if decimal_value is not None else None


def _date_or_none(value: Any) -> date | datetime | None:
    if isinstance(value, (date, datetime)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return None


def _bridge_payment_snapshot(venta: Any) -> dict[str, Any]:
    payload = getattr(venta, "_bridge_payload", None)
    if not isinstance(payload, dict):
        return {}
    payment = payload.get("payment")
    return payment if isinstance(payment, dict) else {}


def _is_bridge_sale(venta: Any) -> bool:
    return getattr(venta, "_source", None) == "siga_bridge" or isinstance(getattr(venta, "_bridge_payload", None), dict)


def _fecha_venta(venta: Any) -> date | datetime | None:
    fecha = getattr(venta, "fecha_venta", None)
    if fecha:
        return _date_or_none(fecha)

    payload = getattr(venta, "_bridge_payload", None)
    if not isinstance(payload, dict):
        return None

    sale = payload.get("sale") if isinstance(payload.get("sale"), dict) else {}
    return _date_or_none(
        sale.get("fecha_venta")
        or sale.get("sale_date")
        or payload.get("fecha_venta")
    )


def _payment_money(payment: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _money_or_none(payment.get(key))
        if value is not None:
            return value
    return None


def _payment_date_text(payment: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        parsed = _date_or_none(payment.get(key))
        if parsed:
            return formatear_fecha_larga(parsed)
    return None


def calcular_info_pagos(venta: BitacoraVentas) -> Optional[dict[str, str]]:
    """
    Calcula los datos necesarios para el mensaje INFO_PAGOS.

    Reglas actuales:
    - fecha_limite = fecha_venta + 7 días.
    - pago_minimo = pago_semanal del plan.
    - importe_mensual = pago_minimo * 4.33 (semanas/mes), redondeando hacia arriba.
    - importe_quincenal = importe_mensual / 2, redondeando hacia arriba.
    """
    fecha_venta = _fecha_venta(venta)
    if not venta or not fecha_venta:
        return None

    payment = _bridge_payment_snapshot(venta)
    pago_minimo_bridge = _payment_money(payment, "pago_minimo", "minimum_payment", "pago_semanal")
    importe_quincenal_bridge = _payment_money(payment, "importe_quincenal", "pago_quincenal")
    importe_mensual_bridge = _payment_money(payment, "importe_mensual", "pago_mensual")
    fecha_limite = fecha_venta + timedelta(days=7)
    
    plan = PLANES_POR_MESES.get(PLAZO_MESES_INFO_PAGOS)
    if not plan:
        return None

    pago_semanal = _decimal_or_none(pago_minimo_bridge) or plan["pago_semanal"]

    # Cálculo base en decimales
    importe_mensual_base = pago_semanal * SEMANAS_POR_MES
    importe_mensual_entero = _redondear_entero_amigable(importe_mensual_base)

    # Quincenal como la mitad del mensual (ya par), manteniendo números fáciles
    importe_quincenal_entero = importe_mensual_entero // 2

    return {
        "fecha_limite": formatear_fecha_larga(fecha_limite),
        "pago_minimo": pago_minimo_bridge or f"{pago_semanal:.2f}",
        "importe_quincenal": importe_quincenal_bridge or f"{Decimal(importe_quincenal_entero):.2f}",
        "importe_mensual": importe_mensual_bridge or f"{Decimal(importe_mensual_entero):.2f}",
    }


def calcular_info_plan_3_meses(venta: BitacoraVentas) -> Optional[dict[str, str]]:
    """
    Calcula los datos necesarios para el mensaje INFO_PLAN_3_MESES

    - saldo = precio_plan_3m - subsidio - pago
      (subsidio y pago: NULL o 0 se tratan como 0)
    - fecha_limite_3_meses = fecha_venta + 3 meses exactos
    - importe_semanal_3m = saldo / semanas_plan_3m

    Tanto saldo como importe semanal se redondean a enteros amigables.
    """
    fecha_venta = _fecha_venta(venta)
    if not venta or not fecha_venta:
        return None

    plan_3_meses = PLANES_POR_MESES.get(3)
    if not plan_3_meses:
        return None

    is_bridge = _is_bridge_sale(venta)
    payment = _bridge_payment_snapshot(venta)
    saldo_bridge = _payment_money(payment, "saldo_3_meses", "saldo_3m", "saldo_plan_3_meses")
    subsidio_bridge = _payment_money(payment, "subsidio", "descuento")
    importe_semanal_bridge = _payment_money(payment, "importe_semanal_3m", "pago_semanal_3m", "semanal_3_meses")
    fecha_limite_bridge = _payment_date_text(
        payment,
        "fecha_limite_3_meses",
        "fecha_limite_3m",
        "limite_3_meses",
    )
    precio_plan = plan_3_meses["precio"]

    # Subsidio y pago desde la venta; NULL o 0 se tratan como 0
    subsidio_raw = _decimal_or_none(subsidio_bridge) if is_bridge else venta.subsidio
    pago_raw = venta.pago

    subsidio = Decimal(str(subsidio_raw)) if subsidio_raw else Decimal("0")
    pago = Decimal(str(pago_raw)) if pago_raw else Decimal("0")

    saldo_bruto = _decimal_or_none(saldo_bridge) if is_bridge and saldo_bridge else None
    if saldo_bruto is None:
        saldo_bruto = precio_plan - subsidio - pago
    if saldo_bruto < 0:
        saldo_bruto = Decimal("0")

    saldo_entero = _redondear_entero_amigable(saldo_bruto)

    semanas_plan = plan_3_meses["semanas"]
    if semanas_plan <= 0:
        return None

    importe_semanal_entero = _decimal_or_none(importe_semanal_bridge)
    if importe_semanal_entero is None:
        importe_semanal_base = Decimal(saldo_entero) / Decimal(semanas_plan)
        importe_semanal_entero = Decimal(_redondear_entero_amigable(importe_semanal_base))

    fecha_limite = sumar_meses(fecha_venta, 3)

    tiene_subsidio = subsidio > 0

    return {
        "tiene_subsidio": tiene_subsidio,
        "subsidio": f"{subsidio:.2f}",
        "saldo_3_meses": saldo_bridge or f"{Decimal(saldo_entero):.2f}",
        "fecha_limite_3_meses": fecha_limite_bridge or formatear_fecha_larga(fecha_limite),
        "importe_semanal_3m": importe_semanal_bridge or f"{Decimal(importe_semanal_entero):.2f}",
    }

