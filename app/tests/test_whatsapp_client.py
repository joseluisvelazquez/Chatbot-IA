import asyncio

from app.adapters import whatsapp_client


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_long_button_message_is_split_before_sending_to_meta(monkeypatch):
    sent_payloads = []

    async def fake_send(payload):
        sent_payloads.append(payload)
        return FakeResponse()

    monkeypatch.setattr(whatsapp_client, "_send", fake_send)

    long_text = "x" * (whatsapp_client.META_INTERACTIVE_BODY_LIMIT + 1)
    buttons = [{"id": "PAGOS_OK", "label": "✅ Está claro"}]

    asyncio.run(
        whatsapp_client.send_whatsapp_message(
            "5215551234567",
            long_text,
            buttons,
        )
    )

    assert [payload["type"] for payload in sent_payloads] == ["text", "interactive"]
    assert sent_payloads[0]["text"]["body"] == long_text
    assert sent_payloads[1]["interactive"]["body"]["text"] == whatsapp_client.BUTTON_PROMPT_TEXT
    assert sent_payloads[1]["interactive"]["action"]["buttons"][0]["reply"]["id"] == "PAGOS_OK"


def test_failed_interactive_send_falls_back_to_text(monkeypatch):
    sent_payloads = []

    async def fake_send(payload):
        sent_payloads.append(payload)
        if payload["type"] == "interactive":
            return FakeResponse(
                status_code=400,
                payload={"error": {"code": 100, "type": "OAuthException"}},
            )
        return FakeResponse()

    monkeypatch.setattr(whatsapp_client, "_send", fake_send)

    asyncio.run(
        whatsapp_client.send_whatsapp_message(
            "5215551234567",
            "Mensaje con botones",
            [{"id": "PAGOS_OK", "label": "✅ Está claro"}],
        )
    )

    assert [payload["type"] for payload in sent_payloads] == ["interactive", "text"]
    assert "Mensaje con botones" in sent_payloads[1]["text"]["body"]
    assert "✅ Está claro" in sent_payloads[1]["text"]["body"]


def test_unreachable_image_link_sends_buttons_without_image(monkeypatch):
    sent_payloads = []

    async def fake_reachable(_image_url):
        return False

    async def fake_send(payload):
        sent_payloads.append(payload)
        return FakeResponse()

    monkeypatch.setattr(whatsapp_client, "_image_link_is_reachable", fake_reachable)
    monkeypatch.setattr(whatsapp_client, "_send", fake_send)

    asyncio.run(
        whatsapp_client.send_whatsapp_message(
            "5215551234567",
            "Mensaje con imagen opcional",
            [{"id": "PAGOS_OK", "label": "✅ Está claro"}],
            image_id="https://example.invalid/metodos_pago.jpg",
        )
    )

    assert [payload["type"] for payload in sent_payloads] == ["interactive"]
    assert "header" not in sent_payloads[0]["interactive"]
    assert sent_payloads[0]["interactive"]["action"]["buttons"][0]["reply"]["id"] == "PAGOS_OK"


def test_unreachable_image_link_uploads_local_media_when_available(monkeypatch):
    sent_payloads = []

    async def fake_reachable(_image_url):
        return False

    async def fake_upload(image_url):
        assert image_url == "https://chatbot.example/media/imagenes_verificacion/metodos_pago.jpg"
        return "uploaded-media-id"

    async def fake_send(payload):
        sent_payloads.append(payload)
        return FakeResponse()

    monkeypatch.setattr(whatsapp_client, "_image_link_is_reachable", fake_reachable)
    monkeypatch.setattr(whatsapp_client, "_upload_local_media_to_meta", fake_upload)
    monkeypatch.setattr(whatsapp_client, "_send", fake_send)

    asyncio.run(
        whatsapp_client.send_whatsapp_message(
            "5215551234567",
            "Mensaje con imagen local",
            [{"id": "PAGOS_OK", "label": "✅ Está claro"}],
            image_id="https://chatbot.example/media/imagenes_verificacion/metodos_pago.jpg",
        )
    )

    assert [payload["type"] for payload in sent_payloads] == ["interactive"]
    assert sent_payloads[0]["interactive"]["header"]["image"] == {"id": "uploaded-media-id"}


def test_asset_filename_is_normalized_to_public_media_url(monkeypatch):
    monkeypatch.setattr(whatsapp_client.settings, "MEDIA_BASE_URL", "https://chatbot.example")

    assert (
        whatsapp_client._normalize_image_source("metodos_pago.jpg")
        == "https://chatbot.example/media/imagenes_verificacion/metodos_pago.jpg"
    )


def test_local_media_path_for_public_media_url():
    path = whatsapp_client._local_media_path_for_source(
        "https://chatbot.example/media/imagenes_verificacion/metodos_pago.jpg"
    )

    assert path is not None
    assert path.name == "metodos_pago.jpg"
