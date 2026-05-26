ALTER TABLE messages
    ADD COLUMN extra_json JSON NULL AFTER file_name;
