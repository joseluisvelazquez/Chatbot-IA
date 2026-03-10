from app.content import messages


class MessageBuilder:

    @staticmethod
    def confirmar_nombre(nombre: str) -> str:
        return messages.CONFIRMAR_NOMBRE.format(nombre_completo=nombre)

    @staticmethod
    def confirmar_producto(producto: str) -> str:
        return messages.CONFIRMAR_PRODUCTO.format(nombre_producto=producto)
    @staticmethod
    def confirmar_pago(pago: str) -> str:
        return messages.CONFIRMAR_PAGO.format(importe_pago_inicial=pago)

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
            pago_minimo=pago_minimo,
            importe_quincenal=importe_quincenal,
            importe_mensual=importe_mensual,
        )
    
    @staticmethod
    def info_metodos_pago(numero_cuenta: str) -> str:
        return messages.INFO_METODOS_PAGO.format(numero_cuenta=numero_cuenta)

    @staticmethod
    def info_plan_3_meses(saldo_3_meses: str, fecha_limite_3_meses: str, importe_semanal_3m: str, subsidio: str | None = None) -> str:
        partes = []
        if subsidio:
            partes.append(messages.INFO_PLAN_3_MESES_DESCUENTO.format(subsidio=subsidio))
        partes.append(messages.INFO_PLAN_3_MESES.format(
            saldo_3_meses=saldo_3_meses,
            fecha_limite_3_meses=fecha_limite_3_meses,
            importe_semanal_3m=importe_semanal_3m,
        ))
        return "".join(partes)
    
    @staticmethod
    def confirmar_estado_producto(producto: str) -> str:
        return messages.CONFIRMAR_ESTADO_PRODUCTO.format(nombre_producto=producto)

    @staticmethod
    def info_beneficios_producto(producto: str) -> str:
        return messages.INFO_BENEFICIOS2.format(producto=producto)