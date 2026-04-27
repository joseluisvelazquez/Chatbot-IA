# Panel Manager Assignment Hardening

Apply this after the April 22 panel migrations.

This pass does not create new test phones and does not touch the existing
`test_mode` rows. It only optimizes manager lookup / stale-assignment sweep.

```sql
CREATE INDEX idx_colaboradores_username
    ON colaboradores (nombre_usuario);

CREATE INDEX idx_colaboradores_operativo_lookup
    ON colaboradores (id_emp_col, estatus, puesto, nombre_usuario);

CREATE INDEX idx_chat_assignment_status_user
    ON chat_sessions (assigned_role, status_operativo, assigned_user_id);
```

If any of those indexes already exist in the target instance, skip the matching
statement.
