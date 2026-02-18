import httpx
from typing import List, Dict

from app.config.settings import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
    META_API_VERSION,
)

GRAPH_API_BASE_URL = f"https://graph.facebook.com/{META_API_VERSION}"


# ============================================================
# Función interna para enviar requests a Meta
# ============================================================
async def _send_request(payload: Dict):
    """
    Envía un request a la API de WhatsApp Cloud.
    """

    url = f"{GRAPH_API_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, headers=headers, json=payload)

    # Puedes mejorar esto con logging estructurado
    if response.status_code not in (200, 201):
        print("❌ Error enviando mensaje a Meta:")
        print("Status:", response.status_code)
        print("Response:", response.text)

    return response


# ============================================================
# Enviar mensaje de texto simple
# ============================================================
async def send_text(to: str, body: str):
    """
    Envía un mensaje de texto simple a WhatsApp.
    """

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": body
        }
    }

    await _send_request(payload)


# ============================================================
# Enviar botones interactivos
# ============================================================
async def send_buttons(
    to: str,
    body: str,
    buttons: List[Dict[str, str]],
):
    """
    Envía botones interactivos.

    buttons debe tener formato interno:
    [
        {"id": "btn_si", "label": "Sí"},
        {"id": "btn_no", "label": "No"}
    ]
    """

    formatted_buttons = []

    for button in buttons:
        formatted_buttons.append({
            "type": "reply",
            "reply": {
                "id": button["id"],
                "title": button["label"][:20]  # Meta permite máximo 20 caracteres
            }
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": body
            },
            "action": {
                "buttons": formatted_buttons
            }
        }
    }

    await _send_request(payload)
