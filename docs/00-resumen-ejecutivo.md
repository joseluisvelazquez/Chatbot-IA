# Resumen Ejecutivo

## Descripción General

El proyecto corresponde al desarrollo de un sistema de chatbot para WhatsApp orientado a la verificación de ventas, atención inicial al cliente y apoyo operativo mediante un panel administrativo web. La solución se encuentra implementada principalmente con un backend en FastAPI, un panel web estático, comunicación en tiempo real mediante WebSocket, persistencia en MySQL y una integración progresiva con SIGA mediante un cliente denominado SIGA Bridge.

El backend principal se inicializa en `app/main.py`, donde se registran los routers del webhook, panel administrativo, autenticación, carga de archivos, integración con SIGA Bridge y disparadores externos. El panel web se encuentra en la carpeta `panel/` y se sirve desde el mismo backend mediante la ruta `/panel`.

## Propósito Del Sistema

El sistema permite automatizar parte del proceso de verificación de una venta a través de WhatsApp. El usuario proporciona o confirma información relacionada con un folio, y el chatbot avanza por un flujo de estados que valida datos como nombre, domicilio, fecha de venta, producto, componentes, pago inicial, información de pagos, métodos de pago, planes y beneficios.

Cuando se detectan inconsistencias, dudas o situaciones que requieren intervención humana, el sistema registra la información para que pueda ser revisada desde el panel administrativo. El panel permite visualizar conversaciones, mensajes, verificaciones, inconsistencias, métricas operativas y eventos en tiempo real.

## Componentes Principales

- Backend FastAPI: implementado en `app/main.py`, `app/api/`, `app/router/`, `app/services/` y `app/core/`.
- Webhook de WhatsApp/Meta: implementado en `app/api/webhook.py`, `app/adapters/meta_webhook.py` y `app/adapters/whatsapp_client.py`.
- Motor conversacional: implementado en `app/core/flow/`, `app/core/states/` y `app/core/intents/`.
- Panel administrativo: implementado en `panel/index.html`, `panel/pages/` y `panel/js/`.
- WebSocket: implementado en `app/router/panel_router.py`, `app/websockets/manager.py` y `panel/js/websocket.js`.
- Autenticación y sesiones: implementadas en `app/router/auth_router.py` y `app/security/`.
- SIGA Bridge: implementado del lado FastAPI en `app/services/siga_bridge.py`, `app/services/siga_bridge_cache.py`, `app/services/siga_bridge_integration.py` y `app/router/siga_bridge_router.py`.
- Base de datos: modelada en `app/db/models.py` y conectada mediante `app/db/session.py`.

## Resultados Relevantes

El repositorio contiene productos técnicos tangibles:

- Backend FastAPI funcional.
- Webhook para integración con WhatsApp Cloud API.
- Panel administrativo web.
- Comunicación en tiempo real mediante WebSocket.
- Flujo conversacional por estados.
- Registro persistente de sesiones, mensajes, verificaciones e inconsistencias.
- Dashboard con métricas operativas.
- Cliente SIGA Bridge con validación de contrato, caché y métricas.
- Manejo de adjuntos de imagen, documento PDF y PNG/JPEG.
- Autenticación de panel mediante token firmado y cookies HTTP-only.

## Pendientes De Validar

- El código PHP del SIGA Bridge no se encuentra dentro de este repositorio; únicamente se identificó el cliente FastAPI y el documento de contrato `app/services/SIGA_BRIDGE.md`.
- Los archivos SQL grandes `dbs55265C.sql` y `siga_dump.sql` no fueron analizados por completo por su tamaño; la descripción de base de datos se basa en los modelos SQLAlchemy existentes.
- Algunos archivos parecen ser legacy o no estar conectados desde `app/main.py`, por ejemplo `app/api/panel_send.py`, `app/media/main.py`, `app/models/message.py` y `app/schemas/webhook.py`.
- El módulo de Cobranza del panel aparece como espacio preparado, pero sin flujos operativos habilitados en `panel/pages/cobranza.html`.
