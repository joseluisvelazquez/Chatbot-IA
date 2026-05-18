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

Para el flujo de comprobantes, las respuestas `verification` o `account` deben exponer el dato de `cuentas`.`ALMARE-1` como campo adicional normalizado `codigo_cliente`. El backend conserva compatibilidad con respuestas que ya usen `customer_code`, `cod_cli` o el nombre original `ALMARE-1`, pero no consulta directamente la base de datos de SIGA para obtenerlo.

## Integracion progresiva

Con `SIGA_BRIDGE_ENABLED=true`, el drawer de verificaciones abre primero con datos locales y luego refresca el detalle con lecturas `customer`, `account` y `payments`. Si Bridge falla, el panel conserva los datos locales.

Solo `admin` y `jefe_operativo` ven datos operativos del Bridge en el drawer. El refresh manual usa:

```text
GET /api/panel/verifications/{session_id}?refresh_siga=true
```

Ese refresh evita la cache en memoria y vuelve a poblarla si SIGA responde bien.

## Cobranza

El modulo de cobranza usa:

```text
GET /api/panel/collections
GET /api/panel/collections/managers
GET /api/panel/collections/{no_cuenta}
GET /api/panel/collections/{no_cuenta}/payments
POST /api/panel/collections/{no_cuenta}/refresh
```

FastAPI consume `action=collections` del Bridge para listar cuentas normalizadas desde `cuentas`. La lista esta paginada por bloques: `limit` default `25`, maximo `50`, y `offset` como cursor numerico. El Bridge consulta `limit + 1` para calcular `has_more` sin hacer `COUNT(*)` sobre busquedas pesadas. La respuesta publica usa `items`, `next_cursor`, `has_more` y `meta`; tambien conserva `data`, `total`, `limit` y `offset` por compatibilidad.

Filtros soportados por `GET /api/panel/collections`:

```text
limit=<int default 25 max 50>
offset=<int>
include_paid=<bool default false>
status=sano|critico|otro|pagado|all
gestor=<agente_verificador>  # solo admin/jefe_operativo/sistemas
no_cuenta|cuenta=<str>
folio=<str>
phone|telefono=<digits>
name|nombre=<str>
date_from=YYYY-MM-DD
date_to=YYYY-MM-DD
overdue_only=<bool>
active_only=<bool default true>
```

Los filtros se aplican dentro del Bridge con SQL parametrizado. `no_cuenta|cuenta` usa igualdad exacta sobre `cuentas.cuenta`. `folio`, `phone|telefono` y `name|nombre` obtienen cuentas candidatas con subconsultas no correlacionadas contra `bitacora_ventas` y/o `clientes`, y luego filtran `cuentas`; asi se evita escanear esas tablas una vez por cada cuenta. El backend no descarga toda la coleccion para filtrar en memoria.

Por defecto cobranza consulta solo cuentas activas/no liquidadas. Las cuentas pagadas se excluyen si `include_paid=false`; se incluyen solo con `include_paid=true`, `status=pagado` o `status=all`. Para rol `cobranza`, FastAPI ignora cualquier `gestor` enviado por query string y fuerza el filtro al `nombre_resumido` del usuario. Si no existe mapeo confiable usuario->gestor, devuelve una respuesta vacia con warning `gestor_scope_missing`.

Clasificacion:

```text
pagado  = saldo <= 0 OR estatus/proceso contiene pagado/liquidado
critico = cuenta no pagada con estatus/proceso juridico/critico/mora
          OR vencido > 0 OR moratorio > 0 OR cuentas.atrasos >= 30
sano    = cuenta activa no pagada, sin vencido/moratorio/atrasos relevantes
otro    = datos insuficientes o estado no mapeado
```

`pagado` siempre gana prioridad. Actualmente los dias de atraso se mapean desde `cuentas.atrasos`; si SIGA expone un campo mas preciso, el cambio debe hacerse en el punto unico de mapeo del Bridge/servicio de cobranza.

El detalle y refresh usan `action=account` y `action=payments` solo al abrir una fila concreta. No se consultan `account` ni `payments` por cada fila durante la carga inicial. Si Bridge falla, FastAPI conserva un fallback local de solo lectura con las mismas tablas SIGA mapeadas en SQLAlchemy y respeta `include_paid`, `active_only`, rol `cobranza` y filtro por gestor cuando existe alcance seguro.

El catalogo de gestores usa:

```text
GET /api/panel/collections/managers
```

FastAPI llama `action=collection_managers`, que lee valores distintos de `cuentas.agente_verificador`; no hay gestores hardcodeados. Solo `admin`, `jefe_operativo` y `sistemas` pueden consultar este catalogo. Si Bridge falla, se intenta fallback local sobre el mismo campo.

El webhook dispara lookup de cliente por telefono en background despues del commit de la sesion para no agregar latencia al flujo de WhatsApp. Si existe `chat_sessions.extra_json`, guarda una cache secundaria en `siga_bridge.customer_lookup`; si la columna no existe en algun entorno, el fallo se registra y se omite sin romper el webhook.

El cliente mantiene cache TTL solo para lecturas:

```text
customer: 300s
account: 60s
payments: 30s
collections: 30s
```

Las metricas internas incluyen requests, timeouts, errores HTTP `400/401/429/500`, latencia promedio y cache hit ratio.
