# Base De Datos

## Descripción General

El sistema utiliza MySQL como base de datos principal. La conexión se configura en `app/db/session.py` usando SQLAlchemy y PyMySQL. Las variables se obtienen desde `app/config/settings.py`.

El archivo central de modelos es `app/db/models.py`. En él se definen tanto tablas relacionadas con SIGA como tablas propias del chatbot y panel administrativo.

## Conexión

La URL de conexión se construye a partir de:

- `DB_HOST`
- `DB_PORT`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`

La conexión usa `charset=utf8mb4`, `pool_pre_ping=True` y `pool_recycle=3600`.

## Tablas Propias Del Chatbot

### `chat_sessions`

Registra sesiones conversacionales por teléfono, estado actual, folio, último mensaje, fecha de actividad, intentos de IA, intentos de folio inválido y contador de mensajes no leídos.

Modelo: `ChatSessions`.

### `messages`

Registra mensajes entrantes, salientes y de agente. Incluye contenido, dirección, tipo, URL de media, nombre de archivo y `message_id`.

Modelo: `Message`.

### `flow_events`

Registra transiciones del flujo conversacional. Guarda estado origen, estado destino, texto detonador, intención detectada y payload del evento.

Modelo: `FlowEvent`.

### `verificacion_cuenta`

Almacena el avance de verificación por número de cuenta. El avance se guarda en una columna JSON y se controla mediante una versión.

Modelo: `VerificacionCuenta`.

### `inconsistencias`

Registra inconsistencias asociadas a teléfono, folio y sesión. Usa `extra_json` para almacenar detalle estructurado, severidad, contador y resoluciones.

Modelo: `Inconsistencias`.

### `reminders`

Registra recordatorios de inactividad, con programación, envío y cancelación.

Modelo: `Reminder`.

### `panel_sessions`

Guarda sesiones activas o revocadas del panel administrativo.

Modelo: `PanelSession`.

### `auth_tokens`

Registra identificadores únicos de tokens firmados para evitar reutilización.

Modelo: `AuthToken`.

## Tablas Relacionadas Con SIGA

Entre los modelos que representan información de SIGA se identifican:

- `bitacora_ventas`
- `clientes`
- `clientes_aval`
- `clientes_credito_directo`
- `cuentas`
- `domicilios_horarios_entrega`
- `estados_cuenta`
- `saldos`
- `transacciones`
- `productos`
- `planes_pago`
- `ventas_documentos`

Estas tablas son usadas para consultar datos de venta, domicilio, cuenta, saldos, productos y documentos.

## Migración Manual Identificada

Existe un archivo de migración manual:

- `app/db/migrations/20260416_panel_consistency.md`

Este documento incluye cambios para:

- Agregar columnas de resolución en `inconsistencias`.
- Agregar versión en `verificacion_cuenta`.
- Agregar constraint único e índice en `messages.message_id`.

## Pendientes De Validar

- No se identificó una herramienta de migraciones automatizadas como Alembic.
- Los dumps SQL grandes no fueron revisados completamente; la descripción se basa en modelos SQLAlchemy.
- Se debe validar que todos los modelos coincidan con el esquema real de producción.
