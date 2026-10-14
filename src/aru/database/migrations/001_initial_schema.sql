-- 001_initial_schema.sql: Initial database schema for ARU AI V4

-- 1. Conversation History
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    metadata TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);

-- 2. Long-term Memories
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    tags TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);

-- 3. FTS5 Virtual Table for Fast Full-Text Search across Memories
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    key,
    content,
    category,
    tags,
    content='memories',
    content_rowid='id'
);

-- Triggers to synchronize memories with memories_fts
CREATE TRIGGER IF NOT EXISTS trg_memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, key, content, category, tags)
    VALUES (new.id, new.key, new.content, new.category, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, category, tags)
    VALUES ('delete', old.id, old.key, old.content, old.category, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, content, category, tags)
    VALUES ('delete', old.id, old.key, old.content, old.category, old.tags);
    INSERT INTO memories_fts(rowid, key, content, category, tags)
    VALUES (new.id, new.key, new.content, new.category, new.tags);
END;

-- 4. Tasks
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed', 'cancelled')),
    priority TEXT DEFAULT 'medium' CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
    due_date TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);

-- 5. Anti-Spam Cooldowns and Whitelists
CREATE TABLE IF NOT EXISTS anti_spam_cooldowns (
    user_id INTEGER PRIMARY KEY,
    cooldown_until DATETIME NOT NULL,
    warning_count INTEGER DEFAULT 0,
    last_message_time DATETIME,
    reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS anti_spam_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_spam_events_user ON anti_spam_events(user_id, created_at);

CREATE TABLE IF NOT EXISTS anti_spam_whitelist (
    user_id INTEGER PRIMARY KEY,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT DEFAULT ''
);
