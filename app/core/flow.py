from app.core.states import ChatState
import app.content.messages as msg

DEFAULT_TRANSITIONS = {
    "negative": ChatState.INCONSISTENCIA,
    "later": ChatState.RECORDATORIO,
    "human": ChatState.LLAMADA,
    "doubt": ChatState.ACLARACION,
    "other": ChatState.FUERA_DE_FLUJO,
}


FLOW = {
    ChatState.MENU_AYUDA: {
        "text": msg.MENU_AYUDA,
        "buttons": [
            {"id": "MENU_VERIFICACION", "label": "📄 Verificacion"},
            {"id": "MENU_DUDAS", "label": "❓ Dudas generales"},
            {"id": "MENU_PAGOS", "label": "💰 Dudas sobre pagos"},
        ],
        "options": {
            "MENU_VERIFICACION": ChatState.CAMBIAR_FOLIO,
            "MENU_DUDAS": ChatState.ACLARACION,
            "MENU_PAGOS": ChatState.INFO_PAGOS,
        },
    },
    ChatState.ESPERA: {
        "text": "",
        "buttons": [],
        "options": {
            "auto_next": ChatState.MENU_AYUDA,
        },
        "auto_next": ChatState.INICIO,
    },
    ChatState.INICIO: {
        "text": msg.INICIO,
        "buttons": [
            {"id": "INICIO_SI", "label": "✅ Sí, adelante"},
            {"id": "INICIO_LUEGO", "label": "⏰ Recordar más tarde"},
            {"id": "INICIO_LLAMADA", "label": "📞 Prefiero llamada"},
        ],
        "options": {
            "INICIO_SI": ChatState.CONFIRMAR_NOMBRE,
            "INICIO_LUEGO": ChatState.RECORDATORIO,
            "INICIO_LLAMADA": ChatState.LLAMADA,
            "affirmative": ChatState.CONFIRMAR_NOMBRE,
        },
    },

    ChatState.CONFIRMAR_FOLIO: {
        "text": "",  
        "buttons": [
            {"id": "FOLIO_SI", "label": "✅ Sí"},
            {"id": "FOLIO_NO", "label": "✏️ Cambiar"},
        ],
        "options": {
            "FOLIO_SI": ChatState.CONFIRMAR_NOMBRE,
            "FOLIO_NO": ChatState.CAMBIAR_FOLIO,
        },
    },

    ChatState.CAMBIAR_FOLIO: {
        "text": "✏️ Por favor escribe tu folio.",
        "buttons": [],
        "options": {}
    },

    

    ChatState.CONFIRMAR_NOMBRE: {
        "text": msg.CONFIRMAR_NOMBRE,
        "buttons": [
            {"id": "NOMBRE_SI", "label": "✅ Sí"},
            {"id": "NOMBRE_NO", "label": "❌ No"},
        ],
        "options": {
            "NOMBRE_SI": ChatState.CONFIRMAR_DOMICILIO,
            "affirmative": ChatState.CONFIRMAR_DOMICILIO,
            "NOMBRE_NO": ChatState.ESCRIBIR_INCONSISTENCIA,
            "negative": ChatState.ESCRIBIR_INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_DOMICILIO: {
        "text": msg.CONFIRMAR_DOMICILIO,
        "buttons": [
            {"id": "DOM_SI", "label": "✅ Sí"},
            {"id": "DOM_NO", "label": "❌ No"},
        ],
        "options": {
            "DOM_SI": ChatState.CONFIRMAR_FECHA,
            "affirmative": ChatState.CONFIRMAR_FECHA,
            "DOM_NO": ChatState.ESCRIBIR_INCONSISTENCIA,
            "negative": ChatState.ESCRIBIR_INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_FECHA: {
        "text": msg.CONFIRMAR_FECHA,
        "buttons": [
            {"id": "FECHA_SI", "label": "✅ Sí"},
            {"id": "FECHA_NO", "label": "❌ No"},
        ],
        "options": {
            "FECHA_SI": ChatState.CONFIRMAR_PRODUCTO,
            "affirmative": ChatState.CONFIRMAR_PRODUCTO,
            "FECHA_NO": ChatState.ESCRIBIR_INCONSISTENCIA,
            "negative": ChatState.ESCRIBIR_INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_PRODUCTO: {
        "text": msg.CONFIRMAR_PRODUCTO,
        "buttons": [
            {"id": "PROD_SI", "label": "✅ Sí"},
            {"id": "PROD_NO", "label": "❌ No"},
        ],
        "options": {
            "PROD_SI": ChatState.CONFIRMAR_COMPONENTES,
            "affirmative": ChatState.CONFIRMAR_COMPONENTES,
            "PROD_NO": ChatState.ESCRIBIR_INCONSISTENCIA,
            "negative": ChatState.ESCRIBIR_INCONSISTENCIA,
        },
    },
    ChatState.CONFIRMAR_COMPONENTES: {
        "text": msg.CONFIRMAR_COMPONENTES,
        "buttons": [
            {"id": "COMP_SI", "label": "✅ Sí"},
            {"id": "COMP_NO", "label": "❌ No"},
        ],
        "options": {
            "COMP_SI": ChatState.CONFIRMAR_PAGO_INICIAL,
            "affirmative": ChatState.CONFIRMAR_PAGO_INICIAL,
            "COMP_NO": ChatState.COMPONENTES_FALTANTES,
            "negative": ChatState.COMPONENTES_FALTANTES,
        },
    },
    ChatState.CONFIRMAR_ESTADO_PRODUCTO: {
        "text": msg.CONFIRMAR_ESTADO_PRODUCTO,
        "buttons": [
            {"id": "PROD_ESTADO_SI", "label": "✅ Sí"},
            {"id": "PROD_ESTADO_NO", "label": "❌ No"},
        ],
        "options": {
            "PROD_ESTADO_SI": ChatState.CONFIRMAR_PAGO_INICIAL,
            "affirmative": ChatState.CONFIRMAR_PAGO_INICIAL,
            "PROD_ESTADO_NO": ChatState.ESCRIBIR_INCONSISTENCIA,
            "negative": ChatState.ESCRIBIR_INCONSISTENCIA,
        },
    },
    ChatState.COMPONENTES_FALTANTES: {
        "text": "Selecciona el componente que faltó:",
        "buttons": [
            {"id": "FALT_CPU", "label": "🔴 CPU roja"},
            {"id": "FALT_MONITOR", "label": "🖥️ Monitor"},
            {"id": "FALT_TECLADO", "label": "⌨️ Teclado"},
            {"id": "FALT_MOUSE", "label": "🖱️ Mouse"},
            {"id": "FALT_BOCINAS", "label": "🔊 Bocinas"},
            {"id": "FALT_REGULADOR", "label": "🔌 Regulador"},
            {"id": "FALT_WIFI", "label": "📶 Antena WiFi"},
        ],
        "options": {
            "FALT_CPU": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "FALT_MONITOR": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "FALT_TECLADO": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "FALT_MOUSE": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "FALT_BOCINAS": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "FALT_REGULADOR": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "FALT_WIFI": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
        },
    },
    ChatState.COMPONENTES_CONFIRMAR_FALTANTES: {
        "text": "¿Deseas agregar otro componente faltante?",
        "buttons": [
            {"id": "FALT_AGREGAR", "label": "✅ Si, agregar otro"},
            {"id": "FALT_CONFIRMAR", "label": "❌ No, es todo"},
        ],
        "options": {
            "FALT_AGREGAR": ChatState.COMPONENTES_FALTANTES,
            "FALT_CONFIRMAR": ChatState.CONFIRMAR_PAGO_INICIAL,
        },
    },
    ChatState.CONFIRMAR_PAGO_INICIAL: {
        "text": msg.CONFIRMAR_PAGO,
        "buttons": [
            {"id": "PAGO_SI", "label": "✅ Sí"},
            {"id": "PAGO_NO", "label": "❌ No"},
        ],
        "options": {
            "PAGO_SI": ChatState.INFO_PAGOS,
            "affirmative": ChatState.INFO_PAGOS,
            "PAGO_NO": ChatState.ESCRIBIR_INCONSISTENCIA,
            "negative": ChatState.ESCRIBIR_INCONSISTENCIA,
        },
    },
    ChatState.INFO_PAGOS: {
        "text": msg.INFO_PAGOS,
        "buttons": [
            {"id": "PAGOS_OK", "label": "✅ Está claro"},
            {"id": "PAGOS_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PAGOS_OK": ChatState.INFO_METODOS_PAGO,
            "affirmative": ChatState.INFO_METODOS_PAGO,
            "PAGOS_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.INFO_METODOS_PAGO: {
        "text": msg.INFO_METODOS_PAGO,
        "buttons": [
            {"id": "PAGOS_OK", "label": "✅ Está claro"},
            {"id": "PAGOS_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PAGOS_OK": ChatState.INFO_PLAN_3_MESES,
            "affirmative": ChatState.INFO_PLAN_3_MESES,
            "PAGOS_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.INFO_PLAN_3_MESES: {
        "text": msg.INFO_PLAN_3_MESES,
        "buttons": [
            {"id": "PLAN3_OK", "label": "✅ No tengo dudas"},
            {"id": "PLAN3_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PLAN3_OK": ChatState.INFO_OTROS_PLANES,
            "affirmative": ChatState.INFO_OTROS_PLANES,
            "PLAN3_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.INFO_OTROS_PLANES: {
        "text": msg.INFO_OTROS_PLANES,
        "buttons": [
            {"id": "PLANES_OK", "label": "✅ No tengo dudas"},
            {"id": "PLANES_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PLANES_OK": ChatState.INFO_BENEFICIOS,
            "affirmative": ChatState.INFO_BENEFICIOS,
            "PLANES_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.INFO_BENEFICIOS: {
        "text": msg.INFO_BENEFICIOS,
        "buttons": [
            {"id": "BEN_OK", "label": "✅ No tengo dudas"},
            {"id": "BEN_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "BEN_OK": ChatState.FINALIZADO,
            "affirmative": ChatState.FINALIZADO,
            "BEN_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.INFO_BENEFICIOS2: {
        "text": msg.INFO_BENEFICIOS2,
        "buttons": [
            {"id": "BEN_OK", "label": "✅ No tengo dudas"},
            {"id": "BEN_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "BEN_OK": ChatState.FINALIZADO,
            "affirmative": ChatState.FINALIZADO,
            "BEN_DUDA": ChatState.ACLARACION,
        },
    },
    ChatState.FINALIZADO: {
        "text": msg.FINALIZADO,
        "buttons": [],
        "options": {},
    },
    ChatState.INCONSISTENCIA: {
        "text": msg.INCONSISTENCIA,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar proceso"},
            {"id": "ACLARA_LLAMADA", "label": "📞 Hablar asesor"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
            "affirmative": "__RESUME__",
            "ACLARA_LLAMADA": ChatState.LLAMADA,
        },
    },
    ChatState.FUERA_DE_FLUJO: {
        "text": msg.FUERA_DE_FLUJO,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar proceso"},
            {"id": "ACLARA_LLAMADA", "label": "📞 Hablar asesor"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
            "affirmative": "__RESUME__",
            "ACLARA_LLAMADA": ChatState.LLAMADA,
        },
    },
    ChatState.ACLARACION: {
        "text": msg.ACLARACION,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar proceso"},
            {"id": "ACLARA_LLAMADA", "label": "📞 Hablar asesor"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
            "affirmative": "__RESUME__",

            "ACLARA_LLAMADA": ChatState.LLAMADA,
        },
    },
    ChatState.LLAMADA: {
        "text": msg.ACLARACION,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar proceso"},
            {"id": "ACLARA_LLAMADA", "label": "📞 Hablar asesor"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
            "affirmative": "__RESUME__",
            "ACLARA_LLAMADA": ChatState.LLAMADA,
        },
    },
    ChatState.ESCRIBIR_INCONSISTENCIA: {
        "text": "✏️ Por favor escribe cuál es el error para que podamos revisarlo.",
        "buttons": [],
        "options": {}
    },
}
