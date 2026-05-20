# Modulo de Cobranza

## 1. Proposito

El modulo de cobranza apoya la consulta y seguimiento de cuentas, pagos y clientes relacionados con cobranza desde el panel administrativo. No sustituye la validacion financiera manual, no ejecuta cobranza automatica completa y no modifica directamente SIGA; consume informacion local y, cuando esta habilitado, consulta SIGA Bridge.

## 2. Alcance actual

Implementado:
- Vista de panel en `panel/pages/cobranza.html` y logica en `panel/js/collections.js`.
- Consulta paginada de cuentas por cuenta, folio, telefono, nombre, estado, fechas, morosidad, pagadas y gestor.
- Consulta de detalle de cuenta y pagos normalizados.
- Fallback local cuando SIGA Bridge esta deshabilitado o falla.
- Filtro de gestores para roles autorizados.
- Permisos para roles `admin`, `cobranza`, `jefe_operativo` y `sistemas`.

Parcial:
- Enriquecimiento con SIGA Bridge para cuentas, detalle, pagos y gestores.
- Actualizacion manual puntual con `POST /api/panel/collections/{no_cuenta}/refresh`.
- Relacion indirecta con folio, telefono y cuenta; no hay vinculacion explicita cuenta/folio/session_id para abrir conversaciones desde cobranza.

Pendiente:
- Evento WebSocket especifico para cobranza.
- Boton "Ir a conversacion" desde una cuenta con `chat_sessions` asociado.
- Cache corto explicito por cuenta para respuestas de bridge.
- Endpoint optimizado de busqueda unica si se requiere una sola persona/cuenta con menor carga.

## 3. Flujo funcional esperado

1. El usuario entra al modulo de cobranza.
2. El panel solicita informacion al backend con filtros y paginacion.
3. El backend consulta SIGA Bridge si esta habilitado; si falla o no aplica, usa datos locales.
4. El backend normaliza cuentas, resumen financiero, cliente y pagos.
5. El panel renderiza cuentas, pagos y datos del cliente.
6. Si en el futuro existe chat asociado, debe mostrarse acceso a la conversacion.
7. Si hay actualizacion en tiempo real, debe emitirse un evento WebSocket minimo o refrescarse solo la seccion afectada.

## 4. Fuentes de datos

- Base local: tablas como `cuentas`, `bitacora_ventas` y `estados_cuenta`.
- SIGA Bridge: cliente en `app/services/siga_bridge.py`.
- Normalizacion de cobranza: `app/services/collections_panel_service.py`.
- `chat_sessions`: fuente disponible para conversaciones, pero actualmente no esta enlazada desde cobranza.
- Gestores: `cuentas.agente_verificador` o catalogo devuelto por SIGA Bridge; no debe hardcodearse.

## 5. Endpoints relacionados

- `GET /api/panel/collections`
  - Proposito: listar cuentas de cobranza con filtros y paginacion.
  - Parametros: `no_cuenta`, `cuenta`, `folio`, `phone`, `telefono`, `name`, `nombre`, `cliente`, `status`, `classification`, `gestor`, `date_from`, `date_to`, `overdue_only`, `paid_only`, `include_paid`, `active_only`, `limit`, `offset`.
  - Respuesta: items normalizados, total, paginacion y metadatos de origen/bridge.
  - Notas: valida rol, empresa y filtros; limita `limit` a 50 en servicio.

- `GET /api/panel/collections/managers`
  - Proposito: listar gestores disponibles.
  - Parametros: `search`, `limit`.
  - Respuesta: gestores normalizados con conteo y metadatos.
  - Notas: solo roles `admin`, `jefe_operativo` y `sistemas`.

- `GET /api/panel/collections/{no_cuenta}`
  - Proposito: obtener detalle de una cuenta.
  - Parametros: `include_paid`.
  - Respuesta: cuenta, cliente, resumen financiero, pagos si aplican y metadatos SIGA Bridge.
  - Notas: usa fallback local si el bridge falla.

- `GET /api/panel/collections/{no_cuenta}/payments`
  - Proposito: obtener historial de pagos normalizado.
  - Parametros: `include_paid`.
  - Respuesta: `{ data, total }`.
  - Notas: consulta bridge si esta habilitado y recurre a `estados_cuenta`.

- `POST /api/panel/collections/{no_cuenta}/refresh`
  - Proposito: forzar refresco de detalle desde SIGA Bridge cuando aplica.
  - Parametros: `include_paid`.
  - Respuesta: detalle normalizado de cuenta.
  - Notas: no escribe en SIGA.

## 6. WebSocket y tiempo real

Actualmente no se identifico un evento especifico de cobranza. Eventos existentes que pueden afectar contexto operativo del panel: `conversation_updated`, `dashboard_update`, `dashboard_updated`, `siga_snapshot_updated`.

Pendiente propuesto:

```json
{
  "type": "collections_updated",
  "cuenta": "...",
  "folio": "...",
  "session_id": null,
  "reason": "payment|siga_refresh|conversation_link|status_change",
  "force_refetch": true
}
```

## 7. Validaciones necesarias

- No confiar en parametros del frontend.
- Validar rol y `empresa_id`.
- Validar cuenta, folio o telefono antes de consultar.
- Sanitizar datos sensibles en logs.
- No exponer tokens de SIGA Bridge.
- Evitar consultas masivas si se busca una sola cuenta/persona.
- Manejar timeouts y respuestas incompletas del bridge.
- Respetar el alcance por gestor para usuarios de cobranza.

## 8. Riesgos actuales

- Latencia si se consulta demasiada informacion al bridge.
- Datos incompletos o desactualizados desde SIGA.
- Desfase entre cache/fallback local y bridge.
- Relacion ambigua entre telefono, folio y cuenta.
- Estado asociado a sesion incorrecta si se usa solo telefono.
- Falta de eventos WebSocket especificos para cobranza.
- Riesgo de mostrar informacion sensible si se relajan roles o alcance por empresa.

## 9. Mejoras recomendadas

- Busqueda server-side por cuenta, folio, telefono o nombre con indices revisados.
- Endpoint especifico y liviano para detalle de una cuenta.
- Cache corto para respuestas de bridge.
- Normalizador unico para pagos/cuenta como contrato interno estable.
- Relacion explicita cuenta/folio/session_id.
- Evento WebSocket minimo para cambios relevantes.
- Boton "Ir a conversacion" si existe `chat_sessions` relacionado.
- Obtener gestores activos dinamicamente.
- Mantener paginacion y filtros en backend.

## 10. Pruebas sugeridas

- Buscar cuenta existente.
- Buscar cuenta inexistente.
- Buscar por folio.
- Buscar por telefono.
- Abrir detalle de cuenta.
- Ver pagos normalizados.
- Validar comportamiento si SIGA Bridge falla.
- Validar que usuario sin rol no acceda.
- Validar boton de conversacion cuando se implemente relacion con chat.
- Validar que no se dupliquen registros.
- Validar actualizacion por WebSocket cuando exista evento de cobranza.
