# Objetivo General Y Específicos

## Objetivo General

Desarrollar e integrar un sistema de chatbot por WhatsApp con backend FastAPI, panel administrativo web, almacenamiento en MySQL e integración con SIGA, para automatizar y centralizar el proceso de verificación de ventas, seguimiento de conversaciones e identificación de inconsistencias.

## Objetivos Específicos

### Automatizar La Atención Inicial Por WhatsApp

Implementar un webhook capaz de recibir mensajes desde WhatsApp Cloud API, interpretar entradas de texto, botones, imágenes y documentos, y responder al usuario mediante la API de Meta.

Archivos relacionados:

- `app/api/webhook.py`
- `app/adapters/meta_webhook.py`
- `app/adapters/whatsapp_client.py`

### Implementar Un Flujo Conversacional De Verificación

Diseñar un flujo por estados para guiar al cliente en la confirmación de datos de venta, producto, componentes, pagos, métodos de pago, planes y beneficios.

Archivos relacionados:

- `app/core/flow/flow.py`
- `app/core/flow/flow_engine.py`
- `app/core/states/states.py`
- `app/core/states/state_renderer.py`

### Registrar La Información Del Proceso En MySQL

Persistir sesiones, mensajes, eventos de flujo, verificaciones, recordatorios, autenticación e inconsistencias mediante modelos SQLAlchemy.

Archivos relacionados:

- `app/db/models.py`
- `app/db/session.py`
- `app/services/message_service.py`
- `app/services/session_service.py`
- `app/services/verification_service.py`

### Desarrollar Un Panel Administrativo

Crear una interfaz web para visualizar conversaciones, enviar mensajes, revisar verificaciones, atender inconsistencias y consultar métricas operativas.

Archivos relacionados:

- `panel/index.html`
- `panel/pages/conversaciones.html`
- `panel/pages/verificaciones.html`
- `panel/pages/dashboard.html`
- `panel/js/app.js`
- `panel/js/chat.js`
- `panel/js/verifications.js`
- `panel/js/dashboard.js`

### Implementar Comunicación En Tiempo Real

Incorporar WebSocket para actualizar conversaciones, mensajes, dashboard y verificaciones en el panel sin recargar manualmente la página.

Archivos relacionados:

- `app/websockets/manager.py`
- `app/router/panel_router.py`
- `panel/js/websocket.js`

### Integrar Información De SIGA

Consultar datos locales de SIGA desde modelos existentes y, cuando esté habilitado, complementar la información mediante SIGA Bridge.

Archivos relacionados:

- `app/siga/siga_repository.py`
- `app/services/siga_bridge.py`
- `app/services/siga_bridge_cache.py`
- `app/services/siga_bridge_integration.py`
- `app/router/siga_bridge_router.py`

### Incorporar Seguridad Y Control De Acceso

Gestionar sesiones del panel, roles, permisos por empresa y restricciones de visibilidad según perfil.

Archivos relacionados:

- `app/security/auth_service.py`
- `app/security/auth_dependencies.py`
- `app/router/auth_router.py`
- `app/security/auth_models.py`

## Pendientes De Validar

- No se encontró un documento institucional con objetivos originales; estos objetivos se formularon a partir de funcionalidades reales del repositorio.
