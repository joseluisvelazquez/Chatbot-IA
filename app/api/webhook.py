from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from datetime import datetime, timezone
import asyncio

from app.db.session import get_db
from app.adapters.meta_webhook import parse_meta_payload
from app.adapters.whatsapp_client import send_whatsapp_message

from app.config.settings import settings

from app.core.flow_engine import process_message
from app.core.states import ChatState

from app.services.session_service import get_or_create_session, update_session
from app.services.message_service import save_message
from app.services.reminder_service import upsert_inactivity_reminders
from app.services.inconsistencias_service import (
    open_or_patch_inconsistencia,
    close_open_inconsistencia,
)
from app.services.verification_panel_service import build_verification_snapshot
from app.services.media_service import handle_incoming_media

from app.websockets.manager import manager



router = APIRouter()


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/webhook")
async def verify(request: Request):
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge"))
    return PlainTextResponse("Error", status_code=403)


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    data = parse_meta_payload(payload)

    if not data:
        return {"status": "ignored"}

    if data.get("is_status"):
        return {"status": "whatsapp_status"}

    is_media = data.get("type") in ["image", "document"]

    if (
        not data.get("text")
        and not data.get("button_id")
        and not is_media
    ):
        return {"status": "ignored_no_user_input"}

    if data.get("unsupported"):
        await send_whatsapp_message(
            data["phone"],
            "Por favor responde usando las opciones del menú 🙂"
        )
        return {"status": "ok"}

    phone = data["phone"]
    text = data.get("text") or ""
    message_id = data.get("message_id")
    button_id = data.get("button_id")
    if is_media:
        content = "📎 Archivo recibido"
    else:
        content = text if text else button_id

    print(
        "ABOUT TO PROCESS:",
        {
            "type": data.get("type"),
            "text": data.get("text"),
            "button_id": data.get("button_id"),
            "unsupported": data.get("unsupported"),
            "is_status": data.get("is_status"),
        },
    )

    try:
        chat = get_or_create_session(db, phone)

        # Anti-duplicado
        if message_id and chat.last_message_id == message_id:
            db.rollback()
            return {"status": "duplicate"}

        media_msg = None

        try:
            if is_media:
                media_msg = handle_incoming_media(data, chat)

                saved_msg = save_message(
                    db=db,
                    session_id=chat.id,
                    phone=phone,
                    direction="in",
                    content="[MEDIA]",
                    message_id=message_id,
                    type=media_msg.type,
                    media_url=media_msg.media_url,
                    file_name=media_msg.file_name,
                )
            else:
                saved_msg = save_message(
                    db=db,
                    session_id=chat.id,
                    phone=phone,
                    direction="in",
                    content=text if text else f"[BOTON] {button_id}",
                    message_id=message_id,
                )

            chat.unread_count = (chat.unread_count or 0) + 1

            db.commit()
            db.refresh(saved_msg)

        except IntegrityError:
            db.rollback()
            return {"status": "duplicate_ignored"}
        except Exception as e:
            db.rollback()
            if is_media:
                print("ERROR MEDIA:", e)
                return {"status": "media_error"}
            raise

        await manager.send_to_all({
            "type": "new_message",
            "session_id": chat.id,
            "message": {
                "id": saved_msg.id,
                "content": saved_msg.content,
                "direction": saved_msg.direction,
                "created_at": saved_msg.created_at.isoformat() if saved_msg.created_at else "",
                "type": getattr(saved_msg, "type", None),
                "media_url": getattr(saved_msg, "media_url", None),
                "file_name": getattr(saved_msg, "file_name", None),
            },
            "unread_count": chat.unread_count
        })

        await manager.send_to_all({
            "type": "dashboard_update",
            "payload": {
                "messages_in_delta": 1,
                "messages_out_delta": 0,
                "session_id": chat.id
            }
        })

        result = process_message(
            session=chat,
            text=text,
            intent=button_id,
            db=db,
        )
        reply = result.reply
        next_state = result.next_state
        buttons = result.buttons
        previous_state = result.previous_state


        print("🤖 REPLY GENERADO:", repr(reply))

        if reply:
            try:
                bot_msg = save_message(
                    db=db,
                    session_id=chat.id,
                    phone=phone,
                    direction="out",
                    content=reply
                )
                db.commit()
                db.refresh(bot_msg)

                await manager.send_to_all({
                    "type": "new_message",
                    "session_id": chat.id,
                    "message": {
                        "id": bot_msg.id,
                        "content": bot_msg.content,
                        "direction": bot_msg.direction,
                        "created_at": bot_msg.created_at.isoformat() if bot_msg.created_at else "",
                        "type": getattr(bot_msg, "type", None),
                        "media_url": getattr(bot_msg, "media_url", None),
                        "file_name": getattr(bot_msg, "file_name", None),
                    },
                    "unread_count": chat.unread_count
                })


                

            except IntegrityError:
                db.rollback()

        now = utcnow_naive()

        print(
            f"DEBUG: next_state={next_state}, previous_state={previous_state}, buttons={buttons}"
        )

        # --------------------------------------
        # 🧾 Persistencia de inconsistencias
        # --------------------------------------
        if result.inconsistencia_patch:
            open_or_patch_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
                patch=result.inconsistencia_patch,
            )

        if next_state in [
            ChatState.INCONSISTENCIA,
            ChatState.ACLARACION,
            ChatState.LLAMADA,
        ]:
            open_or_patch_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
                patch={
                    "evento": {
                        "ultimo_estado": chat.state,
                        "causa_estado": next_state.value,
                        "ultimo_mensaje": text,
                    }
                },
            )


        if next_state == ChatState.FINALIZADO:
            close_open_inconsistencia(
                db=db,
                phone=phone,
                folio=chat.folio,
                session_id=chat.id,
            )

        # --------------------------------------
        # 💾 persistencia chat_sessions
        # --------------------------------------
        update_session(
            session=chat,
            state=next_state.value,
            last_message=content,
            previous_state=previous_state,
            message_id=message_id,
            last_message_at=now,
        )

        upsert_inactivity_reminders(db, chat)
        db.commit()
        db.refresh(chat)

        try:
            snapshot = build_verification_snapshot(db, chat)
            if snapshot:
                await manager.send_to_all({
                    "type": "verification_update",
                    "payload": snapshot
                })
        except Exception as e:
            print("ERROR snapshot:", e)

    except Exception:
        db.rollback()
        raise

    if reply:
        asyncio.create_task(
            send_whatsapp_message(
                phone,
                reply,
                buttons,
                image_id=result.image_id
            )
        )

    return {"status": "ok"}