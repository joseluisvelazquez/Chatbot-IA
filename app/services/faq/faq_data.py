FAQ_DATA = [

    # -------------------------
    # COMPROBANTES
    # -------------------------
    {
        "keywords": [
            "subir comprobante",
            "enviar comprobante",
            "cargar comprobante",
            "donde subo comprobante",
            "como subo mi comprobante",
            "mxcomp comprobante",
            "codigo cliente",
            "datos de acceso comprobante"
        ],
        "response": "Debes enviar tu comprobante en https://mxcomp.mx/ usando el numero de cuenta y codigo de cliente que se te compartieron.",
        "response_dinamica": "Debes enviar tu comprobante en https://mxcomp.mx/ usando estos datos: numero de cuenta *{numero_cuenta_referencia}* y codigo de cliente *{codigo_cliente}*."
    },

    # -------------------------
    # PRIMER PAGO
    # -------------------------
    {
        "keywords": [
            "cuando primer pago",
            "puedo pagar cualquier dia",
            "cuando puedo hacer el primer pago",
            "primer pago dia",
            "puedo pagar antes"
        ],
        "response": "Si puedes hacerlo, siempre y cuando no supere el dia limite indicado en su verificación, puede realizarlo antes sin problema.",
        "response_dinamica": "Si puedes hacerlo, siempre y cuando no sea después del *{fecha_limite}* puede realizarlo antes sin problema."
    },
    {
        "keywords": [
            "primer pago 15 dias",
            "primer pago un mes",
            "puedo pagar en 15 dias",
            "puedo pagar despues"
        ],
        "response": "Su primer pago se debe realizar a mas tardar en la fecha indicada en su verificación y en ese mismo pago debe cubrir lo correspondiente a 2 semanas o a 4 según lo decida.",
        "response_dinamica": "Su primer pago se debe realizar a mas tardar el *{fecha_limite}* y en ese mismo pago debe cubrir lo correspondiente a 2 semanas: *${importe_quincenal}* o a 4 semanas: *${importe_mensual}* según lo decida."
    },

    # -------------------------
    # DEPÓSITOS EN EFECTIVO (OXXO, Ventanilla, Telecomm, Caja Huastecas)
    # -------------------------
    {
        "keywords": [
            "oxxo numero",
            "deposito oxxo numero",
            "pago oxxo numero",
            "que numero doy en oxxo",
            "numero ventanilla",
            "deposito ventanilla",
            "numero telecomm",
            "pago telecomm",
            "numero caja huastecas",
            "pago caja huastecas",
            "a que numero deposito en efectivo"
        ],
        "response": "Para depósitos físicos, debe proporcionar cualquiera de las opciones que dicen 'Tarjeta de débito' (16 dígitos) de la imagen.",
        "image_env": "METODOS_PAGO_IMAGE_ID"
    },
    {
        "keywords": [
            "oxxo concepto",
            "concepto oxxo",
            "poner concepto en oxxo",
            "deposito en efectivo concepto",
            "concepto numero de cuenta oxxo",
            "concepto ventanilla",
            "concepto telecomm",
            "concepto caja huastecas",
            "como le pongo mi numero de cuenta al ticket"
        ],
        "response": "No hay manera de que en los depósitos en efectivo pongan concepto, una vez que usted tenga su ticket deberá escribirlo en el mismo con pluma, para conocer su numero de cuenta inicie la verificación.  ",
        "response_dinamica": "No hay manera de que en los depósitos en efectivo pongan concepto, una vez que usted tenga su ticket deberá escribir este numero *{numero_cuenta_referencia}* en el mismo con pluma."
    },

    # -------------------------
    # TRANSFERENCIA (SPEI) Y PAGO CON TARJETA
    # -------------------------
    {
        "keywords": [
            "concepto transferencia",
            "que pongo en concepto",
            "concepto banco",
            "transferencia concepto"
        ],
        "response": "Debe colocar el número de cuenta que se le proporciona durante la verificación, el cual comienza con la letra A.",
        "response_dinamica": "Debe colocar su número de cuenta, el cual es *{numero_cuenta_referencia}*."
    },

    # -------------------------
    # PAGOS
    # -------------------------

    {
        "keywords": [
            "pagos cuando quiera",
            "pagos cuando pudiera",
            "realizar cuando pudiera",
            "pagar cuando pueda",
            "pagar cuando quiera"
        ],
        "response": "Los pagos son de manera semanal, aunque puede optar por realizarlos quincenales o mensuales según las opciones que se le proporcionan en la verificación.",
        "response_dinamica": "Los pagos son de manera semanal de *${pago_minimo}*, aunque puede optar por realizarlos quincenales por la cantidad de *${importe_quincenal}* o mensuales por *${importe_mensual}*."
    },

    {
        "keywords": [
            "pago minimo",
            "pagos semanales 215",
            "cuanto es el pago semanal"
            "por que pago mas",
            "por que no es 215",
            "por que cambio el pago",
            "diferencia entre pagos",
            "por que es mas caro"
        ],
        "response": "El pago mínimo semanal sugerido es de $215, aunque también existe la opción de aprovechar el plan de 3 meses y no pagar ningún remanente, para mas información favor de realizar la verificación.",
        "response_dinamica": "El pago mínimo semanal sugerido es de *${pago_minimo}*, aunque también existe la opción de aprovechar el plan de 3 meses y no pagar ningún remanente al llegar la fecha de sus 3 meses, es decir con 13 pagos de *${importe_semanal_3m}* liquida su cuenta realizando el primero el *{fecha_limite}*."
    },

    {
        "keywords": [
            "despues de 3 meses",
            "que pasa despues de 3 meses",
            "cambia el precio",
            "cambia el costo"
        ],
        "response": "Entiendo, todo viene establecido en su contrato en el apartado de PRECIOS Y PLANES DE PAGO. Si gusta revisarlo detalladamente y si existiera alguna duda adicional se le transfiere con un asesor para que le apoye."
    },



]
