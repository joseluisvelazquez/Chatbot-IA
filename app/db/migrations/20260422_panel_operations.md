# Panel Operations Migration

Run this migration before deploying the backend that reads the new operational
chat columns. The `ALTER TABLE` block is meant to run once; if you need
idempotent execution, validate `INFORMATION_SCHEMA.COLUMNS` and
`INFORMATION_SCHEMA.STATISTICS` before applying it again.

```sql
ALTER TABLE chat_sessions
    ADD COLUMN assigned_user_id VARCHAR(120) NULL,
    ADD COLUMN assigned_role VARCHAR(30) NULL,
    ADD COLUMN owner_type VARCHAR(20) NULL,
    ADD COLUMN status_operativo VARCHAR(30) NOT NULL DEFAULT 'assistant_active',
    ADD COLUMN priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    ADD COLUMN transfer_pending TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN locked_until DATETIME NULL,
    ADD COLUMN assigned_at DATETIME NULL,
    ADD COLUMN last_agent_message_at DATETIME NULL,
    ADD COLUMN last_customer_message_at DATETIME NULL,
    ADD COLUMN returned_from_role VARCHAR(30) NULL,
    ADD COLUMN test_mode TINYINT(1) NOT NULL DEFAULT 0,
    ADD COLUMN transferred_by_user_id VARCHAR(120) NULL,
    ADD COLUMN previous_owner_user_id VARCHAR(120) NULL,
    ADD COLUMN previous_owner_role VARCHAR(30) NULL,
    ADD COLUMN transfer_reason TEXT NULL,
    ADD COLUMN transfer_created_at DATETIME NULL;

UPDATE chat_sessions
SET
    owner_type = CASE
        WHEN owner_type IN ('bot', 'ia') OR owner_type IS NULL THEN 'assistant'
        ELSE owner_type
    END,
    status_operativo = CASE
        WHEN status_operativo IN ('bot_active', 'ia_active') OR status_operativo IS NULL THEN 'assistant_active'
        ELSE status_operativo
    END,
    priority = COALESCE(priority, 'normal'),
    test_mode = CASE
        WHEN REPLACE(REPLACE(phone, '+', ''), ' ', '') IN (
            '5214271227177',
            '5214271665615',
            '5214271644542'
        ) THEN 1
        ELSE COALESCE(test_mode, 0)
    END;

CREATE TABLE IF NOT EXISTS chat_transfer_audit (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    action VARCHAR(40) NOT NULL,
    actor_username VARCHAR(120) NULL,
    actor_role VARCHAR(30) NULL,
    from_owner_type VARCHAR(20) NULL,
    from_assigned_user_id VARCHAR(120) NULL,
    from_assigned_role VARCHAR(30) NULL,
    from_status VARCHAR(30) NULL,
    to_owner_type VARCHAR(20) NULL,
    to_assigned_user_id VARCHAR(120) NULL,
    to_assigned_role VARCHAR(30) NULL,
    to_status VARCHAR(30) NULL,
    reason TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_chat_transfer_audit_session
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chat_technical_logs (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session_id INT NOT NULL,
    phone VARCHAR(20) NULL,
    detected_by VARCHAR(40) NULL,
    keyword VARCHAR(80) NULL,
    description TEXT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    opened_by VARCHAR(120) NULL,
    closed_by VARCHAR(120) NULL,
    resolution TEXT NULL,
    return_action VARCHAR(40) NULL,
    sla_due_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME NULL,
    CONSTRAINT fk_chat_technical_logs_session
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS panel_domain_events (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    aggregate_type VARCHAR(40) NOT NULL,
    aggregate_id VARCHAR(80) NULL,
    actor_username VARCHAR(120) NULL,
    actor_role VARCHAR(30) NULL,
    payload JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_panel_domain_events_event_id (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS panel_feature_flags (
    name VARCHAR(80) NOT NULL PRIMARY KEY,
    enabled TINYINT(1) NOT NULL DEFAULT 0,
    description TEXT NULL,
    updated_by VARCHAR(120) NULL,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_chat_operativo_owner
    ON chat_sessions (owner_type, assigned_role, assigned_user_id);

CREATE INDEX idx_chat_status_test
    ON chat_sessions (status_operativo, test_mode);

CREATE INDEX idx_chat_locked_until
    ON chat_sessions (locked_until);

CREATE INDEX idx_chat_support_return
    ON chat_sessions (assigned_role, previous_owner_user_id, transfer_created_at);

CREATE INDEX idx_chat_transfer_session_created
    ON chat_transfer_audit (session_id, created_at);

CREATE INDEX idx_chat_transfer_actor_created
    ON chat_transfer_audit (actor_username, created_at);

CREATE INDEX idx_technical_session_created
    ON chat_technical_logs (session_id, created_at);

CREATE INDEX idx_technical_status
    ON chat_technical_logs (status);

CREATE INDEX idx_technical_sla
    ON chat_technical_logs (status, sla_due_at);

CREATE INDEX idx_panel_domain_event_type_created
    ON panel_domain_events (event_type, created_at);

CREATE INDEX idx_panel_domain_event_aggregate
    ON panel_domain_events (aggregate_type, aggregate_id);

CREATE INDEX idx_panel_feature_flags_enabled
    ON panel_feature_flags (enabled);
```
