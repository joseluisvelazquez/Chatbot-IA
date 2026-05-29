# Payment Reminders Setup

## Que hace

Este modulo programa y envia recordatorios automaticos de pago por WhatsApp usando plantillas aprobadas de Meta. La fuente principal para cuenta, saldo, fecha de venta, fecha/dia de pago y estado de cuenta es SIGA Bridge.

## Aclaracion critica

El modulo de recordatorios no decide si un comprobante es valido. Solo consulta el estado financiero ya reflejado por SIGA Bridge o por la logica existente de cobranza/pagos del panel.

Para recordatorios solo existen dos estados operativos: `pagado` y `no_pagado`. La cuenta se considera `pagado` cuando cobranza/Bridge reflejan saldo cero, o estado pagado, liquidado o saldado. Si no existe confirmacion confiable, se considera `no_pagado` o se omite el envio por datos insuficientes.

`TEST_PHONE_ONLY` no forma parte del flujo productivo permanente de `payment_reminders`. Solo aplica cuando `PAYMENT_REMINDERS_TEST_MODE=true`. Con `PAYMENT_REMINDERS_TEST_MODE=false`, los telefonos reales provenientes de SIGA Bridge son validos y no quedan bloqueados por listas de prueba.

## Flujo general

1. Obtiene candidatos desde `chat_sessions` locales con folio o cuenta asociada.
2. Consulta Bridge antes de programar o enviar cualquier recordatorio.
3. Normaliza cuenta, folio, telefono, cliente, saldo, pago minimo y fechas.
4. Resuelve la referencia operativa de cuenta con el mismo formato usado por `INFO_COMPROBANTE_ACCESO`.
5. Reutiliza la logica de cobranza/pagos para resolver `pagado` o `no_pagado`.
6. Valida que exista una `chat_session` local confiable para ese telefono y, cuando existan, que folio/cuenta coincidan.
7. Clasifica si corresponde enviar por vencimiento, omitir por no vencido, cancelar por pagado o saltar por datos insuficientes.
8. Envia plantilla Meta, o registra que se omitio.
9. Guarda el envio exitoso como mensaje visible en conversaciones.
10. Programa siguiente recordatorio o cancela futuros por pago confirmado.
11. Guarda auditoria en `payment_reminders`.

El endpoint `sync` tambien puede evaluar una cuenta puntual con `cuenta` o `folio`. Esa ruta no descarga toda cobranza: consulta Bridge para esa cuenta, resuelve la `chat_session` local confiable y crea el recordatorio o una fila de auditoria con `skip_reason`.

## Ciclo semanal por cliente

El dia del recordatorio no es global. Cada cuenta conserva su propio ciclo semanal derivado de una fecha base confiable de Bridge.

- Si Bridge entrega `next_payment_date` o equivalente, esa fecha se usa como base y se avanza cada 7 dias.
- Si Bridge no entrega proxima fecha pero si `fecha_venta`, el primer vencimiento se calcula como `fecha_venta + 7 dias` y desde ahi se avanza cada 7 dias. Esto conserva el weekday propio del cliente.
- Si Bridge no entrega fecha base confiable, el sistema omite el envio. Solo se puede usar `PAYMENT_REMINDER_DEFAULT_WEEKDAY` si se configuro explicitamente como fallback operativo.

Ejemplos:

- Cliente A: fecha base martes -> recordatorios martes cada 7 dias.
- Cliente B: fecha base viernes -> recordatorios viernes cada 7 dias.

Ademas del ciclo de vencimiento, existe una guarda fuerte de frecuencia: una misma cuenta/sesion no debe recibir otro recordatorio hasta que hayan pasado 7 dias completos desde `sent_at` del ultimo envio. `PAYMENT_REMINDER_SCHEDULER_INTERVAL_MINUTES` solo define cada cuanto se revisa; no define cada cuanto se envia.

Despues de un envio aceptado por Meta, el registro queda como `sent` con `sent_at`, y se programa el siguiente recordatorio para la siguiente semana. Si el envio ocurrio tarde, `scheduled_for` del siguiente recordatorio se ajusta para no quedar antes de `sent_at + 7 dias`.

## Formato operativo de cuenta

