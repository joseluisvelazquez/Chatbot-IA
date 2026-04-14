from app.services.media_downloader import download_and_store
from app.db.models import Message


def handle_incoming_media(parsed: dict, session):
    content = parsed.get("text") or parsed.get("caption")
    if parsed["type"] == "image":
        url = download_and_store(parsed["media_id"])

        return Message(
            session_id=session.id,
            direction="in",
            type="image",
            media_url=url,
            content=content
        )

    if parsed["type"] == "document":
        url = download_and_store(parsed["media_id"])

        return Message(
            session_id=session.id,
            direction="in",
            type="document",
            media_url=url,
            file_name=parsed.get("filename"),
            content=content
        )

    return None