from fastapi import APIRouter, UploadFile, File, HTTPException
import os
from datetime import datetime

router = APIRouter(prefix="/api/panel", tags=["media"])

MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    allowed_types = [
        "image/jpeg",
        "image/png",
        "application/pdf"
    ]

    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo no permitido")

    ext = file.filename.split(".")[-1]
    filename = f"{datetime.utcnow().timestamp()}.{ext}"

    file_path = os.path.join(MEDIA_DIR, filename)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    return {
        "url": f"/media/{filename}",
        "filename": file.filename
    }