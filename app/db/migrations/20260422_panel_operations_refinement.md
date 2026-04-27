# Panel Operations Refinement Migration

Apply this after the initial panel operations migration if that migration was
already executed with `bot_active` / `ia_active`. New installs can use the
updated `20260422_panel_operations.md` directly.

```sql
ALTER TABLE chat_sessions
    ADD COLUMN transferred_by_user_id VARCHAR(120) NULL,
    ADD COLUMN previous_owner_user_id VARCHAR(120) NULL,
    ADD COLUMN previous_owner_role VARCHAR(30) NULL,
    ADD COLUMN transfer_reason TEXT NULL,
    ADD COLUMN transfer_created_at DATETIME NULL,
    MODIFY COLUMN status_operativo VARCHAR(30) NOT NULL DEFAULT 'assistant_active';

UPDATE chat_sessions
SET
    owner_type = CASE
        WHEN owner_type IN ('bot', 'ia') OR owner_type IS NULL THEN 'assistant'
        ELSE owner_type
    END,
    status_operativo = CASE
        WHEN status_operativo IN ('bot_active', 'ia_active') OR status_operativo IS NULL THEN 'assistant_active'
        ELSE status_operativo
    END;

ALTER TABLE chat_technical_logs
    ADD COLUMN resolution TEXT NULL,
    ADD COLUMN return_action VARCHAR(40) NULL,
    ADD COLUMN sla_due_at DATETIME NULL;

CREATE INDEX idx_chat_transfer_to_owner
    ON chat_transfer_audit (to_assigned_user_id, created_at);

CREATE INDEX idx_technical_sla
    ON chat_technical_logs (status, sla_due_at);

CREATE INDEX idx_chat_support_return
    ON chat_sessions (assigned_role, previous_owner_user_id, transfer_created_at);
```