La cuenta enviada en recordatorios debe usar el mismo formato operativo que el flujo `INFO_COMPROBANTE_ACCESO`. Algunas cuentas pueden requerir prefijo, por ejemplo `A` o `B`, antes del numero. Si Bridge entrega una cuenta ya prefijada, se conserva ese valor. Si solo existe el numero crudo, se aplica el mismo fallback historico del flujo de comprobantes. Si una fuente marca explicitamente que el prefijo es obligatorio y no se puede resolver, el sistema debe omitir el envio para evitar referencias incorrectas.

## Variables de entorno

- `PAYMENT_REMINDERS_ENABLED`: activa o desactiva el scheduler automatico. En produccion solo debe activarse despues de probar con dry-run.
- `PAYMENT_REMINDERS_DRY_RUN`: si esta en `true`, simula sincronizacion y clasificacion sin enviar plantillas Meta reales ni escribir cambios operativos.
- `PAYMENT_REMINDERS_TEST_MODE`: si esta en `true`, solo permite programar/enviar a telefonos incluidos en `TEST_PHONE_ONLY`.
- `TEST_PHONE_ONLY`: lista JSON o CSV de telefonos permitidos en modo pruebas. Ejemplo: `["5214271227177", "5214271665615", "5214271644542"]`.
- `PAYMENT_REMINDER_COMPANY_ID`: empresa usada para consultar datos frescos en Bridge. Por defecto `1`.
- `PAYMENT_REMINDER_SYNC_LIMIT`: maximo de cuentas procesadas por corrida para evitar cargas grandes contra Bridge o base local.
- `PAYMENT_REMINDER_SEND_HOUR`: hora local en la que se programan o envian recordatorios vencidos. No define el dia del cliente, solo la hora.
- `PAYMENT_REMINDER_SCHEDULER_INTERVAL_MINUTES`: frecuencia con la que corre el job del scheduler.
- `PAYMENT_REMINDER_DEFAULT_WEEKDAY`: fallback opcional, NO regla principal. Solo se usa si se decide explicitamente permitir programacion cuando Bridge no entregue fecha base confiable. En operacion normal, el dia se calcula desde la fecha de pago del cliente y se repite cada 7 dias.
- `META_PAYMENT_PENDING_TEMPLATE_NAME`: nombre de plantilla Meta aprobada para pago pendiente o proximo a vencer.
- `META_PAYMENT_OVERDUE_TEMPLATE_NAME`: nombre de plantilla Meta aprobada para pago vencido.
- `META_NEXT_PAYMENT_TEMPLATE_NAME`: plantilla para avisar proximo pago cuando aplique.
- `META_TEMPLATE_LANGUAGE`: codigo de idioma de la plantilla, por ejemplo `es_MX`.
- `SIGA_BRIDGE_BASE_URL`: URL base del Bridge.
- `SIGA_BRIDGE_TOKEN`: token usado para autenticar llamadas contra Bridge. No debe loguearse.
- `SIGA_BRIDGE_ENABLED`: activa o desactiva integracion con Bridge.

## Base de datos

Ejecutar las migraciones manuales:

```sql
app/db/migrations/20260525_payment_reminders.sql
app/db/migrations/20260527_payment_reminders_session_id.sql
app/db/migrations/20260529_payment_reminders_weekly_guard.sql
```

Tabla nueva: `payment_reminders`.

Campos principales: `session_id`, telefono, folio, cuenta, fecha de vencimiento, proxima fecha, fecha programada, tipo de recordatorio, plantilla, estado, snapshots de saldo/monto minimo, hash de Bridge, id de Meta, errores sanitizados y timestamps de auditoria.

`session_id` es nullable para compatibilidad con registros historicos, pero los envios nuevos deben resolver una `chat_session` antes de programar o enviar.

Cuando `dry_run=false`, las omisiones controladas tambien se auditan en `payment_reminders`. En esos casos `status` queda como `skipped`, `failed` o `cancelled_settled`, `error_code` guarda el `skip_reason`, y `error_message_sanitized` resume campos faltantes o error tecnico sin exponer datos sensibles. Si no existe un tipo real de plantilla para esa decision, `reminder_type` puede quedar como `payment_audit`.

## Estados de recordatorio

