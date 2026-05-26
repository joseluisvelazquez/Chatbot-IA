from app.adapters.meta_webhook import parse_meta_payload
from app.services.message_metadata import (
    build_outgoing_interactive_metadata,
    build_outgoing_media_metadata,
)
from app.utils.money import format_money


def _payload(message):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [message],
                        }
                    }
                ]
            }
        ]
    }


def test_interactive_button_reply_uses_visible_title():
    parsed = parse_meta_payload(_payload({
        "from": "5215551234567",
        "id": "wamid.1",
        "timestamp": "1710000000",
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {
                "id": "PAGOS_DUDA",
                "title": "Tengo dudas",
            },
        },
    }))

    assert parsed["text"] == "Tengo dudas"
    assert parsed["button_id"] == "PAGOS_DUDA"
    assert parsed["extra_json"]["interactive_reply"]["title"] == "Tengo dudas"


def test_interactive_button_reply_without_title_has_safe_fallback():
    parsed = parse_meta_payload(_payload({
        "from": "5215551234567",
        "id": "wamid.2",
        "timestamp": "1710000000",
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "PAGOS_DUDA"},
        },
    }))

    assert parsed["text"] == "Respuesta interactiva recibida"
    assert parsed["button_id"] == "PAGOS_DUDA"
    assert parsed["extra_json"]["interactive_reply"]["id"] == "PAGOS_DUDA"


def test_outgoing_interactive_metadata_keeps_button_order():
    metadata = build_outgoing_interactive_metadata(
        "Texto principal",
        [
            {"id": "ok", "label": "Esta claro"},
            {"id": "duda", "label": "Tengo dudas"},
        ],
    )

    assert metadata == {
        "interactive": {
            "type": "button",
            "body": "Texto principal",
            "buttons": [
                {"id": "ok", "title": "Esta claro"},
                {"id": "duda", "title": "Tengo dudas"},
            ],
        }
    }


def test_outgoing_media_metadata_with_and_without_local_url():
    local = build_outgoing_media_metadata(
        source="https://chatbot.example/media/imagenes_verificacion/metodos_pago.jpg",
        caption="Datos bancarios",
    )
    remote = build_outgoing_media_metadata(
        source="wa-media-id",
        caption="Video enviado",
        media_type="video",
    )

    assert local["media"]["type"] == "image"
    assert local["media"]["url"] == "/media/imagenes_verificacion/metodos_pago.jpg"
    assert remote["media"]["type"] == "video"
    assert remote["media"]["status"] == "sent_without_local_preview"


def test_sticker_payload_is_parsed_as_media():
    parsed = parse_meta_payload(_payload({
        "from": "5215551234567",
        "id": "wamid.sticker",
        "timestamp": "1710000000",
        "type": "sticker",
        "sticker": {
            "id": "media-sticker-id",
            "mime_type": "image/webp",
            "animated": False,
        },
    }))

    assert parsed["type"] == "sticker"
    assert parsed["text"] == "Sticker recibido"
    assert parsed["media_id"] == "media-sticker-id"
    assert parsed["mime_type"] == "image/webp"
    assert parsed["extra_json"]["sticker"]["mime_type"] == "image/webp"


def test_reaction_payload_is_parsed_with_target_message_and_emoji():
    parsed = parse_meta_payload(_payload({
        "from": "5215551234567",
        "id": "wamid.reaction",
        "timestamp": "1710000000",
        "type": "reaction",
        "reaction": {
            "message_id": "wamid.original",
            "emoji": "👍",
        },
    }))

    assert parsed["type"] == "reaction"
    assert parsed["extra_json"]["reaction"] == {
        "message_id": "wamid.original",
        "emoji": "👍",
    }


def test_empty_reaction_payload_is_parsed_as_delete():
    parsed = parse_meta_payload(_payload({
        "from": "5215551234567",
        "id": "wamid.reaction-delete",
        "timestamp": "1710000000",
        "type": "reaction",
        "reaction": {
            "message_id": "wamid.original",
            "emoji": "",
        },
    }))

    assert parsed["text"] == "Reaccion eliminada"
    assert parsed["extra_json"]["reaction"]["emoji"] is None


def test_format_money_cases():
    assert format_money(1000) == "$1,000.00"
    assert format_money("1000.00") == "$1,000.00"
    assert format_money(6734) == "$6,734.00"
    assert format_money(None) == ""
    assert format_money("$1,000.00") == "$1,000.00"
    assert format_money("valor invalido") == "valor invalido"
