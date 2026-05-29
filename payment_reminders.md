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
- `TEST_PHONE_ONLY` no forma parte del flujo productivo y no debe bloquear creacion, programacion ni envio en produccion.

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
