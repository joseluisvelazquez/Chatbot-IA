-- SOLO DATOS FAKE DE PRUEBA PAYMENT REMINDERS - CHATBOT DB
-- NO USAR PARA CLIENTES REALES
-- REVISAR SELECT ANTES DE EJECUTAR DELETE
-- NO USAR TRUNCATE
-- NO USAR DELETE SIN WHERE

START TRANSACTION;

-- Revisar exactamente que se va a borrar.
SELECT *
FROM payment_reminders
WHERE cuenta IN ('A900001', 'B900002', 'A900003')
   OR folio IN ('990001', '990002', '990003');

SELECT *
FROM chat_sessions
WHERE folio IN ('990001', '990002', '990003')
  AND phone IN ('5214271227177', '5214271665615', '5214271644542');

SELECT *
FROM messages
WHERE session_id IN (
  SELECT id
  FROM chat_sessions
  WHERE folio IN ('990001', '990002', '990003')
    AND phone IN ('5214271227177', '5214271665615', '5214271644542')
);

SELECT *
FROM reminders
WHERE session_id IN (
  SELECT id
  FROM chat_sessions
  WHERE folio IN ('990001', '990002', '990003')
    AND phone IN ('5214271227177', '5214271665615', '5214271644542')
);

SELECT *
FROM flow_events
WHERE session_id IN (
  SELECT id
  FROM chat_sessions
  WHERE folio IN ('990001', '990002', '990003')
    AND phone IN ('5214271227177', '5214271665615', '5214271644542')
);

-- Borrado seguro: mensajes/eventos fake -> reminders fake -> sesiones fake.
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

-- Debe regresar 0 despues del cleanup.
SELECT COUNT(*) AS fake_payment_reminders_remaining
FROM payment_reminders
WHERE cuenta IN ('A900001', 'B900002', 'A900003')
   OR folio IN ('990001', '990002', '990003');

SELECT COUNT(*) AS fake_chat_sessions_remaining
FROM chat_sessions
WHERE folio IN ('990001', '990002', '990003')
  AND phone IN ('5214271227177', '5214271665615', '5214271644542');

COMMIT;
