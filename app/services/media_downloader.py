import requests
import os
from datetime import datetime
from app.config.settings import settings

MEDIA_DIR = "media"

os.makedirs(MEDIA_DIR, exist_ok=True)


def get_media_url(media_id: str) -> str:
    url = f"https://graph.facebook.com/v21.0/{media_id}"
    headers = {
        "Authorization": f"Bearer {settings.META_TOKEN}"
    }

    res = requests.get(url, headers=headers)
    res.raise_for_status()

    return res.json()["url"]


def download_and_store(media_id: str) -> str:
    media_url = get_media_url(media_id)

    headers = {
        "Authorization": f"Bearer {settings.META_TOKEN}"
    }

    res = requests.get(media_url, headers=headers)
    res.raise_for_status()

    ext = res.headers.get("Content-Type", "").split("/")[-1] or "bin"
    filename = f"{datetime.utcnow().timestamp()}.{ext}"

    file_path = os.path.join(MEDIA_DIR, filename)

    with open(file_path, "wb") as f:
        f.write(res.content)

    # Ajusta esto a tu dominio real en producción
    return f"/media/{filename}"