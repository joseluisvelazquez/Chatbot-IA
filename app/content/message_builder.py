from app.content import messages
from decimal import Decimal
from app.pricing.payment_plans import PLANES_POR_MESES
from app.pricing.payment_plans import _redondear_entero_amigable
from app.utils.account_reference import format_account_reference
from app.utils.money import format_money


def _clean_access_value(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"-", "null", "none", "undefined", "no disponible"}:
        return None
    return text


def _format_money_value(value) -> str:
    return format_money(value)


class MessageBuilder:

    @staticmethod
    def confirmar_nombre(nombre: str) -> str:
        return messages.CONFIRMAR_NOMBRE.format(nombre_completo=nombre)

    @staticmethod
    def confirmar_producto(articulo: str, producto: str) -> str:
        return messages.CONFIRMAR_PRODUCTO.format(articulo=articulo, nombre_producto=producto)
    
    @staticmethod
    def confirmar_estado_producto(producto: str) -> str:
        return messages.CONFIRMAR_ESTADO_PRODUCTO.format(nombre_producto=producto)

    @staticmethod
    def confirmar_pago(pago: str) -> str:
        return messages.CONFIRMAR_PAGO.format(importe_pago_inicial=_format_money_value(pago))

    @staticmethod
    def confirmar_fecha(fecha: str) -> str:
        return messages.CONFIRMAR_FECHA.format(fecha_venta=fecha)

    @staticmethod
    def confirmar_domicilio(domicilio: str) -> str:
        return messages.CONFIRMAR_DOMICILIO.format(domicilio_completo=domicilio)

    @staticmethod
    def info_pagos(fecha_limite: str, pago_minimo: str, importe_quincenal: str, importe_mensual: str) -> str:
        return messages.INFO_PAGOS.format(
            fecha_limite=fecha_limite,
            pago_minimo=_format_money_value(pago_minimo),
            importe_quincenal=_format_money_value(importe_quincenal),
            importe_mensual=_format_money_value(importe_mensual),
        )
    
    @staticmethod
    def info_metodos_pago(numero_cuenta: str) -> str:
        cuenta = format_account_reference(numero_cuenta) or numero_cuenta
        return messages.INFO_METODOS_PAGO.format(numero_cuenta=cuenta)

    @staticmethod
    def info_comprobante_acceso(numero_cuenta: str, codigo_cliente: str | None) -> str:
        cuenta = format_account_reference(numero_cuenta)
        codigo = _clean_access_value(codigo_cliente)
        if not cuenta or not codigo:
            return messages.INFO_COMPROBANTE_ACCESO_FALLBACK
        return messages.INFO_COMPROBANTE_ACCESO.format(
            numero_cuenta=cuenta,
            codigo_cliente=codigo,
        )

    @staticmethod
    def info_plan_3_meses(saldo_3_meses: str, fecha_limite_3_meses: str, importe_semanal_3m: str, subsidio: str | None = None) -> str:
        partes = []
        if subsidio:
            partes.append(messages.INFO_PLAN_3_MESES_DESCUENTO.format(subsidio=_format_money_value(subsidio)))
        partes.append(messages.INFO_PLAN_3_MESES.format(
            saldo_3_meses=_format_money_value(saldo_3_meses),
            fecha_limite_3_meses=fecha_limite_3_meses,
            importe_semanal_3m=_format_money_value(importe_semanal_3m),
        ))
        return "".join(partes)

    @staticmethod
    def info_beneficios2(producto: str) -> str:
        return messages.INFO_BENEFICIOS2.format(producto=producto)
    
    @staticmethod
    def build_descuento_desglose(venta) -> str:

        if not venta:
            return "No se pudo obtener la información de tu cuenta."

        plan_3m = PLANES_POR_MESES.get(3)

        if not plan_3m:
            return "No se pudo obtener la información del plan."

        # Redondeo amigable para mostrar precios cerrados 
        precio = Decimal(_redondear_entero_amigable(plan_3m["precio"]))

        pago = Decimal(str(venta.pago)) if venta.pago else Decimal("0")
        subsidio = Decimal(str(venta.subsidio)) if venta.subsidio else Decimal("0")

        saldo = precio - pago - subsidio
        if saldo < 0:
            saldo = Decimal("0")

        def money_aligned(val, prefix=''):
            # U+2007 es el "Figure Space", tiene el grosor exacto de un número en WhatsApp.
            # Nos ayuda a alinear los decimales verticalmente sin usar la fuente de código.
            txt = f"{prefix}{format_money(val)}"
            return txt.rjust(11, '\u2007')

        # Usamos el Figure Space repetido para empujar las cantidades y alinearlas.
        esp = '\u2007'

        return (
            "Claro, con gusto te comparto el desglose de tu cuenta:\n\n"
            f"*Precio del equipo:* {esp*2}{money_aligned(precio)}\n"
            f"*Pago inicial:* {esp*10}{money_aligned(pago, '-')}\n"
            f"*Subsidio:* {esp*15}{money_aligned(subsidio, '-')}\n"
            "----------------------------------------------------\n"
            f"*Saldo restante:* {esp*7}{money_aligned(saldo)}"
        )
    
    @staticmethod
    def build_devolucion_confirmacion() -> str:
        return (
            "Si es posible realizar la devolución del equipo, solo necesitas seguir el siguiente proceso:\n\n"
            "- Se deberá cubrir un cargo de $850.00 por gastos de traslado y gestión.\n"
            "- Posteriormente se le notificará el día de recolección.\n\n"
            "¿Deseas continuar con la devolución?"
        )
