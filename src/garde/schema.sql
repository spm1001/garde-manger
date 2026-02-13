-- Conversation Memory System - SQLite Schema
-- Run with: sqlite3 memory.db < schema.sql

-- Sources: metadata for everything we've seen
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,              -- composite: type:identifier
    source_type TEXT NOT NULL,        -- claude_ai, claude_code, gdoc, etc.
    title TEXT,                       -- name/subject/filename
    path TEXT,                        -- where to find it (may be null for API sources)
    content_hash TEXT,                -- for change detection / relocation
    created_at TEXT,                  -- from source metadata
    updated_at TEXT,                  -- from source metadata
    input_mode TEXT,                  -- 'voice' or null (for conversations)
    is_subagent BOOLEAN DEFAULT FALSE,-- Claude Code subagent conversations
    project_path TEXT,                -- Claude Code: project directory name
    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    status TEXT DEFAULT 'pending',    -- pending, processed, skipped, failed
    error_message TEXT
);

-- Summaries: what we index and search
CREATE TABLE IF NOT EXISTS summaries (
    source_id TEXT PRIMARY KEY REFERENCES sources(id),
    summary_text TEXT NOT NULL,
    raw_text TEXT,                         -- full conversation text (capped at 100K)
    has_presummary BOOLEAN DEFAULT FALSE,  -- true if from source, false if LLM-generated
    word_count INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search index
-- Note: NOT using external content mode (content='summaries') because:
-- 1. FTS5 needs title column which lives in sources, not summaries
-- 2. Triggers already insert all data including title via JOIN
-- 3. Storing content directly avoids the schema mismatch
CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts USING fts5(
    source_id,
    title,
    summary_text,
    raw_text
);

-- Triggers to keep FTS in sync (INSERT, UPDATE, DELETE)
CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
    INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
    SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
    FROM summaries s JOIN sources src ON s.source_id = src.id
    WHERE s.source_id = NEW.source_id;
END;

CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
    INSERT INTO summaries_fts(summaries_fts, rowid, source_id, title, summary_text, raw_text)
    VALUES('delete', OLD.rowid, OLD.source_id,
           (SELECT title FROM sources WHERE id = OLD.source_id),
           OLD.summary_text, OLD.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
    INSERT INTO summaries_fts(summaries_fts, rowid, source_id, title, summary_text, raw_text)
    VALUES('delete', OLD.rowid, OLD.source_id,
           (SELECT title FROM sources WHERE id = OLD.source_id),
           OLD.summary_text, OLD.raw_text);
    INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
    SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
    FROM summaries s JOIN sources src ON s.source_id = src.id
    WHERE s.source_id = NEW.source_id;
END;

-- Entities mentioned in each source
CREATE TABLE IF NOT EXISTS source_entities (
    source_id TEXT REFERENCES sources(id),
    entity_id TEXT,                   -- canonical name from glossary
    mention_text TEXT,                -- how it appeared in source
    confidence REAL,
    PRIMARY KEY (source_id, entity_id, mention_text)
);

-- Entity resolution candidates (pending human review)
CREATE TABLE IF NOT EXISTS pending_entities (
    id INTEGER PRIMARY KEY,
    mention_text TEXT NOT NULL,
    source_id TEXT REFERENCES sources(id),
    suggested_entity TEXT,            -- null if completely unknown
    confidence REAL,
    status TEXT DEFAULT 'pending',    -- pending, resolved, rejected
    resolution TEXT,                  -- what it was resolved to
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_subagent ON sources(is_subagent) WHERE is_subagent = TRUE;
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
