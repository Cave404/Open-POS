CREATE TABLE IF NOT EXISTS test_addon_data (
    id SERIAL PRIMARY KEY,
    test_key TEXT UNIQUE,
    test_val TEXT
);
