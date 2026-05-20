# Arquitectura General

## Visión General

La arquitectura del sistema se compone de un backend FastAPI, un panel administrativo web, una base de datos MySQL, servicios de integración con WhatsApp Cloud API y servicios de consulta hacia SIGA local o SIGA Bridge.

El archivo `app/main.py` actúa como punto de entrada principal. En este archivo se registran los routers, se montan archivos estáticos, se configura CORS y se inicializa un scheduler para recordatorios.

## Componentes Arquitectónicos

### Backend FastAPI

El backend centraliza la lógica del sistema. Sus responsabilidades son:

- Recibir webhooks de WhatsApp.
- Procesar mensajes mediante el motor de flujo.
- Persistir mensajes, sesiones, verificaciones e inconsistencias.
- Exponer endpoints para el panel.
- Administrar autenticación.
- Transmitir eventos por WebSocket.
- Consultar SIGA local o SIGA Bridge.

Archivos principales:

- `app/main.py`
- `app/api/webhook.py`
- `app/router/panel_router.py`
- `app/router/auth_router.py`
- `app/router/media_router.py`
- `app/router/siga_bridge_router.py`

### Motor Conversacional

El motor conversacional se ubica en `app/core/`. Usa estados, intenciones, renderizado de mensajes y reglas especiales para avanzar en el proceso de verificación.

Archivos principales:

- `app/core/states/states.py`
- `app/core/flow/flow.py`
- `app/core/flow/flow_engine.py`
- `app/core/states/state_renderer.py`
- `app/core/states/state_handlers.py`
- `app/core/intents/intents.py`
- `app/core/intents/intent_router.py`

### Servicios De Negocio

La carpeta `app/services/` concentra lógica auxiliar y de negocio. Incluye servicios para sesiones, mensajes, media, recordatorios, verificación, inconsistencias, IA, FAQ y SIGA Bridge.

Ejemplos:

- `app/services/session_service.py`
- `app/services/message_service.py`
- `app/services/verification_service.py`
- `app/services/inconsistencias_service.py`
- `app/services/siga_bridge.py`
- `app/services/ai/ai_service.py`

### Base De Datos

El sistema utiliza MySQL, configurado desde variables de entorno. Los modelos se concentran en `app/db/models.py`, mientras que la conexión y sesiones SQLAlchemy se definen en `app/db/session.py`.

### Panel Administrativo

El panel se encuentra en `panel/` y se sirve como contenido estático. Se compone de vistas HTML y módulos JavaScript.

Vistas principales:

- `panel/pages/dashboard.html`
- `panel/pages/conversaciones.html`
- `panel/pages/verificaciones.html`
- `panel/pages/cobranza.html`

Módulos principales:

- `panel/js/app.js`
- `panel/js/api.js`
- `panel/js/store.js`
- `panel/js/websocket.js`
- `panel/js/chat.js`
- `panel/js/verifications.js`
- `panel/js/dashboard.js`

### Integraciones Externas

El sistema se integra con:

- WhatsApp Cloud API mediante `app/adapters/whatsapp_client.py`.
- SIGA local mediante consultas SQLAlchemy en `app/siga/siga_repository.py`.
- SIGA Bridge mediante `app/services/siga_bridge.py`.
- Google Gemini mediante `app/services/ai/ai_service.py`.

## Flujo Arquitectónico General

1. El cliente envía un mensaje por WhatsApp.
2. Meta llama al endpoint `/webhook`.
3. El backend valida y normaliza el mensaje.
4. El sistema obtiene o crea una sesión de chat.
5. El motor conversacional procesa el estado y genera una respuesta.
6. Se guardan mensajes, eventos, avance e inconsistencias.
7. Se emiten eventos WebSocket para actualizar el panel.
8. El backend envía la respuesta al cliente por WhatsApp.

## Pendientes De Validar

- El código del Bridge PHP no está incluido en el repositorio.
- No se identificó documentación formal de despliegue en producción además de `Dockerfile` y `docker-compose.yml`.
