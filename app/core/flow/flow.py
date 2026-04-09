from app.core.states.states import ChatState
import app.content.messages as msg

# --------------------------------------
# TRANSICIONES GLOBALES
# --------------------------------------

DEFAULT_TRANSITIONS = {
    "inconsistency": ChatState.INCONSISTENCIA,
    "pause": ChatState.RECORDATORIO,
    "escalate": ChatState.ACLARACION,
    "ai": ChatState.FUERA_DE_FLUJO,
}


# --------------------------------------
# FLOW PRINCIPAL
# --------------------------------------

FLOW = {

    # --------------------------------------
    # MENU DE AYUDA
    # --------------------------------------

   ChatState.MENU_AYUDA: {
        "text": msg.MENU_AYUDA,
        "buttons": [
            {"id": "MENU_VERIFICACION", "label": "📄 Ir a verificación"},
            {"id": "MENU_DUDA", "label": "❓ Hacer una pregunta"},
        ],
    },

    ChatState.MENU_DUDA: {
        "text": msg.PREGUNTA_DUDA,
        "buttons": [],
    },

    # --------------------------------------
    # INICIO
    # --------------------------------------

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

    # --------------------------------------
    # CONFIRMACIONES
    # --------------------------------------

    ChatState.CAMBIAR_FOLIO: {
        "text": msg.PEDIR_FOLIO,
        "buttons": [],
    },

    ChatState.CAMBIAR_FOLIO_DEVOLUCION: {
        "text": msg.PEDIR_FOLIO,
        "buttons": [],
    },

    ChatState.CAMBIAR_FOLIO_DESCUENTO: {
        "text": msg.PEDIR_FOLIO,
        "buttons": [],
    },

    ChatState.CONFIRMAR_FOLIO: {
        "text": msg.CONFIRMAR_FOLIO_DETECTADO,
        "buttons": [
            {"id": "FOLIO_SI", "label": "✅ Sí"},
            {"id": "FOLIO_NO", "label": "✏️ Cambiar"},
        ],
        "options": {
            "FOLIO_SI": ChatState.CONFIRMAR_NOMBRE,
            "FOLIO_NO": ChatState.CAMBIAR_FOLIO,
            "affirmative": ChatState.CONFIRMAR_NOMBRE,
            "negative": ChatState.CAMBIAR_FOLIO,
        },
    },

    ChatState.CONFIRMAR_FOLIO_DEVOLUCION: {
        "text": msg.CONFIRMAR_FOLIO_DETECTADO,
        "buttons": [
            {"id": "FOLIO_SI", "label": "✅ Sí"},
            {"id": "FOLIO_NO", "label": "✏️ Cambiar"},
        ],
        "options": {
            "FOLIO_SI": ChatState.DEVOLUCION_CONFIRMAR,
            "FOLIO_NO": ChatState.CAMBIAR_FOLIO_DEVOLUCION,
            "affirmative": ChatState.DEVOLUCION_CONFIRMAR,
            "negative": ChatState.CAMBIAR_FOLIO_DEVOLUCION,
        },
    },

    ChatState.CONFIRMAR_FOLIO_DESCUENTO: {
        "text": msg.CONFIRMAR_FOLIO_DETECTADO,
        "buttons": [
            {"id": "FOLIO_SI", "label": "✅ Sí"},
            {"id": "FOLIO_NO", "label": "✏️ Cambiar"},
        ],
        "options": {
            "FOLIO_SI": "__RESUME_DESCUENTO__",
            "FOLIO_NO": ChatState.CAMBIAR_FOLIO_DESCUENTO,
            "affirmative": "__RESUME_DESCUENTO__",
            "negative": ChatState.CAMBIAR_FOLIO_DESCUENTO,
        },
    },

    ChatState.CONFIRMAR_NOMBRE: {
        "text": msg.CONFIRMAR_NOMBRE,
        "buttons": [
            {"id": "NOMBRE_SI", "label": "✅ Sí"},
            {"id": "NOMBRE_NO", "label": "❌ No"},
        ],
        "options": {
            "NOMBRE_SI": ChatState.CONFIRMAR_DOMICILIO,
            "NOMBRE_NO": ChatState.INCONSISTENCIA,
            "affirmative": ChatState.CONFIRMAR_DOMICILIO,
            "negative": ChatState.INCONSISTENCIA,
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
            "DOM_NO": ChatState.INCONSISTENCIA,
            "affirmative": ChatState.CONFIRMAR_FECHA,
            "negative": ChatState.INCONSISTENCIA,
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
            "FECHA_NO": ChatState.INCONSISTENCIA,
            "affirmative": ChatState.CONFIRMAR_PRODUCTO,
            "negative": ChatState.INCONSISTENCIA,
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
            "PROD_NO": ChatState.INCONSISTENCIA,
            "affirmative": ChatState.CONFIRMAR_COMPONENTES,
            "negative": ChatState.INCONSISTENCIA,
        },
    },

    ChatState.CONFIRMAR_ESTADO_PRODUCTO: {
        "text": "(Renderizado estáticamente/dinámico)",
        "buttons": [
            {"id": "ESTADO_SI", "label": "✅ Sí"},
            {"id": "ESTADO_NO", "label": "❌ No"},
        ],
        "options": {
            "ESTADO_SI": ChatState.CONFIRMAR_PAGO_INICIAL,
            "ESTADO_NO": ChatState.INCONSISTENCIA,
            "affirmative": ChatState.CONFIRMAR_PAGO_INICIAL,
            "negative": ChatState.INCONSISTENCIA,
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
            "COMP_NO": ChatState.COMPONENTES_FALTANTES,
            "affirmative": ChatState.CONFIRMAR_PAGO_INICIAL,
            "negative": ChatState.COMPONENTES_FALTANTES,
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
            "affirmative": ChatState.COMPONENTES_FALTANTES,
            "negative": ChatState.CONFIRMAR_PAGO_INICIAL,
        },
    },

    ChatState.VERIFICAR_FOTO_COMPONENTE: {
        "text": "(Renderizado dinámicamente)",
        "buttons": [
            {"id": "FOTO_SI_FALTA", "label": "❌ Sí, me falta"},
            {"id": "FOTO_YA_LO_VI", "label": "✅ Ah ya lo vi"},
        ],
        "options": {
            "FOTO_SI_FALTA": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "FOTO_YA_LO_VI": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "affirmative": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
            "negative": ChatState.COMPONENTES_CONFIRMAR_FALTANTES,
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
            "PAGO_NO": ChatState.INCONSISTENCIA,
            "affirmative": ChatState.INFO_PAGOS,
            "negative": ChatState.INCONSISTENCIA,
        },
    },

    # --------------------------------------
    # INFORMACIÓN
    # --------------------------------------

    ChatState.INFO_PAGOS: {
        "text": msg.INFO_PAGOS,
        "buttons": [
            {"id": "PAGOS_OK", "label": "✅ Está claro"},
            {"id": "PAGOS_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "PAGOS_OK": ChatState.INFO_METODOS_PAGO,
            "PAGOS_DUDA": ChatState.DUDA,
            "affirmative": ChatState.INFO_METODOS_PAGO,
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
            "PAGOS_DUDA": ChatState.DUDA,
            "affirmative": ChatState.INFO_PLAN_3_MESES,
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
            "PLAN3_DUDA": ChatState.DUDA,
            "affirmative": ChatState.INFO_OTROS_PLANES,
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
            "PLANES_DUDA": ChatState.DUDA,
            "affirmative": ChatState.INFO_BENEFICIOS,
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
            "BEN_DUDA": ChatState.DUDA,
            "affirmative": ChatState.FINALIZADO,
        },
    },

    ChatState.INFO_BENEFICIOS2: {
        "text": "(Renderizado dinámicamente)",
        "buttons": [
            {"id": "BEN_OK", "label": "✅ No tengo dudas"},
            {"id": "BEN_DUDA", "label": "❓ Tengo dudas"},
        ],
        "options": {
            "BEN_OK": ChatState.FINALIZADO,
            "BEN_DUDA": ChatState.DUDA,
            "affirmative": ChatState.FINALIZADO,
        },
    },

    # --------------------------------------
    # DEVOLUCIONES
    # --------------------------------------
    ChatState.DEVOLUCION_CONFIRMAR: {
        "text": None,
        "buttons": [
            {"id": "DEVOLUCION_SI", "label": "✅ Sí, continuar"},
            {"id": "DEVOLUCION_NO", "label": "❌ No"},
        ],
    },


    # --------------------------------------
    # ESTADOS ESPECIALES
    # --------------------------------------

    ChatState.INCONSISTENCIA: {
        "text": msg.INCONSISTENCIA,
        "buttons": [],
        "options": {},
    },

    ChatState.FUERA_DE_FLUJO: {
        "text": msg.FUERA_DE_FLUJO,
        "buttons": [],
        "options": {},
    },

    ChatState.DUDA: {
        "text": msg.PREGUNTA_DUDA,  
        "buttons": [],
        "options": {},
    },

    ChatState.ACLARACION: {
        "text": msg.ACLARACION,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar proceso"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
        },
    },

    ChatState.LLAMADA: {
        "text": msg.ACLARACION,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar proceso"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
        },
    },

    ChatState.RECORDATORIO_1H: {
        "text": msg.RECORDATORIO_1H,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar"},
            {"id": "LLAMADA", "label": "📞 Hablar con asesor"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
            "LLAMADA": ChatState.LLAMADA,
            "affirmative": "__RESUME__",
        },
    },

    ChatState.RECORDATORIO_2H: {
        "text": msg.RECORDATORIO_2H,
        "buttons": [
            {"id": "REANUDACION", "label": "▶️ Continuar"},
            {"id": "LLAMADA", "label": "📞 Hablar con asesor"},
        ],
        "options": {
            "REANUDACION": "__RESUME__",
            "LLAMADA": ChatState.LLAMADA,
            "affirmative": "__RESUME__",
        },
    },


    ChatState.FINALIZADO: {
        "text": msg.FINALIZADO,
        "buttons": [],
        "options": {},
    },
}