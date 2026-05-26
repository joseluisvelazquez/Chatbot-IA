# Soporte de stickers y reacciones de WhatsApp

## Stickers

WhatsApp Cloud API entrega los stickers como mensajes entrantes con `type = "sticker"` y un objeto `sticker` que incluye al menos:

- `id`: media ID de Meta.
- `mime_type`: normalmente `image/webp`.
- `animated`: bandera opcional.

El parser normaliza estos mensajes como `type="sticker"`, conserva `media_id`, `mime_type` y guarda metadata mínima en `messages.extra_json`:

```json
{
  "sticker": {
    "media_id": "media-id",
    "mime_type": "image/webp",
    "animated": false
  }
}
```

El downloader ahora permite `image/webp`, por lo que intenta descargar el sticker a `/media/<uuid>.webp`. Si falla la descarga, el mensaje se guarda de todos modos y el panel muestra un fallback visual.

En conversaciones se muestra `🧩 Sticker recibido`. En el chat se renderiza una burbuja con el texto `El cliente envio un sticker` y, si existe preview local, la imagen WebP.

## Reacciones

WhatsApp Cloud API entrega reacciones con `type = "reaction"` y un objeto:

```json
{
  "reaction": {
    "message_id": "wamid-original",
    "emoji": "👍"
  }
}
```

`reaction.message_id` es el ID de WhatsApp del mensaje original. Si `emoji` viene vacío, se interpreta como eliminación de reacción.

Las reacciones se persisten en `message_reactions`, asociadas al mensaje interno encontrado por `messages.message_id`.

## Base de datos

Migraciones relacionadas:

- `app/db/migrations/20260525_message_extra_json.sql`: agrega `messages.extra_json`.
- `app/db/migrations/20260526_message_reactions.sql`: crea la tabla `message_reactions`.

La tabla `message_reactions` usa `utf8mb4_unicode_ci` para soportar emojis.

## WebSocket y panel

Cuando llega un sticker, se emite `new_message` con `message_kind = "sticker"`.

Cuando llega una reacción asociada, se emite:

```json
{
  "type": "reaction_update",
  "payload": {
    "session_id": 1,
    "message_id": 123,
    "wa_message_id_original": "wamid-original",
    "reaction": {
      "reaction_emoji": "👍"
    },
    "removed": false
  }
}
```

El panel actualiza el mensaje original sin recargar. Si no se encuentra el mensaje original, se guarda un evento discreto como mensaje tipo `reaction`: `El cliente reacciono con 👍 a un mensaje anterior`.

## Consideraciones

Para poder asociar reacciones a mensajes salientes, el sistema ahora intenta persistir el ID devuelto por Meta en `messages.message_id` después del envío. Los mensajes históricos salientes que quedaron con `message_id = NULL` no podrán asociarse retroactivamente a una reacción de WhatsApp.
