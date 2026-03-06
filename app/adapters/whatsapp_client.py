import httpx
from app.adapters.meta_parser import build_meta_buttons
from app.config.settings import settings

HEADERS = {
    "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}


# ---------------- CORE SEND ----------------


# Esta función se encarga de enviar la petición a Meta, y loguear la respuesta. Si Meta devuelve un error, se loguea pero no se trunca el bot, para evitar que problemas temporales con Meta afecten la experiencia del usuario.
async def _send(payload: dict):

    print("\n================ META REQUEST ================")
    print(payload)
    url = f"{settings.BASE_URL}/{settings.PHONE_NUMBER_ID}/messages"

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers=HEADERS, json=payload)

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)
    print("=============================================\n")

    # si Meta falla, no truenes el bot
    if response.status_code >= 400:
        print("⚠️ ERROR ENVIANDO A WHATSAPP")

    return response


# ---------------- SENDERS ----------------


# Estas funciones construyen el payload específico para cada tipo de mensaje (texto, botones, documentos), y llaman a _send para enviar la petición a Meta.
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
                "action": {"buttons": build_meta_buttons(buttons)},
            },
        }
    )

# Funcion para enviar una lista de opciones, si hay más de 3 botones.
async def send_list(phone: str, text: str, buttons: list):
    return await _send(
        {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": text},
                "action": {
                    "button": "📋 Ver opciones",
                    "sections": [
                        {
                            "title": "Selecciona una opción",
                            "rows": [
                                {
                                    "id": btn["id"],
                                    "title": btn["label"][:24],  # límite de WhatsApp
                                }
                                for btn in buttons
                            ],
                        }
                    ],
                },
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


# Esta es la función que se exporta para ser usada en el resto del código. Recibe el teléfono, el texto, los botones y/o el documento a enviar, y llama a las funciones específicas según corresponda.
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
        if len(buttons) > 3:
            await send_list(phone, text, buttons)
        else:
            await send_buttons(phone, text, buttons)
    elif text:
        await send_text(phone, text)
