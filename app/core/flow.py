from app.core.states import ChatState

DEFAULT_TRANSITIONS = {
    "negative": ChatState.INCONSISTENCIA,
    "later": ChatState.RECORDATORIO,
    "human": ChatState.LLAMADA,
    "doubt": ChatState.ACLARACION,
    #"other": ChatState.FUERA_DE_FLUJO,
}

FLOW = {
    ChatState.ESPERA: {
        "text": (
            "Hola, soy Alonso 👋🏻\n\n"
            "Estoy aquí para apoyarte con la activación de tus beneficios. 🤳🏻\n"
            "En breve te contactaré nuevamente para brindarte más información."
        ),
        "buttons": [],
        "options": {
            "affirmative": ChatState.INICIO,
        },
        "auto_next": ChatState.INICIO,
    },
    ChatState.INICIO: {
        "text": (
            "¡Ya volví!\n"
            "Vamos a confirmar algunos datos de tu compra.\n"
            "El proceso toma menos de ⌚ 5 minutos y es necesario para activar tus beneficios 🎁\n\n"
            "¿Podemos comenzar?"
        ),
        "buttons": [
            {"id": "INICIO_SI", "label": "✅ Sí, adelante"},
            {"id": "INICIO_LUEGO", "label": "⏰ Recuérdamelo más tarde"},
            {"id": "INICIO_LLAMADA", "label": "📞 Prefiero que me llames"},
        ],
        "options": {
            "INICIO_SI": ChatState.CONFIRMAR_NOMBRE,  # quick reply (Meta)
            "INICIO_LUEGO": ChatState.RECORDATORIO,  # quick reply (Meta)
            "INICIO_LLAMADA": ChatState.LLAMADA,  # quick reply (Meta)
            "affirmative": ChatState.CONFIRMAR_NOMBRE,  # texto
            "start_verification": ChatState.CONFIRMAR_NOMBRE,
        },
    },
    ChatState.CONFIRMAR_NOMBRE: {
        "text": "📝 ¿Tu nombre completo es *{nombre_completo}*?",
        "buttons": [
            {"id": "NOMBRE_SI", "label": "✅ Sí"},
            {"id": "NOMBRE_NO", "label": "❌ No"},
        ],
        "options": {
            "NOMBRE_SI": ChatState.CONFIRMAR_DOMICILIO,
            "affirmative": ChatState.CONFIRMAR_DOMICILIO,  # texto
            "NOMBRE_NO": ChatState.INCONSISTENCIA,
            "negative": ChatState.INCONSISTENCIA,  # texto
        },
    },
    ChatState.CONFIRMAR_DOMICILIO: {
        "text": "🏠 ¿Tu domicilio es *{domicilio_completo}*?",
        "buttons": [
            {"id": "DOM_SI", "label": "✅ Sí"},
            {"id": "DOM_NO", "label": "❌ No"},
        ],
        "options": {
            "DOM_SI": ChatState.CONFIRMAR_FECHA,
            "affirmative": ChatState.CONFIRMAR_FECHA,  # texto
            "DOM_NO": ChatState.INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_FECHA: {
        "text": "📆 ¿Tu contrato fue el *{fecha_venta}*?",
        "buttons": [
            {"id": "FECHA_SI", "label": "✅ Sí"},
            {"id": "FECHA_NO", "label": "❌ No"},
        ],
        "options": {
            "FECHA_SI": ChatState.CONFIRMAR_PRODUCTO,
            "affirmative": ChatState.CONFIRMAR_PRODUCTO,  # texto
            "FECHA_NO": ChatState.INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_PRODUCTO: {
        "text": "🖥️ ¿El producto adquirido es *{nombre_producto}*?",
        "buttons": [
            {"id": "PROD_SI", "label": "✅ Sí"},
            {"id": "PROD_NO", "label": "❌ No"},
        ],
        "options": {
            "PROD_SI": ChatState.CONFIRMAR_COMPONENTES,
            "affirmative": ChatState.CONFIRMAR_COMPONENTES,  # texto
            "PROD_NO": ChatState.INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_COMPONENTES: {
        "text": (
            "📦 ¿Recibiste todos los componentes?\n"
            "CPU, Monitor, Teclado, Mouse, Bocinas, Regulador y Antena WiFi"
        ),
        "buttons": [
            {"id": "COMP_SI", "label": "✅ Sí"},
            {"id": "COMP_NO", "label": "❌ No"},
        ],
        "options": {
            "COMP_SI": ChatState.CONFIRMAR_PAGO_INICIAL,
            "affirmative": ChatState.CONFIRMAR_PAGO_INICIAL,  # texto
            "COMP_NO": ChatState.INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_PAGO_INICIAL: {
        "text": "💲 ¿Tu pago inicial fue de *${importe_pago_inicial}*?",
        "buttons": [
            {"id": "PAGO_SI", "label": "✅ Sí"},
            {"id": "PAGO_NO", "label": "❌ No"},
        ],
        "options": {
            "PAGO_SI": ChatState.INFO_PAGOS,
            "affirmative": ChatState.INFO_PAGOS,  # texto
            "PAGO_NO": ChatState.INCONSISTENCIA,
        },
    },
    ChatState.INFO_PAGOS: {
        "text": "🏦 ¿Está claro tu esquema de pagos?",
        "buttons": [
            {"id": "PAGOS_OK", "label": "✅ Está claro"},
            {"id": "PAGOS_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PAGOS_OK": ChatState.INFO_BANCOS,
            "affirmative": ChatState.INFO_BANCOS,  # texto
            "PAGOS_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.INFO_BANCOS: {
        "text": "🏦 Aquí tienes los datos bancarios.",
        "buttons": [
            {"id": "BANCOS_OK", "label": "✅ Está claro"},
            {"id": "BANCOS_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "BANCOS_OK": ChatState.PLAN_3_MESES,
            "affirmative": ChatState.PLAN_3_MESES,  # texto
            "BANCOS_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.PLAN_3_MESES: {
        "text": "🎓 ¿Tienes dudas sobre tu plan de 3 meses?",
        "buttons": [
            {"id": "PLAN3_OK", "label": "✅ No tengo dudas"},
            {"id": "PLAN3_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PLAN3_OK": ChatState.INFO_PLANES,
            "affirmative": ChatState.INFO_PLANES,  # texto
            "PLAN3_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.INFO_PLANES: {
        "text": "📜 ¿Tienes dudas sobre los planes de 6, 9, 12, 15 y 18 meses?",
        "buttons": [
            {"id": "PLANES_OK", "label": "✅ No tengo dudas"},
            {"id": "PLANES_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PLANES_OK": ChatState.BENEFICIOS,
            "affirmative": ChatState.BENEFICIOS,  # texto
            "PLANES_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.BENEFICIOS: {
        "text": "🎉 ¡Felicidades! Ya puedes disfrutar de tus beneficios.",
        "buttons": [
            {"id": "BEN_OK", "label": "✅ No tengo dudas"},
            {"id": "BEN_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "BEN_OK": ChatState.FINALIZADO,
            "affirmative": ChatState.FINALIZADO,  # texto
            "BEN_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.FINALIZADO: {
        "text": "✅ Verificación completada. Gracias por tu tiempo.",
        "buttons": [],
        "options": {},
    },
    ChatState.INCONSISTENCIA: {  # Se debe de checar para encontrar una ayuda con la inconsistencia a través de un mensaje o una llamada del asesor
        "text": (
            "💬 Gracias por tu mensaje.\n\n"
            "En un momento te contactará un asesor para ayudarte a resolver esta inconsistencia."
        ),
        "buttons": [
            {"id": "ACLARA_CONTINUAR", "label": "▶️ Continuar verificación"},
            {"id": "ACLARA_LLAMADA", "label": "📞 Hablar con un asesor"},
        ],
        "options": {
            "ACLARA_CONTINUAR": ChatState.INICIO,
            "ACLARA_LLAMADA": ChatState.LLAMADA,
        },
    },
    ChatState.FUERA_DE_FLUJO: {  # Se debe de checar para responder mensajes con la ia
        "text": (
            "💬 Gracias por tu mensaje.\n\n"
            "En un momento te contactará un asesor para ayudarte a resolver este fuera  lasdb."
        ),
        "buttons": [
            {"id": "REANUDACIÓN", "label": "▶️ Continuar verificación"},
            {"id": "ACLARA_LLAMADA", "label": "📞 Hablar con un asesor"},
        ],
        "options": {
            "REANUDACIÓN": "__RESUME__",
            "ACLARA_LLAMADA": ChatState.LLAMADA,
        },
    },
    ChatState.ACLARACION: {
        "text": (
            "💬 Gracias por tu mensaje.\n\n"
            "Puedo ayudarte a aclarar tu duda o continuar con el proceso de verificación."
        ),
        "buttons": [
            {"id": "ACLARA_CONTINUAR", "label": "▶️ Continuar verificación"},
            {"id": "ACLARA_LLAMADA", "label": "📞 Hablar con un asesor"},
        ],
        "options": {
            "ACLARA_CONTINUAR": "__RESUME__",
            "ACLARA_LLAMADA": ChatState.LLAMADA,
        },
    },
}
