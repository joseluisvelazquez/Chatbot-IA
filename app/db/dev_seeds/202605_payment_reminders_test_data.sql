-- SOLO DESARROLLO / PRUEBAS CONTROLADAS PAYMENT REMINDERS - CHATBOT DB
-- NO ES MIGRACION. NO SE EJECUTA AUTOMATICAMENTE.
-- Ejecutar en la base del chatbot, donde existen chat_sessions, messages y payment_reminders.
-- Requiere que app/db/migrations/20260525_payment_reminders.sql y
-- app/db/migrations/20260527_payment_reminders_session_id.sql ya esten aplicadas.
-- TEST_PHONE_ONLY esperado:
-- 5214271227177,5214271665615,5214271644542

START TRANSACTION;

-- Limpieza segura previa solo de datos fake de esta prueba.
DELETE FROM messages
WHERE session_id IN (
  SELECT id
  FROM chat_sessions
  WHERE folio IN ('990001', '990002', '990003')
    AND phone IN ('5214271227177', '5214271665615', '5214271644542')
);

DELETE FROM reminders
WHERE session_id IN (
  SELECT id
  FROM chat_sessions
  WHERE folio IN ('990001', '990002', '990003')
    AND phone IN ('5214271227177', '5214271665615', '5214271644542')
);

DELETE FROM flow_events
WHERE session_id IN (
  SELECT id
  FROM chat_sessions
  WHERE folio IN ('990001', '990002', '990003')
    AND phone IN ('5214271227177', '5214271665615', '5214271644542')
);

DELETE FROM payment_reminders
WHERE cuenta IN ('A900001', 'B900002', 'A900003')
   OR folio IN ('990001', '990002', '990003');

DELETE FROM chat_sessions
WHERE folio IN ('990001', '990002', '990003')
  AND phone IN ('5214271227177', '5214271665615', '5214271644542');

-- Sesiones locales fake. Son necesarias porque payment reminders ya no envia sin chat_session.
INSERT INTO chat_sessions (
  phone,
  state,
  folio,
  previous_state,
  last_message,
  last_message_at,
  last_customer_message_at,
  extra_json,
  created_at,
  updated_at,
  last_message_id,
  ai_intent_attempts,
  ai_response_attempts,
  ai_inconsistency_attempts,
  invalid_folio_attempts,
  unread_count
) VALUES
(
  '5214271227177',
  'INICIO',
  '990001',
  NULL,
  'Sesion fake para prueba de recordatorio A900001',
  NOW(),
  NOW(),
  JSON_OBJECT(
    'siga_bridge', JSON_OBJECT(
      'verification_cache', JSON_OBJECT(
        'snapshot', JSON_OBJECT(
          'folio', '990001',
          'no_cuenta', 'A900001',
          'customer', JSON_OBJECT('name', 'Cliente Prueba Uno')
        )
      )
    )
  ),
  NOW(),
  NOW(),
  NULL,
  0,
  0,
  0,
  0,
  0
),
(
  '5214271665615',
  'INICIO',
  '990002',
  NULL,
  'Sesion fake para prueba de recordatorio B900002',
  NOW(),
  NOW(),
  JSON_OBJECT(
    'siga_bridge', JSON_OBJECT(
      'verification_cache', JSON_OBJECT(
        'snapshot', JSON_OBJECT(
          'folio', '990002',
          'no_cuenta', 'B900002',
          'customer', JSON_OBJECT('name', 'Cliente Prueba Dos')
        )
      )
    )
  ),
  NOW(),
  NOW(),
  NULL,
  0,
  0,
  0,
  0,
  0
),
(
  '5214271644542',
  'INICIO',
  '990003',
  NULL,
  'Sesion fake para prueba de recordatorio A900003',
  NOW(),
  NOW(),
  JSON_OBJECT(
    'siga_bridge', JSON_OBJECT(
      'verification_cache', JSON_OBJECT(
        'snapshot', JSON_OBJECT(
          'folio', '990003',
          'no_cuenta', 'A900003',
          'customer', JSON_OBJECT('name', 'Cliente Prueba Tres')
        )
      )
    )
  ),
  NOW(),
  NOW(),
  NULL,
  0,
  0,
  0,
  0,
  0
);

