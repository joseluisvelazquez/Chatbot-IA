# SIGA Bridge v1 - FastAPI client

## Configuracion

Variables de entorno:

```text
SIGA_BRIDGE_ENABLED=true
SIGA_BRIDGE_BASE_URL=http://localhost/PruebasP/bridge/
SIGA_BRIDGE_TOKEN=<token-configurado-en-php>
SIGA_BRIDGE_TIMEOUT_CONNECT=2
SIGA_BRIDGE_TIMEOUT_READ=5
```

`SIGA_BRIDGE_TOKEN` nunca debe loguearse ni hardcodearse. Debe coincidir con el token que valida el PHP Bridge mediante `X-Bridge-Token`.

## Headers enviados

```text
X-Bridge-Token: <SIGA_BRIDGE_TOKEN>
Accept: application/json
```

## Timeouts

El cliente usa:

```text
connect: settings.SIGA_BRIDGE_TIMEOUT_CONNECT, default 2s
read: settings.SIGA_BRIDGE_TIMEOUT_READ, default 5s
write: 2s
pool: 2s
```

Hace 1 retry adicional solo para requests GET ante timeout, error transitorio de transporte o estados HTTP `502`, `503`, `504`.

## Contrato esperado

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

El cliente valida que existan exactamente `ok`, `data`, `error` y `meta`, que `meta.version` sea `v1` y que `meta.action` coincida con la accion solicitada.

## Excepciones

```text
SigaBridgeConfigError       Bridge deshabilitado, base_url faltante o token faltante.
SigaBridgeBadRequestError   HTTP 400 desde PHP Bridge.
SigaBridgeUnauthorizedError HTTP 401 desde PHP Bridge.
SigaBridgeRateLimitError    HTTP 429 desde PHP Bridge.
SigaBridgeServerError       HTTP 5xx desde PHP Bridge.
SigaBridgeUnavailableError  Timeout/transporte agotado despues del retry.
SigaBridgeContractError     JSON invalido o contrato v1 roto.
```

## Endpoints internos de prueba

Solo roles `admin` y `jefe_operativo`:

```text
GET /api/panel/siga-bridge/ping
GET /api/panel/siga-bridge/customer?phone=4421234567
GET /api/panel/siga-bridge/account?cuenta=60436
GET /api/panel/siga-bridge/metrics
```

Estos endpoints son probes internos. No reemplazan todavia la logica actual del panel y no realizan escrituras en SIGA.

## Integracion progresiva

Con `SIGA_BRIDGE_ENABLED=true`, el drawer de verificaciones abre primero con datos locales y luego refresca el detalle con lecturas `customer`, `account` y `payments`. Si Bridge falla, el panel conserva los datos locales.

Solo `admin` y `jefe_operativo` ven datos operativos del Bridge en el drawer. El refresh manual usa:

```text
GET /api/panel/verifications/{session_id}?refresh_siga=true
```

Ese refresh evita la cache en memoria y vuelve a poblarla si SIGA responde bien.

El webhook dispara lookup de cliente por telefono en background despues del commit de la sesion para no agregar latencia al flujo de WhatsApp. Si existe `chat_sessions.extra_json`, guarda una cache secundaria en `siga_bridge.customer_lookup`; si la columna no existe en algun entorno, el fallo se registra y se omite sin romper el webhook.

El cliente mantiene cache TTL solo para lecturas:

```text
customer: 300s
account: 60s
payments: 30s
```

Las metricas internas incluyen requests, timeouts, errores HTTP `400/401/429/500`, latencia promedio y cache hit ratio.
