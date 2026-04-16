# Panel Consistency Migration

Run this migration before deploying the backend changes that depend on the new
columns and indexes.

```sql
ALTER TABLE inconsistencias
    ADD COLUMN resolved_by_panel TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN resolved_by_siga TINYINT(1) NOT NULL DEFAULT 0,
    ADD INDEX idx_inconsistencias_resolution (resolved_by_panel, resolved_by_siga);

ALTER TABLE verificacion_cuenta
    ADD COLUMN version INT NOT NULL DEFAULT 0;

ALTER TABLE messages
    ADD UNIQUE KEY uq_messages_message_id (message_id),
    ADD INDEX idx_messages_session_created (session_id, created_at);
```
