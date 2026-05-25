# Payment Reminders Setup

## Que hace

Este modulo programa y envia recordatorios automaticos de pago por WhatsApp usando plantillas aprobadas de Meta. La fuente principal para cuenta, saldo, fecha de venta, fecha/dia de pago y estado de cuenta es SIGA Bridge.

## Aclaracion critica

El modulo de recordatorios no decide si un comprobante es valido. Solo consulta el estado financiero ya reflejado por SIGA Bridge o por la logica existente de cobranza/pagos del panel.

Para recordatorios solo existen dos estados operativos: `pagado` y `no_pagado`. La cuenta se considera `pagado` cuando cobranza/Bridge reflejan saldo cero, o estado pagado, liquidado o saldado. Si no existe confirmacion confiable, se considera `no_pagado` o se omite el envio por datos insuficientes.

## Flujo general

1. Obtiene candidatos de cobranza desde SIGA Bridge.
2. Consulta Bridge antes de enviar cualquier recordatorio.
3. Normaliza cuenta, folio, telefono, cliente, saldo, pago minimo y fechas.
4. Resuelve la referencia operativa de cuenta con el mismo formato usado por `INFO_COMPROBANTE_ACCESO`.
5. Reutiliza la logica de cobranza/pagos para resolver `pagado` o `no_pagado`.
6. Clasifica si corresponde enviar por vencimiento, omitir por no vencido, cancelar por pagado o saltar por datos insuficientes.
7. Aplica el candado temporal `TEST_PHONE_ONLY`.
8. Envia plantilla Meta, o registra que se omitio.
9. Programa siguiente recordatorio o cancela futuros por pago confirmado.
10. Guarda auditoria en `payment_reminders`.

## Ciclo semanal por cliente

El dia del recordatorio no es global. Cada cuenta conserva su propio ciclo semanal derivado de una fecha base confiable de Bridge.

- Si Bridge entrega `next_payment_date` o equivalente, esa fecha se usa como base y se avanza cada 7 dias.
- Si Bridge no entrega proxima fecha pero si `fecha_venta`, el primer vencimiento se calcula como `fecha_venta + 7 dias` y desde ahi se avanza cada 7 dias. Esto conserva el weekday propio del cliente.
- Si Bridge no entrega fecha base confiable, el sistema omite el envio. Solo se puede usar `PAYMENT_REMINDER_DEFAULT_WEEKDAY` si se configuro explicitamente como fallback operativo.

Ejemplos:

- Cliente A: fecha base martes -> recordatorios martes cada 7 dias.
- Cliente B: fecha base viernes -> recordatorios viernes cada 7 dias.

## Formato operativo de cuenta

La cuenta enviada en recordatorios debe usar el mismo formato operativo que el flujo `INFO_COMPROBANTE_ACCESO`. Algunas cuentas pueden requerir prefijo, por ejemplo `A` o `B`, antes del numero. Si Bridge entrega una cuenta ya prefijada, se conserva ese valor. Si solo existe el numero crudo, se aplica el mismo fallback historico del flujo de comprobantes. Si una fuente marca explicitamente que el prefijo es obligatorio y no se puede resolver, el sistema debe omitir el envio para evitar referencias incorrectas.

## Variables de entorno