SELECT id INTO @session_900001
FROM chat_sessions
WHERE phone = '5214271227177'
  AND folio = '990001'
ORDER BY id DESC
LIMIT 1;

SELECT id INTO @session_900002
FROM chat_sessions
WHERE phone = '5214271665615'
  AND folio = '990002'
ORDER BY id DESC
LIMIT 1;

SELECT id INTO @session_900003
FROM chat_sessions
WHERE phone = '5214271644542'
  AND folio = '990003'
ORDER BY id DESC
LIMIT 1;

-- Los tres quedan vencidos para seleccion por run-due.
-- Bridge recalculara due_date desde SIGA: fecha_venta = CURDATE() - INTERVAL 7 DAY -> due_date = CURDATE().
INSERT INTO payment_reminders (
  session_id,
  phone,
  folio,
  cuenta,
  due_date,
  next_due_date,
  scheduled_for,
  reminder_type,
  template_name,
  status,
  receipt_status,
  receipt_id,
  saldo_snapshot,
  monto_minimo_snapshot,
  bridge_found,
  bridge_snapshot_hash,
  meta_message_id,
  error_code,
  error_message_sanitized,
  dry_run,
  sent_at,
  paused_at,
  reactivated_at,
  cancelled_at,
  created_at,
  updated_at
) VALUES
(
  @session_900001,
  '5214271227177',
  '990001',
  'A900001',
  CURDATE(),
  CURDATE() + INTERVAL 7 DAY,
  NOW() - INTERVAL 10 MINUTE,
  'payment_pending',
  'mxcomp_pago_pendiente_v1',
  'scheduled',
  'none',
  NULL,
  3000.00,
  500.00,
  0,
  'fake_bridge_hash_900001',
  NULL,
  NULL,
  NULL,
  0,
  NULL,
  NULL,
  NULL,
  NULL,
  NOW(),
  NOW()
),
(
  @session_900002,
  '5214271665615',
  '990002',
  'B900002',
  CURDATE(),
  CURDATE() + INTERVAL 7 DAY,
  NOW() - INTERVAL 10 MINUTE,
  'payment_pending',
  'mxcomp_pago_pendiente_v1',
  'scheduled',
  'none',
  NULL,
  2500.00,
  500.00,
  0,
  'fake_bridge_hash_900002',
  NULL,
  NULL,
  NULL,
  0,
  NULL,
  NULL,
  NULL,
  NULL,
  NOW(),
  NOW()
),
(
  @session_900003,
  '5214271644542',
  '990003',
  'A900003',
  CURDATE(),
  CURDATE() + INTERVAL 7 DAY,
  NOW() - INTERVAL 10 MINUTE,
  'payment_pending',
  'mxcomp_pago_pendiente_v1',
  'scheduled',
  'none',
  NULL,
  1500.00,
  500.00,
  0,
  'fake_bridge_hash_900003',
  NULL,
  NULL,
  NULL,
  0,
  NULL,
  NULL,
  NULL,
  NULL,
  NOW(),
  NOW()
);

-- Verificacion: los 3 deben tener session_id y estar due.
SELECT
  pr.id,
  pr.session_id,
  cs.phone AS session_phone,
  pr.phone,
  pr.folio,
  pr.cuenta,
  pr.status,
  pr.reminder_type,
  pr.due_date,
  pr.scheduled_for,
  (pr.scheduled_for <= NOW()) AS is_due
FROM payment_reminders pr
LEFT JOIN chat_sessions cs ON cs.id = pr.session_id
WHERE pr.cuenta IN ('A900001', 'B900002', 'A900003')
ORDER BY pr.cuenta;

SELECT cuenta, due_date, reminder_type, COUNT(*) AS total
FROM payment_reminders
WHERE cuenta IN ('A900001', 'B900002', 'A900003')
GROUP BY cuenta, due_date, reminder_type
HAVING COUNT(*) > 1;

COMMIT;
