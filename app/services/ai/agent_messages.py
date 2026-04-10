AGENT_MESSAGES = {

    # --------------------------------------
    # ESCALACIÓN
    # --------------------------------------
    "escalation": {
        "default": "Voy a pasar tu caso con un asesor para ayudarte mejor.",
    },

    # --------------------------------------
    # FUERA DE ALCANCE
    # --------------------------------------
    "out_of_scope": {
        "default": (
            "Solo puedo ayudarte con temas relacionados con tu compra en MEXIcomp, "
            "como verificación, pagos, producto, planes y beneficios."
        ),
    },

    # --------------------------------------
    # FALTA DE INFORMACIÓN
    # --------------------------------------
    "missing_information": {
        "default": (
            "No tengo suficiente información para ayudarte con eso en este momento."
        ),
    },

    # --------------------------------------
    # CONFUSIÓN DEL CLIENTE
    # --------------------------------------
    "confusion": {
        "default": (
            "Quiero asegurarme de ayudarte correctamente. ¿Podrías explicarme un poco más tu duda?"
        ),
    },

    # --------------------------------------
    # REDIRECCIÓN AL FLUJO
    # --------------------------------------
    "return_to_flow": {
        "default": (
            "Continuemos con el proceso para terminar tu verificación."
        ),
    },

    # --------------------------------------
    # ERROR GENERAL
    # --------------------------------------
    "fallback": {
        "default": (
            "Tu caso requiere revisión. Voy a pasarte con un asesor para ayudarte mejor."
        ),
    },
}