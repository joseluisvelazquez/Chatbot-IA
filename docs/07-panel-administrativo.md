# Panel Administrativo

## Descripción General

El panel administrativo es una interfaz web estática ubicada en la carpeta `panel/`. Se sirve desde el backend FastAPI mediante `StaticFiles`, configurado en `app/main.py` bajo la ruta `/panel`.

El panel permite consultar verificaciones, conversaciones, mensajes, inconsistencias y métricas. También permite enviar respuestas y archivos desde el personal autorizado hacia el cliente por WhatsApp.

## Estructura Del Panel

Archivos principales:

- `panel/index.html`: página base del panel.
- `panel/pages/dashboard.html`: vista de métricas.
- `panel/pages/conversaciones.html`: vista de chat.
- `panel/pages/verificaciones.html`: vista de verificaciones.
- `panel/pages/cobranza.html`: vista preparada, pero pendiente de integración operativa.

Módulos JavaScript:

- `panel/js/app.js`: autenticación, navegación y carga de vistas.
- `panel/js/api.js`: cliente HTTP para consumir el backend.
- `panel/js/store.js`: estado central del panel.
- `panel/js/websocket.js`: conexión WebSocket y actualización en tiempo real.
- `panel/js/chat.js`: lógica de conversaciones, mensajes, adjuntos y vista de imágenes.
- `panel/js/verifications.js`: tabla, filtros y drawer de verificaciones.
- `panel/js/dashboard.js`: carga y renderizado de métricas.
- `panel/js/ui.js`: componentes visuales auxiliares.

## Autenticación En El Panel

El panel intenta autenticar al usuario mediante:

1. Token recibido en query string.
2. Intercambio del token en `/api/auth/exchange`.
3. Validación de sesión mediante `/api/auth/me`.
4. En ambiente local, fallback a `/api/auth/dev-login`.

Esta lógica se encuentra en `panel/js/app.js` y se conecta con `app/router/auth_router.py`.

## Vista De Conversaciones

La vista `panel/pages/conversaciones.html` permite:

- Consultar conversaciones.
- Buscar chats.
- Filtrar conversaciones no leídas.
- Ver historial de mensajes.
- Enviar mensajes.
- Adjuntar archivos.
- Previsualizar imágenes.
- Usar indicador de escritura mediante WebSocket.

El backend correspondiente se encuentra en `app/router/panel_router.py`, con endpoints como:

- `GET /api/panel/conversations`
- `GET /api/panel/messages/{session_id}`
- `POST /api/panel/messages`
- `POST /api/panel/messages/file`
- `POST /api/panel/conversations/{session_id}/read`

## Vista De Verificaciones

La vista de verificaciones permite consultar folios, cuentas, teléfono, estado, progreso, paso actual, inconsistencias y última actividad. También incluye un drawer lateral para observar detalles del cliente, SIGA, progreso e inconsistencias.

Archivos relacionados:

- `panel/pages/verificaciones.html`
- `panel/js/verifications.js`
- `app/router/panel_router.py`
- `app/services/verification_panel_service.py`

## Vista De Dashboard

El dashboard muestra:

- Total de sesiones.
- Sesiones activas.
- Mensajes entrantes.
- Mensajes salientes.
- Inconsistencias abiertas.
- Funnel de verificación.
- Tiempo promedio entre estados.
- Métricas de SIGA Bridge para roles autorizados.

Archivos relacionados:

- `panel/pages/dashboard.html`
- `panel/js/dashboard.js`
- `app/router/panel_router.py`

## Vista De Cobranza

La vista `panel/pages/cobranza.html` indica explícitamente que el módulo quedó preparado dentro del panel, pero todavía no tiene flujos operativos habilitados.

## Pendientes De Validar

- Confirmar qué roles de negocio usarán cada vista del panel en producción.
- El módulo de Cobranza debe considerarse pendiente de integración.
