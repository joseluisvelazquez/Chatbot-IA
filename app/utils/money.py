from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _clean_money_text(value: str) -> str:
    return value.replace("$", "").replace(",", "").strip()


def format_money(value: Any) -> str:
    """
    Formatea montos para mensajes al cliente.

    Devuelve siempre "$#,##0.00" cuando el valor es numerico. Si el valor no se
    puede interpretar como monto, regresa el texto original sin romper el flujo.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        normalized = _clean_money_text(text)
    else:
        text = str(value)
        normalized = text.strip()

    if not normalized:
        return ""

    try:
        amount = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return text

    return f"${amount:,.2f}"
