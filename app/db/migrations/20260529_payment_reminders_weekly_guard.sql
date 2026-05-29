-- Protecciones para recordatorios semanales e idempotencia por sesion/cuenta.
-- El estado `processing` usa la columna status existente.

CREATE INDEX `idx_payment_reminders_session_account_due_type`
  ON `payment_reminders` (`session_id`, `cuenta`, `due_date`, `reminder_type`);
