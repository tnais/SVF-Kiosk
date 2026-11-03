CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    display_title TEXT NOT NULL,
    description TEXT,
    duration_seconds INTEGER DEFAULT 0,
    resolution TEXT DEFAULT '',
    date_added DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted INTEGER DEFAULT 0,
    deleted_at DATETIME NULL
);

CREATE TABLE IF NOT EXISTS playlist (
    position INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS remote_presets (
    preset_key INTEGER PRIMARY KEY CHECK(preset_key BETWEEN 1 AND 9),
    video_id INTEGER NOT NULL,
    FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
