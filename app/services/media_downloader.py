from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import logging

import requests

from app.config.settings import settings

logger = logging.getLogger(__name__)

# app/services/media_downloader.py -> subimos 2 niveles y caemos en /app
MEDIA_DIR = Path.cwd() / "media" # Ruta del docker
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

GRAPH_API_VERSION = "v21.0"
REQUEST_TIMEOUT = (10, 60)  # connect, read

# MIME permitidos y extensión canónica
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}


def _build_auth_headers() -> dict[str, str]:
    token = getattr(settings, "WHATSAPP_TOKEN", None)
    if not token:
        raise RuntimeError("WHATSAPP_TOKEN no configurado")

    return {
        "Authorization": f"Bearer {token}"
    }


def _normalize_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""

    return content_type.split(";")[0].strip().lower()


def _extension_from_content_type(content_type: str) -> str:
    extension = ALLOWED_CONTENT_TYPES.get(content_type)
    if not extension:
        raise ValueError(f"Tipo de contenido no soportado: {content_type}")
    return extension


def get_media_url(media_id: str) -> str:
    if not media_id:
        raise ValueError("media_id requerido")

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{media_id}"

    response = requests.get(
        url,
        headers=_build_auth_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    direct_url = payload.get("url")

    if not direct_url:
        raise RuntimeError("Meta no devolvió URL de descarga para la media")

    return direct_url


def download_and_store(media_id: str) -> str:
    """
    Descarga media desde Meta, la guarda físicamente en app/media
    y devuelve una ruta relativa para persistir en DB/UI:
    /media/<archivo>
    """
    direct_url = get_media_url(media_id)

    response = requests.get(
        direct_url,
        headers=_build_auth_headers(),
        timeout=REQUEST_TIMEOUT,
        stream=True,
    )
    response.raise_for_status()

    content_type = _normalize_content_type(response.headers.get("Content-Type"))
    extension = _extension_from_content_type(content_type)

    generated_name = f"{uuid4().hex}.{extension}"
    destination = MEDIA_DIR / generated_name

    try:
        with destination.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
        logger.info(
            "media_download_stored",
            extra={"content_type": content_type, "size_bytes": destination.stat().st_size},
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        response.close()

    return f"/media/{generated_name}"


def build_public_media_url(relative_media_url: str) -> str:
    """
    Convierte /media/archivo.ext a URL pública absoluta.
    Úsalo solo cuando vayas a enviar el archivo hacia Meta.
    """
    if not relative_media_url:
        raise ValueError("relative_media_url requerido")

    if relative_media_url.startswith("http://") or relative_media_url.startswith("https://"):
        return relative_media_url

    base_url = (
        getattr(settings, "MEDIA_BASE_URL", None)
        or getattr(settings, "BASE_URL", None)
        or ""
    ).rstrip("/")

    if not base_url:
        raise RuntimeError("MEDIA_BASE_URL o BASE_URL no configurado")

    if not relative_media_url.startswith("/"):
        relative_media_url = f"/{relative_media_url}"

    return f"{base_url}{relative_media_url}"
