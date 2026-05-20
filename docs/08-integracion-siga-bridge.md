# Integración SIGA Bridge

## Descripción General

El sistema cuenta con dos vías para consultar información relacionada con SIGA:

1. Consulta local a tablas modeladas en SQLAlchemy, mediante `app/siga/siga_repository.py`.
2. Consulta externa mediante SIGA Bridge, implementada del lado FastAPI como cliente HTTP en `app/services/siga_bridge.py`.

El código PHP del Bridge no se encuentra dentro de este repositorio, por lo que la documentación se basa en el cliente FastAPI y el contrato descrito en `app/services/SIGA_BRIDGE.md`.

## Consulta Local A SIGA

El archivo `app/siga/siga_repository.py` consulta modelos como:

- `BitacoraVentas`
- `DomiciliosHorariosEntrega`
- `VerificacionCuenta`

Funciones relevantes:

- `obtener_venta_por_folio`
- `obtener_folios_pendientes_por_telefono`
- `obtener_verificacion_por_no_cuenta`
- `obtener_domicilio_por_movimiento`
- `construir_nombre`
- `construir_pago_inicial`
- `construir_no_cuenta`

## Cliente SIGA Bridge

El cliente principal se encuentra en `app/services/siga_bridge.py`. Este cliente realiza solicitudes HTTP hacia el Bridge externo y valida que la respuesta cumpla con el contrato esperado.

Acciones identificadas:

- `ping`
- `customer`
- `folio`
- `verification`
- `account`
- `payments`

El cliente envía el header `X-Bridge-Token` y espera respuestas JSON. También implementa:

- Timeouts configurables.
- Reintentos para errores transitorios.
- Validación del contrato de respuesta.
- Manejo de errores HTTP.
- Métricas internas.
- Caché para lecturas.

## Contrato Esperado

El documento `app/services/SIGA_BRIDGE.md` indica que el contrato esperado tiene la forma:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "version": "v1",
    "timestamp": "2026-04-27T12:00:00-06:00",
    "action": "ping"
  }
}
```

## Integración Con Verificaciones

Cuando `SIGA_BRIDGE_ENABLED` está habilitado, el webhook puede buscar información del folio mediante `lookup_verification_for_folio`, definida en `app/services/siga_bridge_integration.py`.

Los datos obtenidos se normalizan en `app/services/siga_bridge_sale.py`, donde se construye un snapshot estándar con:

- Folio.
- Número de cuenta.
- Cliente.
- Producto.
- Fecha de venta.
- Pago.
- Componentes.
- Fuente de información.

## Caché Del Bridge

El archivo `app/services/siga_bridge_cache.py` guarda información normalizada en `chat_sessions.extra_json`, dentro de la clave `siga_bridge`. Esto evita consultar repetidamente el Bridge para el mismo folio y permite usar datos obsoletos si el Bridge falla.

## Endpoints Internos Del Panel

El router `app/router/siga_bridge_router.py` expone endpoints bajo `/api/panel/siga-bridge`, restringidos a roles autorizados:

- `GET /api/panel/siga-bridge/ping`
- `GET /api/panel/siga-bridge/customer`
- `GET /api/panel/siga-bridge/account`
- `GET /api/panel/siga-bridge/verification`
- `GET /api/panel/siga-bridge/metrics`

## Pendientes De Validar

- El código PHP del Bridge no está presente en el repositorio.
- No se puede confirmar desde este repositorio si el Bridge realiza escrituras hacia SIGA; el cliente FastAPI observado realiza lecturas.
- La disponibilidad y formato real de cada endpoint del Bridge debe validarse en ambiente de integración.