- `PAYMENT_REMINDERS_ENABLED`: activa o desactiva el scheduler automatico. En produccion solo debe activarse despues de probar con dry-run.
- `PAYMENT_REMINDERS_DRY_RUN`: si esta en `true`, simula sincronizacion y clasificacion sin enviar plantillas Meta reales ni escribir cambios operativos.
- `PAYMENT_REMINDER_COMPANY_ID`: empresa usada para filtrar candidatos de cobranza. Por defecto `1`.
- `PAYMENT_REMINDER_SYNC_LIMIT`: maximo de cuentas procesadas por corrida para evitar cargas grandes contra Bridge o base local.
- `PAYMENT_REMINDER_SEND_HOUR`: hora local en la que se programan o envian recordatorios vencidos. No define el dia del cliente, solo la hora.
- `PAYMENT_REMINDER_SCHEDULER_INTERVAL_MINUTES`: frecuencia con la que corre el job del scheduler.
- `PAYMENT_REMINDER_DEFAULT_WEEKDAY`: fallback opcional, NO regla principal. Solo se usa si se decide explicitamente permitir programacion cuando Bridge no entregue fecha base confiable. En operacion normal, el dia se calcula desde la fecha de pago del cliente y se repite cada 7 dias.
- `TEST_PHONE_ONLY`: candado temporal para pruebas. Solo permite enviar a telefonos definidos. Debe ser facil de remover quitando el bloque marcado como `TEMPORARY TEST_PHONE_ONLY GATE`.
- `META_PAYMENT_PENDING_TEMPLATE_NAME`: nombre de plantilla Meta aprobada para pago pendiente o proximo a vencer.
- `META_PAYMENT_OVERDUE_TEMPLATE_NAME`: nombre de plantilla Meta aprobada para pago vencido.
- `META_NEXT_PAYMENT_TEMPLATE_NAME`: plantilla para avisar proximo pago cuando aplique.
- `META_TEMPLATE_LANGUAGE`: codigo de idioma de la plantilla, por ejemplo `es_MX`.
- `SIGA_BRIDGE_BASE_URL`: URL base del Bridge.
- `SIGA_BRIDGE_TOKEN`: token usado para autenticar llamadas contra Bridge. No debe loguearse.
- `SIGA_BRIDGE_ENABLED`: activa o desactiva integracion con Bridge.

## Base de datos

Ejecutar la migracion manual:

```sql
app/db/migrations/20260525_payment_reminders.sql
```

Tabla nueva: `payment_reminders`.

Campos principales: telefono, folio, cuenta, fecha de vencimiento, proxima fecha, fecha programada, tipo de recordatorio, plantilla, estado, snapshots de saldo/monto minimo, hash de Bridge, id de Meta, errores sanitizados y timestamps de auditoria.

## Estados de recordatorio

- `scheduled`: programado.
- `sent`: enviado.
- `skipped`: omitido de forma controlada.
- `cancelled`: cancelado operativo.
- `cancelled_settled`: cancelado por liquidacion confirmada por Bridge.
- `failed`: fallo Bridge, Meta o configuracion.

## Como quitar TEST_PHONE_ONLY

El candado esta concentrado en `app/services/payment_reminder_service.py`, funcion `is_test_phone_allowed`, marcada como:

```python
# TEMPORARY TEST_PHONE_ONLY GATE
```

Para produccion, retirar ese bloque y ajustar la llamada previa al envio real.

## Dry-run

Endpoint protegido:

```http
POST /api/panel/payment-reminders/dry-run?cuenta={{CUENTA}}&folio={{FOLIO}}
```

Devuelve cuenta, `cuenta_raw`, `cuenta_formateada`, `prefijo_cuenta`, `fuente_formato_cuenta`, `cuenta_formateada_valida`, telefono enmascarado, saldo, `fecha_base`, `due_date`, `next_due_date`, `scheduled_at`, `estado_pago`, `fuente_estado_pago`, `should_send`, si pasa `TEST_PHONE_ONLY`, plantilla que se usaria y motivo si no se envia.

Para sincronizar sin escribir:

```http
POST /api/panel/payment-reminders/sync?dry_run=true&limit=25
```

Para evaluar recordatorios vencidos sin enviar:

```http
POST /api/panel/payment-reminders/run-due?dry_run=true&limit=25
```

## Envio real controlado

1. Configurar `TEST_PHONE_ONLY=5214420001679`.
2. Configurar plantillas Meta.
3. Mantener `PAYMENT_REMINDERS_DRY_RUN=false`.
4. Activar `PAYMENT_REMINDERS_ENABLED=true`.
5. Ejecutar `sync` y luego `run-due` con `dry_run=false`, o esperar el scheduler.

Si el telefono no esta en `TEST_PHONE_ONLY`, se registra `skipped_test_phone_only` y no se envia nada.

## Logs a revisar

- `payment_reminder_bridge_lookup`
- `payment_reminder_bridge_error`
- `payment_reminder_missing_bridge_fields`
- `payment_reminder_skipped_test_phone_only`
- `payment_reminders_job_finished`
- `whatsapp_send_request`
- `whatsapp_send_failed`

Los logs enmascaran telefono, folio y cuenta. No se loguean tokens ni payloads completos.

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
- Quitar el candado `TEST_PHONE_ONLY` solo con aprobacion operativa.
- Ejecutar primero varios ciclos en `PAYMENT_REMINDERS_DRY_RUN=true`.
