# Flujo WhatsApp Webhook

## Descripción General

El flujo de WhatsApp inicia cuando Meta envía eventos al endpoint `/webhook`, definido en `app/api/webhook.py`. Este archivo concentra la lógica de recepción, validación, deduplicación, persistencia, ejecución del motor conversacional y emisión de eventos al panel.

## Verificación Del Webhook

El endpoint `GET /webhook` valida la suscripción de Meta comparando `hub.verify_token` con `settings.VERIFY_TOKEN`. Si coincide, responde con `hub.challenge`; de lo contrario, devuelve error 403.

Archivo relacionado:

- `app/api/webhook.py`

## Recepción De Mensajes

El endpoint `POST /webhook` realiza los siguientes pasos:

1. Lee el cuerpo crudo de la petición.
2. Verifica la firma de Meta si `META_APP_SECRET` está configurado.
3. Decodifica el JSON recibido.
4. Normaliza el payload mediante `parse_meta_payload`.
5. Ignora eventos de estado de WhatsApp, como entregado o leído.
6. Valida que el evento tenga teléfono, `message_id` y contenido procesable.

La normalización del payload se encuentra en `app/adapters/meta_webhook.py`. Ahí se procesan mensajes de texto, botones, listas, imágenes, documentos y tipos no soportados.

## Control De Duplicados Y Concurrencia

El webhook usa `message_id` para evitar procesar dos veces un mismo mensaje. La función `get_message_by_message_id` se encuentra en `app/services/message_service.py`.

También se implementa un bloqueo por teléfono mediante un diccionario de `asyncio.Lock`, con el objetivo de evitar que dos mensajes del mismo número modifiquen la misma sesión de forma simultánea.

## Persistencia Del Mensaje

Una vez validado el evento, el sistema obtiene o crea una sesión con `get_or_create_session`, definida en `app/services/session_service.py`. Después guarda el mensaje entrante en la tabla `messages` mediante `save_message`.

Si el mensaje contiene imagen o documento, se utiliza `app/services/media_service.py` y `app/services/media_downloader.py` para descargar el archivo desde Meta y guardarlo en la carpeta `media/`.

## Procesamiento Conversacional

El mensaje se envía a `process_message` en `app/core/flow/flow_engine.py`. Esta función determina la intención, evalúa el estado actual de la sesión, aplica reglas especiales y devuelve:

- Respuesta de texto.
- Siguiente estado.
- Botones.
- Imagen opcional.
- Parche de inconsistencia, cuando aplica.

## Actualización Del Sistema

Después del procesamiento, el webhook:

- Guarda la respuesta del bot como mensaje saliente.
- Actualiza la sesión.
- Actualiza recordatorios de inactividad.
- Registra inconsistencias si existen.
- Calcula deltas para dashboard.
- Construye snapshot de verificación.
- Emite eventos WebSocket.

## Envío De Respuesta A WhatsApp

La respuesta se envía mediante `send_whatsapp_message` en `app/adapters/whatsapp_client.py`. Este adaptador construye payloads para:

- Texto.
- Botones.
- Listas.
- Documentos.
- Botones con imagen.

## Eventos En Tiempo Real

El webhook emite eventos como:

- `new_message`
- `dashboard_update`
- `conversation_updated`
- `verification_update`
- `verification_updated`
- `siga_snapshot_updated`

Estos eventos son recibidos por el panel en `panel/js/websocket.js`.

## Pendientes De Validar

- La prueba `app/tests/test_webhook.py` parece usar una estructura antigua del webhook y podría requerir actualización.
- La disponibilidad real de Meta y los valores productivos de tokens dependen del archivo `.env`, el cual no debe documentarse con secretos.
