import httpx
import mimetypes
from pathlib import Path
from urllib.parse import urlparse
from app.adapters.meta_parser import build_meta_buttons
from app.config.settings import settings
from app.config.paths import MEDIA_DIR
import logging

logger = logging.getLogger(__name__)

META_INTERACTIVE_BODY_LIMIT = 1024
BUTTON_PROMPT_TEXT = "Selecciona una opción para continuar:"
IMAGE_LINK_TIMEOUT = 5

HEADERS = {
    "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
    "Content-Type": "application/json",
}


# ---------------- CORE SEND ----------------


# Esta función se encarga de enviar la petición a Meta, y loguear la respuesta. Si Meta devuelve un error, se loguea pero no se trunca el bot, para evitar que problemas temporales con Meta afecten la experiencia del usuario.
def _masked_phone(phone) -> str | None:
    text = str(phone or "")
    return text[-4:] if text else None


def _response_failed(response) -> bool:
    return response is None or getattr(response, "status_code", 0) >= 400


def _meta_error_context(response) -> dict:
    if response is None:
        return {}
    try:
        body = response.json()
    except Exception:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {}
    return {
        "error_code": error.get("code"),
        "error_subcode": error.get("error_subcode"),
        "error_type": error.get("type"),
    }


def _format_button_fallback(text: str | None, buttons: list | None) -> str:
    labels = [
        str(button.get("label") or "").strip()
        for button in (buttons or [])
        if isinstance(button, dict) and str(button.get("label") or "").strip()
    ]
    if not labels:
        return text or ""
    options = "\n".join(f"• {label}" for label in labels)
    return f"{text or BUTTON_PROMPT_TEXT}\n\nOpciones:\n{options}"


def _looks_like_asset_filename(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(str(value))
    if parsed.scheme or parsed.netloc:
        return False
    lower = str(value).strip().lower()
    return lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))


def _normalize_image_source(image_id: str | None) -> str | None:
    if not image_id:
        return None
    text = str(image_id).strip()
    if not text:
        return None
    if _looks_like_asset_filename(text):
        return settings.get_asset_url(text)
    return text


def _local_media_path_for_source(image_source: str | None) -> Path | None:
    if not image_source:
        return None

    source = str(image_source).strip()
    parsed = urlparse(source)
    path_text = parsed.path if parsed.scheme or parsed.netloc else source
    marker = "/media/"
    if marker in path_text:
        relative = path_text.split(marker, 1)[1]
    elif not (parsed.scheme or parsed.netloc) and _looks_like_asset_filename(path_text):
        relative = f"imagenes_verificacion/{Path(path_text).name}"
    else:
        return None

    base = Path(MEDIA_DIR).resolve()
    candidate = (base / relative.lstrip("/")).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


async def _upload_local_media_to_meta(image_source: str | None) -> str | None:
    local_path = _local_media_path_for_source(image_source)
    if not local_path:
        return None

    mime_type = mimetypes.guess_type(local_path.name)[0] or "image/jpeg"
    url = f"{settings.BASE_URL}/{settings.PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}

    logger.info(
        "whatsapp_media_upload_request",
        extra={"media_name": local_path.name, "mime_type": mime_type},
    )

    try:
        with local_path.open("rb") as file_obj:
            files = {"file": (local_path.name, file_obj, mime_type)}
            data = {"messaging_product": "whatsapp", "type": mime_type}
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=headers, data=data, files=files)
    except (OSError, httpx.HTTPError) as exc:
        logger.warning(
            "whatsapp_media_upload_exception",
            extra={"media_name": local_path.name, "error_type": type(exc).__name__},
        )
        return None

    if response.status_code >= 400:
        logger.warning(
            "whatsapp_media_upload_failed",
            extra={
                "status_code": response.status_code,
                "media_name": local_path.name,
                **_meta_error_context(response),
            },
        )
        return None

    try:
        payload = response.json()
    except Exception:
        payload = {}
    media_id = payload.get("id") if isinstance(payload, dict) else None
    if not media_id:
        logger.warning("whatsapp_media_upload_missing_id", extra={"media_name": local_path.name})
        return None
    return str(media_id)


async def _image_link_is_reachable(image_url: str) -> bool:
    if not image_url.lower().startswith(("http://", "https://")):
        return True

    try:
        async with httpx.AsyncClient(timeout=IMAGE_LINK_TIMEOUT, follow_redirects=True) as client:
            response = await client.head(image_url)
            if response.status_code == 405:
                response = await client.get(
                    image_url,
                    headers={"Range": "bytes=0-0"},
                )
    except httpx.HTTPError as exc:
        logger.warning(
            "whatsapp_image_link_check_failed",
            extra={"error_type": type(exc).__name__},
        )
        return False

    if response.status_code >= 400:
        logger.warning(
            "whatsapp_image_link_unreachable",
            extra={"status_code": response.status_code},
        )
        return False

    content_type = response.headers.get("content-type", "")
    if content_type and "image/" not in content_type.lower():
        logger.warning(
            "whatsapp_image_link_invalid_content_type",
            extra={"content_type": content_type[:80]},
        )
        return False

    return True


