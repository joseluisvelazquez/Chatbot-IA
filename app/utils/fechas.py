from datetime import date, datetime
import calendar


MESES_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}


def formatear_fecha_larga(fecha: date | datetime) -> str:
    """
    Devuelve una fecha en formato natural en español, por ejemplo:
    2 de marzo del 2026
    """
    if isinstance(fecha, datetime):
        fecha = fecha.date()

    nombre_mes = MESES_ES.get(fecha.month, "")
    return f"{fecha.day} de {nombre_mes} del {fecha.year}"


def sumar_meses(fecha: date | datetime, meses: int) -> date:
    """
    Suma 'meses' a una fecha, ajustando al último día del mes
    cuando el nuevo mes no tiene el mismo número de días.
    """
    if isinstance(fecha, datetime):
        base = fecha.date()
    else:
        base = fecha

    nuevo_mes_index = base.month - 1 + meses
    nuevo_anio = base.year + nuevo_mes_index // 12
    nuevo_mes = nuevo_mes_index % 12 + 1

    ultimo_dia_nuevo_mes = calendar.monthrange(nuevo_anio, nuevo_mes)[1]
    nuevo_dia = min(base.day, ultimo_dia_nuevo_mes)

    return date(nuevo_anio, nuevo_mes, nuevo_dia)

