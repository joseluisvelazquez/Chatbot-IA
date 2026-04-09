from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(prefix="/api/panel", tags=["media"])

# app/router/media_router.py -> subimos 2 niveles y caemos en /app
MEDIA_DIR = Path("/app/media")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# MIME permitidos y extensión canónica
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
CHUNK_SIZE = 1024 * 1024  # 1 MB


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="Archivo no proporcionado")

    content_type = (file.content_type or "").lower().strip()
    extension = ALLOWED_CONTENT_TYPES.get(content_type)

    if not extension:
        raise HTTPException(status_code=400, detail="Tipo no permitido")

    generated_name = f"{uuid4().hex}.{extension}"
    destination = MEDIA_DIR / generated_name

    bytes_written = 0

    try:
        with destination.open("wb") as buffer:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break

                bytes_written += len(chunk)

                if bytes_written > MAX_FILE_SIZE_BYTES:
                    buffer.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="Archivo demasiado grande")

                buffer.write(chunk)

    except HTTPException:
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Error guardando archivo") from exc
    finally:
        await file.close()

    return {
        "url": f"/media/{generated_name}",
        "filename": file.filename,
        "content_type": content_type,
        "size": bytes_written,
    }