- `scheduled`: programado.
- `processing`: tomado por una corrida de `run-due` para evitar doble envio concurrente.
- `sent`: enviado.
- `skipped`: omitido de forma controlada.
- `cancelled`: cancelado operativo.
- `cancelled_settled`: cancelado por liquidacion confirmada por Bridge.
- `failed`: fallo Bridge, Meta o configuracion.

## Dry-run

Endpoint protegido:

```http
POST /api/panel/payment-reminders/dry-run?cuenta={{CUENTA}}&folio={{FOLIO}}
```

Devuelve cuenta, `cuenta_raw`, `cuenta_formateada`, `prefijo_cuenta`, `fuente_formato_cuenta`, `cuenta_formateada_valida`, telefono enmascarado, saldo, `fecha_base`, `due_date`, `next_due_date`, `scheduled_at`, `estado_pago`, `fuente_estado_pago`, `should_send`, plantilla que se usaria y motivo si no se envia.

Tambien devuelve datos de integracion con conversaciones y frecuencia: `session_id`, `chat_session_found`, `chat_session_match_reason`, `test_mode`, `test_phone_allowed`, `weekly_frequency_allowed`, `last_payment_reminder_at`, `next_allowed_payment_reminder_at`, `existing_scheduled_reminder_id`, `duplicate_prevented`, `would_create_conversation_message`, `conversation_message_preview`, `next_payment_reminder_at` y `sent_count_prev`.

Si no existe `chat_session`, el resultado debe quedar con `should_send=false` y reason `missing_chat_session`. Si hay varias sesiones posibles sin folio/cuenta concluyente, reason `ambiguous_chat_session`. Si la sesion existe pero folio/cuenta no coincide, reason `chat_session_account_mismatch`.

Para sincronizar sin escribir:

```http
POST /api/panel/payment-reminders/sync?dry_run=true&limit=25
```

Para diagnosticar una cuenta real sin barrer todas las sesiones:

```http
POST /api/panel/payment-reminders/sync?dry_run=true&cuenta={{CUENTA}}&company_id=1
POST /api/panel/payment-reminders/sync?dry_run=false&cuenta={{CUENTA}}&company_id=1
POST /api/panel/payment-reminders/sync?dry_run=true&folio={{FOLIO}}&company_id=1
```

El `sync` recorre `chat_sessions` locales y solo programa recordatorios para sesiones que tengan folio/cuenta resoluble y datos confiables en Bridge. `run-due` no descubre clientes nuevos: solo procesa recordatorios ya existentes en `payment_reminders`.

Para evaluar recordatorios vencidos sin enviar:

```http
POST /api/panel/payment-reminders/run-due?dry_run=true&limit=25
```

## Envio real

1. Configurar plantillas Meta.
2. Mantener `PAYMENT_REMINDERS_DRY_RUN=false` solo cuando ya se valido el flujo en dry-run.
3. Activar `PAYMENT_REMINDERS_ENABLED=true` cuando se quiera que el scheduler corra automaticamente.
4. Ejecutar `sync` y luego `run-due` con `dry_run=false`, o esperar el scheduler.

Debe existir `chat_session` local y datos confiables de Bridge. Si falta sesion local, no se envia y se reporta `missing_chat_session`, `ambiguous_chat_session` o `chat_session_account_mismatch`.

## Conversaciones y cobranza

Cuando Meta confirma un envio, el modulo crea un mensaje saliente visible en conversaciones con `type=payment_reminder`, `direction=out` y metadata con cuenta, folio, vencimiento, plantilla e id de Meta. Tambien actualiza `chat_sessions.last_message` y `chat_sessions.last_message_at`, y emite el evento WebSocket de nuevo mensaje para el panel.

Si Meta acepta el envio pero falla la insercion local en `messages`, no se reintenta el envio automaticamente. El recordatorio queda como `sent`, conserva `meta_message_id` y registra `error_code=message_insert_failed` para auditoria.

El modulo de cobranza agrega un resumen por cuenta:

- `next_payment_reminder_at`: proximo recordatorio programado.
- `payment_reminders_sent_count`: cantidad de recordatorios enviados.
- `last_payment_reminder_at`: ultimo recordatorio enviado.

