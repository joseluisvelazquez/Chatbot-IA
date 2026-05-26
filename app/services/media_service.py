import logging

from app.services.media_downloader import download_and_store
from app.db.models import Message

logger = logging.getLogger(__name__)


def _download_media_safely(media_id: str | None, media_type: str) -> str | None:
    if not media_id:
        return None
    try:
        return download_and_store(media_id)
    except Exception as exc:
        logger.warning(
            "incoming_media_download_failed",
            extra={"media_type": media_type, "error_type": exc.__class__.__name__},
        )
        return None


def handle_incoming_media(parsed: dict, session):
    content = parsed.get("text") or parsed.get("caption")
    if parsed["type"] == "image":
        url = _download_media_safely(parsed.get("media_id"), "image")

        return Message(
            session_id=session.id,
            direction="in",
            type="image",
            media_url=url,
            content=content
        )

    if parsed["type"] == "document":
        url = _download_media_safely(parsed.get("media_id"), "document")

        return Message(
            session_id=session.id,
            direction="in",
            type="document",
            media_url=url,
            file_name=parsed.get("filename"),
            content=content
        )

    if parsed["type"] == "sticker":
        url = _download_media_safely(parsed.get("media_id"), "sticker")

        return Message(
            session_id=session.id,
            direction="in",
            type="sticker",
            media_url=url,
            content="🧩 Sticker recibido",
        )

    return None
