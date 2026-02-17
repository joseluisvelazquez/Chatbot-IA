import os
import httpx

PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.getenv("ACCESS_TOKEN")


BASE_URL = f"https://graph.facebook.com/v24.0/{PHONE_NUMBER_ID}/messages"

HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}


# ---------------- BUTTON BUILDER ----------------


def _build_buttons(buttons: list):
    return [
        {
            "type": "reply",
            "reply": {
                "id": b["id"],
                "title": b["label"][:20],
            },
        }
        for b in buttons[:3]
    ]


# ---------------- CORE SEND ----------------


async def _send(payload: dict):

    print("\n================ META REQUEST ================")
    print(payload)

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(BASE_URL, headers=HEADERS, json=payload)

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)
    print("=============================================\n")

    # si Meta falla, no truenes el bot
    if response.status_code >= 400:
        print("⚠️ ERROR ENVIANDO A WHATSAPP")

    return response


# ---------------- SENDERS ----------------


async def send_text(phone: str, text: str):
    return await _send(
        {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        }
    )


async def send_buttons(phone: str, text: str, buttons: list):
    return await _send(
        {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": _build_buttons(buttons)},
            },
        }
    )


async def send_document(phone: str, url: str, filename="archivo.pdf"):
    return await _send(
        {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "document",
            "document": {
                "link": url,
                "filename": filename,
            },
        }
    )


# ---------------- PUBLIC API ----------------


async def send_whatsapp_message(phone, text=None, buttons=None, document_url=None):

    # print(f"\n📤 Enviando a {phone}")
    # print("Texto:", text)
    # print("Botones:", buttons)
    # print("Documento:", document_url)

    # documento primero
    if document_url:
        await send_document(phone, document_url)

    # botones o texto
    if buttons:
        await send_buttons(phone, text, buttons)
    elif text:
        await send_text(phone, text)
