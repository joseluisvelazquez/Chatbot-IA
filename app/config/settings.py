import os


# ============================================================
# Función interna para validar variables obligatorias
# ============================================================
def _get_env_variable(name: str) -> str:
    """
    Obtiene una variable de entorno y falla si no existe.
    """
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"❌ La variable de entorno '{name}' no está definida.")

    return value


# ============================================================
# Variables requeridas para WhatsApp Cloud API
# ============================================================

VERIFY_TOKEN = _get_env_variable("VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = _get_env_variable("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _get_env_variable("WHATSAPP_PHONE_NUMBER_ID")


# ============================================================
# Opcionales con valor por defecto
# ============================================================

META_API_VERSION = os.getenv("META_API_VERSION", "v24.0")


# ============================================================
# URL base de Graph API
# ============================================================

GRAPH_API_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"
