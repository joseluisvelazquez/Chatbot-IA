# Payment Reminders

La documentacion operativa canonica esta en:

```text
docs/payment_reminders_setup.md
```

Resumen del contrato actual:

- Produccion toma candidatos desde `chat_sessions` locales o desde una cuenta/folio puntual solicitado por endpoint de operacion.
- Antes de programar o enviar, siempre consulta SIGA Bridge y normaliza cuenta, folio, telefono, cliente, saldo, pago minimo y fechas.
- El estado operativo solo es `pagado` o `no_pagado`.
- Si Bridge confirma cuenta pagada, liquidada, saldada o saldo `<= 0`, cancela futuros y no envia.
- Si hay saldo pendiente, telefono valido y `chat_session` confiable, programa o envia plantilla Meta aprobada.
- No crea `chat_sessions` artificiales.
- No modifica SIGA ni saldos financieros.
- No envia mensajes libres automaticos; solo usa plantillas Meta.
- Toda omision o fallo debe quedar con razon explicita en logs y, con `dry_run=false`, como auditoria en `payment_reminders`.
- `PAYMENT_REMINDERS_TEST_MODE=true` limita programacion/envio a `TEST_PHONE_ONLY`.
- `PAYMENT_REMINDERS_TEST_MODE=false` desactiva ese candado para operar con telefonos reales de SIGA Bridge.
- La frecuencia real es semanal: despues de un `sent_at` o un mensaje visible `messages.type='payment_reminder'`, la misma cuenta/sesion queda bloqueada hasta 7 dias despues.
- El siguiente recordatorio posterior a un envio real usa `sent_at + 7 dias`: `due_date` queda en esa fecha y `scheduled_for` en ese timestamp.
- Los registros terminales (`failed`, `skipped`, `cancelled`, `cancelled_settled`) no se reactivan solos en cada `sync`.
- `run-due` pasa los registros por estado `processing` para evitar doble envio entre scheduler, endpoints manuales o multiples workers.
- Cada envio real aceptado por Meta crea un registro `messages.type='payment_reminder'`; si falla ese insert, el recordatorio queda `sent` con `error_code=message_insert_failed`.

Endpoints utiles:

```http
POST /api/panel/payment-reminders/dry-run?cuenta={{CUENTA}}&folio={{FOLIO}}
POST /api/panel/payment-reminders/sync?dry_run=true&limit=25
POST /api/panel/payment-reminders/sync?dry_run=false&limit=25
POST /api/panel/payment-reminders/sync?dry_run=true&cuenta={{CUENTA}}&company_id=1
POST /api/panel/payment-reminders/run-due?dry_run=true&limit=25
POST /api/panel/payment-reminders/run-due?dry_run=false&limit=25
```

Antes de produccion, revisar plantillas Meta aprobadas, permisos, scheduler cargando `app.main:app`, zona horaria, logs, rollback/errores y las variables `PAYMENT_REMINDERS_*`, `META_*` y `SIGA_BRIDGE_*`.
