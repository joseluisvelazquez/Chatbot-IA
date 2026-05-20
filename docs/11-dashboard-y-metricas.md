# Dashboard Y Métricas

## Descripción General

El dashboard del panel administrativo permite monitorear el comportamiento general del sistema. Su vista se encuentra en `panel/pages/dashboard.html`, la lógica frontend en `panel/js/dashboard.js` y los endpoints backend en `app/router/panel_router.py`.

## Métricas Principales

El endpoint `GET /api/panel/dashboard/summary` entrega:

- Total de sesiones.
- Sesiones activas.
- Mensajes entrantes.
- Mensajes salientes.
- Inconsistencias abiertas.

Estos valores se calculan consultando tablas como `chat_sessions`, `messages` e `inconsistencias`.

## Funnel De Verificación

El endpoint `GET /api/panel/dashboard/funnel` calcula el avance de sesiones por pasos del flujo de verificación. Los pasos provienen de `STEP_ORDER`, definido en `app/core/verification_steps.py`.

El funnel se basa en:

- Eventos registrados en `flow_events`.
- Estado actual de sesiones con folio.
- Mapeo de estados a pasos de verificación.

El panel renderiza la gráfica mediante Chart.js.

## Tiempo Entre Estados

El endpoint `GET /api/panel/dashboard/state-times` calcula tiempos promedio, máximos y mínimos entre transiciones de estados conversacionales. Para ello consulta `flow_events`, ordena eventos por sesión y calcula diferencias de tiempo entre transiciones.

Esta métrica ayuda a identificar etapas donde el proceso puede tardar más.

## Métricas De SIGA Bridge

El dashboard también puede mostrar métricas de SIGA Bridge para roles autorizados. Esta información se obtiene mediante:

- `GET /api/panel/siga-bridge/metrics`

Las métricas del Bridge incluyen:

- Número de requests.
- Cache hits.
- Cache misses.
- Ratio de cache.
- Timeouts.
- Errores 400, 401, 429 y 500.
- Latencia promedio.

La disponibilidad visual de estas métricas está condicionada en `panel/js/dashboard.js` a roles como `admin` y `jefe_operativo`.

## Actualización En Tiempo Real

El dashboard puede actualizarse con eventos WebSocket de tipo `dashboard_update`. Estos eventos son emitidos desde el webhook y desde acciones del panel, y procesados en `panel/js/websocket.js` y `panel/js/store.js`.

## Pendientes De Validar

- No se encontraron objetivos numéricos de desempeño o metas de negocio en el repositorio.
- La interpretación final de cada métrica debe validarse con usuarios operativos.