async def _send(payload: dict):

    url = f"{settings.BASE_URL}/{settings.PHONE_NUMBER_ID}/messages"
    logger.info(
        "whatsapp_send_request",
        extra={
            "message_type": payload.get("type"),
            "phone_last4": _masked_phone(payload.get("to")),
        },
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, headers=HEADERS, json=payload)
    except httpx.HTTPError as exc:
        logger.warning(
            "whatsapp_send_exception",
            extra={
                "message_type": payload.get("type"),
                "phone_last4": _masked_phone(payload.get("to")),
                "error_type": type(exc).__name__,
            },
        )
        return None

    # si Meta falla, no truenes el bot
    if response.status_code >= 400:
        logger.warning(
            "whatsapp_send_failed",
            extra={
                "status_code": response.status_code,
                "message_type": payload.get("type"),
                "phone_last4": _masked_phone(payload.get("to")),
                **_meta_error_context(response),
            },
        )

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


async def send_buttons_with_image(phone: str, text: str, buttons: list, image_id: str):
    image_source = _normalize_image_source(image_id)
    header_image = {"link": image_source} if image_source and image_source.startswith("http") else {"id": image_source}

    return await _send(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {
                    "type": "image",
                    "image": header_image
                },
                "body": {"text": text},
                "action": {"buttons": build_meta_buttons(buttons)},
            },
        }
    )


# ---------------- PUBLIC API ----------------


# Esta es la función que se exporta para ser usada en el resto del código. Recibe el teléfono, el texto, los botones y/o el documento a enviar, y llama a las funciones específicas según corresponda.
async def send_whatsapp_message(phone, text=None, buttons=None, document_url=None, image_id=None):

    # print(f"\n📤 Enviando a {phone}")
    # print("Texto:", text)
    # print("Botones:", buttons)
    # print("Documento:", document_url)

    last_response = None

    # documento primero
    if document_url:
        last_response = await send_document(phone, document_url)

    image_source = _normalize_image_source(image_id)

    # botones con imagen
    if image_source and buttons:
        if image_source.startswith("http") and not await _image_link_is_reachable(image_source):
            uploaded_media_id = await _upload_local_media_to_meta(image_source)
            if uploaded_media_id:
                logger.info(
                    "whatsapp_image_uploaded_after_unreachable_link",
                    extra={"phone_last4": _masked_phone(phone)},
                )
                image_source = uploaded_media_id
            else:
                logger.warning(
                    "whatsapp_image_skipped_unreachable",
                    extra={"phone_last4": _masked_phone(phone)},
                )
                image_source = None

    if image_source and buttons:
        if text and len(text) > META_INTERACTIVE_BODY_LIMIT:
            text_response = await send_text(phone, text)
            if _response_failed(text_response):
                return text_response
            return await send_buttons_with_image(phone, BUTTON_PROMPT_TEXT, buttons[:3], image_source)
        response = await send_buttons_with_image(phone, text, buttons[:3], image_source)
        if _response_failed(response):
            logger.warning(
                "whatsapp_image_interactive_fallback_without_image",
                extra={"phone_last4": _masked_phone(phone), "has_image": True},
            )
            if len(buttons) > 3:
                response = await send_list(phone, text, buttons)
            else:
                response = await send_buttons(phone, text, buttons)
            if _response_failed(response):
                logger.warning(
                    "whatsapp_interactive_fallback_to_text",
                    extra={"phone_last4": _masked_phone(phone), "has_image": True},
                )
                return await send_text(phone, _format_button_fallback(text, buttons))
            return response
        return response

    # botones sin imagen
    elif buttons:
        if text and len(text) > META_INTERACTIVE_BODY_LIMIT:
            text_response = await send_text(phone, text)
            if _response_failed(text_response):
                return text_response
            if len(buttons) > 3:
                return await send_list(phone, BUTTON_PROMPT_TEXT, buttons)
            return await send_buttons(phone, BUTTON_PROMPT_TEXT, buttons)

        if len(buttons) > 3:
            response = await send_list(phone, text, buttons)
        else:
            response = await send_buttons(phone, text, buttons)

        if _response_failed(response):
            logger.warning(
                "whatsapp_interactive_fallback_to_text",
                extra={"phone_last4": _masked_phone(phone), "has_image": False},
            )
            return await send_text(phone, _format_button_fallback(text, buttons))
        return response

    # solo texto
    elif text:
        return await send_text(phone, text)

    return last_response


async def send_whatsapp_media(phone, media_url, media_type, filename=None, caption=None):
    url = f"https://graph.facebook.com/{settings.META_API_VERSION}/{settings.PHONE_NUMBER_ID}/messages"

    clean_url = f"{settings.MEDIA_BASE_URL}{media_url}"

    if media_type == "image":
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "image",
            "image": {
                "link": clean_url
            }
        }
        if caption:
            payload["image"]["caption"] = caption

    elif media_type == "document":
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "document",
            "document": {
                "link": f"{settings.MEDIA_BASE_URL}{media_url}",
                "filename": filename or "archivo"
            }
        }
        if caption:
            payload["document"]["caption"] = caption

    else:
        raise Exception(f"Tipo no soportado: {media_type}")

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            url,
            headers=headers,
            json=payload
        )

    if response.status_code >= 400:
        logger.warning(
            "whatsapp_media_send_failed",
            extra={"status_code": response.status_code, "media_type": media_type},
        )
        raise Exception(f"WhatsApp media send failed: {response.status_code}")