En el panel de cobranza se muestra una columna compacta con el proximo recordatorio y el total enviado. Si no hay datos, se muestra como sin programar o sin enviados.

Para verificar por SQL:

```sql
SELECT id, session_id, phone, folio, cuenta, status, due_date, scheduled_for, sent_at
FROM payment_reminders
WHERE session_id = {{SESSION_ID}}
ORDER BY scheduled_for DESC;
```

Y para confirmar que el mensaje quedo visible:

```sql
SELECT id, session_id, direction, type, content, message_id, created_at
FROM messages
WHERE session_id = {{SESSION_ID}}
  AND type = 'payment_reminder'
ORDER BY created_at DESC;
```

## Logs a revisar

- `payment_reminders_scheduler_enabled`
- `payment_reminders_scheduler_disabled`
- `payment_reminders_job_started`
- `payment_reminder_candidate_sync_started`
- `payment_reminder_candidate_sync_finished`
- `payment_reminders_job_finished`
- `payment_reminders_job_failed`
- `payment_reminder.create.start`
- `payment_reminder.bridge.loaded`
- `payment_reminder.normalized`
- `payment_reminder.validation.ok`
- `payment_reminder.validation.failed`
- `payment_reminder.create.insert.start`
- `payment_reminder.create.inserted`
- `payment_reminder.create.commit.ok`
- `payment_reminder.create.failed`
- `payment_reminder.send.attempt`
- `payment_reminder.send.accepted`
- `payment_reminder.send.failed`
- `payment_reminder.test_mode.blocked`
- `payment_reminder.duplicate.prevented`
- `payment_reminder.weekly_frequency.blocked`
- `payment_reminder.message.insert.start`
- `payment_reminder.message.inserted`
- `payment_reminder.message.failed`
- `payment_reminder.next_scheduled`
- `payment_reminder.cancelled_settled`
- `payment_reminder_bridge_lookup`
- `payment_reminder_bridge_error`
- `payment_reminder_missing_bridge_fields`
- `payment_reminder_skipped_chat_session`
- `payment_reminder_conversation_message_failed`
- `collections_payment_reminder_summary_failed`
- `payment_reminders_job_finished`
- `whatsapp_send_request`
- `whatsapp_send_failed`

Los logs enmascaran telefono, folio y cuenta. No se loguean tokens ni payloads completos.

Las omisiones esperadas deben aparecer con razon explicita: `missing_chat_session`, `ambiguous_chat_session`, `chat_session_account_mismatch`, `missing_bridge_fields`, `bridge_error`, `not_due`, `paid_or_settled`, `already_sent`, `template_missing`, `meta_error`, `test_phone_not_allowed`, `weekly_frequency_blocked` o `message_insert_failed`.

## Si Bridge falla

No se envia plantilla y no se programa un recordatorio nuevo basado en datos dudosos. El recordatorio se marca como `failed` o se reporta `bridge_error` en dry-run.

## Si Meta falla

El intento queda como `failed` con `meta_error` y mensaje sanitizado. No se expone token ni payload completo.

## Seguridad

- No enviar mensajes libres automaticos fuera de la ventana de 24 horas.
- Usar solo plantillas Meta aprobadas.
- Proteger endpoints manuales con sesion de panel y roles `admin`, `jefe_operativo` o `sistemas`.
- No exponer tokens, cookies, datos bancarios completos ni payloads completos.
- No modificar SIGA ni saldos financieros.

## Antes de produccion

