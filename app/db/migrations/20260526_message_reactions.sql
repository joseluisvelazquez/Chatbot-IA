CREATE TABLE message_reactions (
    id INT NOT NULL AUTO_INCREMENT,
    message_id INT NOT NULL,
    wa_message_id_original VARCHAR(120) COLLATE utf8mb4_unicode_ci NOT NULL,
    reaction_emoji VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL,
    reacted_by_phone VARCHAR(20) COLLATE utf8mb4_unicode_ci NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_message_reactions_original_phone (wa_message_id_original, reacted_by_phone),
    KEY idx_message_reactions_message_id (message_id),
    KEY idx_message_reactions_wa_original (wa_message_id_original),
    CONSTRAINT fk_message_reactions_message
        FOREIGN KEY (message_id) REFERENCES messages (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
