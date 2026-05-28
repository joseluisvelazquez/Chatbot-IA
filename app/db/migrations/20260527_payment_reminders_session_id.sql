-- Asociacion opcional entre payment_reminders y chat_sessions.
-- Nullable para no romper auditoria existente.

ALTER TABLE `payment_reminders`
  ADD COLUMN `session_id` INT NULL AFTER `id`;

CREATE INDEX `idx_payment_reminders_session_id`
  ON `payment_reminders` (`session_id`);
