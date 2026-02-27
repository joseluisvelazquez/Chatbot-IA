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
