# Seguridad, Roles Y Sesiones

## Descripción General

El sistema implementa seguridad para el panel administrativo mediante tokens firmados, sesiones persistentes, cookies HTTP-only, validación de empresa y control de roles.

Los archivos principales son:

- `app/router/auth_router.py`
- `app/security/auth_service.py`
- `app/security/auth_dependencies.py`
- `app/security/auth_models.py`
- `app/db/models.py`

## Autenticación Mediante Token De SIGA

El endpoint `/api/auth/exchange` recibe un token firmado. La función `decode_siga_token`, ubicada en `app/security/auth_service.py`, valida:

- Firma HMAC.
- Usuario.
- Puesto.
- Empresa.
- Expiración.
- Identificador único `jti`.
- Uso único del token.

Los `jti` utilizados se guardan en la tabla `auth_tokens` para evitar reutilización.

## Sesión Del Panel

Después de validar el token, se crea una sesión mediante `create_panel_session`. La sesión se almacena en la tabla `panel_sessions` y se entrega al navegador mediante una cookie HTTP-only.

La cookie se configura en `app/router/auth_router.py` usando valores definidos en `app/config/settings.py`:

- `PANEL_SESSION_COOKIE_NAME`
- `PANEL_SESSION_SECURE_COOKIE`
- `PANEL_SESSION_SAMESITE`

## Roles Identificados

Los roles se definen en `app/security/auth_models.py`:

- `admin`
- `ventas`
- `cobranza`
- `sistemas`
- `jefe_operativo`
- `viewer`

El mapeo entre puesto y rol se encuentra en `ROLE_MAP`, dentro de `app/security/auth_service.py`.

## Restricción Por Empresa

La función `is_allowed_panel_company` permite únicamente las empresas con identificadores `1` y `8`, de acuerdo con `ALLOWED_PANEL_COMPANY_IDS`.

Esta validación se usa en rutas del panel y en el router de SIGA Bridge.

## Restricción Por Rol

El helper `require_roles` de `app/security/auth_dependencies.py` permite restringir endpoints a ciertos roles.

El panel también aplica restricciones de respuesta mediante `require_reply_permission`, definida en `app/router/panel_router.py`, donde se permite responder a:

- `admin`
- `ventas`
- `cobranza`
- `jefe_operativo`
- `sistemas`

## Restricción Para Cobranza

La función `restrict_to_assigned` de `app/security/auth_service.py` filtra información para usuarios con rol `cobranza`. En ese caso, busca el `nombre_resumido` del colaborador y limita las consultas a cuentas asignadas mediante `Cuentas.agente_verificador`.

## Seguridad En WebSocket

El endpoint WebSocket `/api/panel/ws` valida la cookie `panel_session`. Después de autenticar al usuario, asigna al WebSocket:

- Usuario actual.
- Lista de sesiones permitidas.

El administrador de conexiones `app/websockets/manager.py` filtra eventos por rol y por sesiones permitidas.

## Pendientes De Validar

- En producción debería validarse que `PANEL_SESSION_SECURE_COOKIE` esté configurado correctamente para HTTPS.
- Existe referencia compilada a `rbac.py` en `__pycache__`, pero no se encontró archivo fuente `app/security/rbac.py`; pendiente validar si fue eliminado o si no forma parte del código activo.