- Confirmar nombres y orden de variables de cada plantilla Meta.
- Confirmar que Bridge entregue saldo y fecha de venta confiables.
- Confirmar que en produccion el ciclo se derive de fecha base de Bridge; usar `PAYMENT_REMINDER_DEFAULT_WEEKDAY` solo como fallback temporal y documentado.
- Ejecutar primero varios ciclos en `PAYMENT_REMINDERS_DRY_RUN=true`.
- Confirmar que el proceso de produccion carga `app.main:app`, porque el scheduler se registra ahi.
- Confirmar `PAYMENT_REMINDERS_ENABLED=true`, `PAYMENT_REMINDERS_DRY_RUN=false`, `PAYMENT_REMINDERS_TEST_MODE`, `TEST_PHONE_ONLY`, `PAYMENT_REMINDER_COMPANY_ID`, `PAYMENT_REMINDER_SYNC_LIMIT`, `PAYMENT_REMINDER_SEND_HOUR`, `PAYMENT_REMINDER_SCHEDULER_INTERVAL_MINUTES`, `META_PAYMENT_PENDING_TEMPLATE_NAME`, `META_PAYMENT_OVERDUE_TEMPLATE_NAME`, `META_NEXT_PAYMENT_TEMPLATE_NAME`, `META_TEMPLATE_LANGUAGE`, `SIGA_BRIDGE_BASE_URL`, `SIGA_BRIDGE_TOKEN` y `SIGA_BRIDGE_ENABLED`.
- Confirmar zona horaria del servidor, API y DB.
- Confirmar que las plantillas Meta esten aprobadas y que la app tenga permisos activos.
- Confirmar que endpoints manuales esten protegidos por sesion y rol.
- Confirmar que errores de Bridge, Meta y DB quedan visibles en logs sin tokens, cookies ni headers sensibles.

## Diagnostico con datos reales

El normalizador acepta tanto respuestas Bridge envueltas como `{ok,data,error,meta}` como respuestas desempaquetadas. Para una cuenta real como `1260522`, estos campos son validos y no deben romper el flujo:

- `account.account` como `"1260522"` sin prefijo.
- `company_id` numerico.
- `customer.phones` como lista.
- `customer.name` con espacios y nombres completos.
- `account.plan.term` igual a `0`.
- `account.plan.minimum_payment` como numero.
- `account.amounts.stored_balance` mayor a `0`.
- `account.amounts.overdue` y `payment_summary.overdue` negativos.
- `account.amounts.late_fee` negativo.
- `account.sale_date` como `YYYY-MM-DD HH:MM:SS`.
- `account.status` como `Sano` y `account.process` como `Cobranza`.
- `last_payment_date` como `YYYY-MM-DD`.

Si Bridge confirma saldo `<= 0` o estado pagado/liquidado/saldado, no se envia y se cancelan futuros. Si Bridge no confirma pago y existe saldo pendiente, se evalua como `no_pagado`; un comprobante subido no se interpreta como pago.

## SQL de verificacion

Sesiones locales con folio o cuenta:

```sql
SELECT id, phone, folio, last_message_at, JSON_EXTRACT(extra_json, '$.siga_bridge') AS siga_bridge
FROM chat_sessions
WHERE folio IS NOT NULL
   OR JSON_EXTRACT(extra_json, '$.no_cuenta') IS NOT NULL
   OR JSON_EXTRACT(extra_json, '$.cuenta') IS NOT NULL
   OR JSON_EXTRACT(extra_json, '$.siga_bridge.verification_cache.snapshot.no_cuenta') IS NOT NULL
ORDER BY last_message_at DESC
LIMIT 50;
```

Recordatorios de una cuenta:

```sql
SELECT *
FROM payment_reminders
WHERE cuenta = '1260522'
ORDER BY created_at DESC;
```

Vista general de recordatorios:

```sql
SELECT id, session_id, phone, folio, cuenta, status, due_date, next_due_date, scheduled_for, sent_at, error_code
FROM payment_reminders
ORDER BY created_at DESC;
```

Estado operativo:

```sql
SELECT status, reminder_type, scheduled_for, sent_at, error_code, error_message_sanitized
FROM payment_reminders
WHERE cuenta = '1260522'
ORDER BY id DESC;
```

Estructura:

```sql
SHOW CREATE TABLE payment_reminders;
SHOW FULL COLUMNS FROM payment_reminders;
```

Skips y fallos:

```sql
SELECT status, error_code, error_message_sanitized, COUNT(*) total
FROM payment_reminders
GROUP BY status, error_code, error_message_sanitized
ORDER BY total DESC;
```

Mensajes visibles en conversaciones:

```sql
SELECT id, session_id, direction, type, content, message_id, created_at
FROM messages
WHERE type = 'payment_reminder'
ORDER BY created_at DESC;
```

Ultimas conversaciones actualizadas:

```sql
SELECT id, phone, folio, last_message, last_message_at
FROM chat_sessions
ORDER BY last_message_at DESC
LIMIT 20;
```
