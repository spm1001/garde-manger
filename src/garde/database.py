"""SQLite database for conversation memory.

Schema includes:
- sources: metadata for all indexed content
- summaries: searchable text (pre-generated or LLM-created)
- summaries_fts: FTS5 virtual table for full-text search
- source_entities: entity mentions per source
- pending_entities: entities awaiting resolution
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Any
from dataclasses import dataclass

from .config import get_db_path


SCHEMA = """
-- Sources: metadata for everything we've seen
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,              -- composite: type:identifier
    source_type TEXT NOT NULL,        -- claude_ai, claude_code, gdoc, etc.
    title TEXT,                       -- name/subject/filename
    path TEXT,                        -- where to find it
    content_hash TEXT,                -- for change detection
    created_at TEXT,                  -- from source metadata
    updated_at TEXT,                  -- from source metadata
    input_mode TEXT,                  -- 'voice' or null
    is_subagent BOOLEAN DEFAULT FALSE,
    project_path TEXT,                -- Claude Code: project directory
    metadata TEXT,                    -- JSON blob: tool usage, files touched, etc.
    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    status TEXT DEFAULT 'pending'     -- pending, processed, skipped, failed
);

-- Summaries: what we index and search
CREATE TABLE IF NOT EXISTS summaries (
    source_id TEXT PRIMARY KEY REFERENCES sources(id),
    summary_text TEXT NOT NULL,
    raw_text TEXT,                        -- full conversation text (capped at 100K)
    title TEXT,                           -- denormalized at insert; FTS triggers use JOIN to sources instead
    has_presummary BOOLEAN DEFAULT FALSE,
    word_count INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search index (standalone mode - triggers keep it in sync)
CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts USING fts5(
    source_id,
    title,
    summary_text,
    raw_text
);

-- Triggers to keep summaries FTS in sync (title comes from sources via JOIN)
CREATE TRIGGER IF NOT EXISTS summaries_ai AFTER INSERT ON summaries BEGIN
    INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
    SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
    FROM summaries s JOIN sources src ON s.source_id = src.id
    WHERE s.source_id = NEW.source_id;
END;

-- Note: summaries_fts is STANDALONE mode, so use regular DELETE (not the special
-- INSERT ... VALUES('delete', ...) syntax which is only for contentless/external content)
CREATE TRIGGER IF NOT EXISTS summaries_ad AFTER DELETE ON summaries BEGIN
    DELETE FROM summaries_fts WHERE rowid = OLD.rowid;
END;

CREATE TRIGGER IF NOT EXISTS summaries_au AFTER UPDATE ON summaries BEGIN
    DELETE FROM summaries_fts WHERE rowid = OLD.rowid;
    INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
    SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
    FROM summaries s JOIN sources src ON s.source_id = src.id
    WHERE s.source_id = NEW.source_id;
END;

-- Entity mentions resolved to glossary entities
CREATE TABLE IF NOT EXISTS source_entities (
    source_id TEXT REFERENCES sources(id),
    entity_id TEXT NOT NULL,          -- canonical name from glossary
    mention_text TEXT NOT NULL,       -- how it appeared in source
    confidence REAL,
    PRIMARY KEY (source_id, entity_id, mention_text)
);

-- Entities awaiting human resolution
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

-- Hybrid extractions: structured digest from conversations
CREATE TABLE IF NOT EXISTS extractions (
    source_id TEXT PRIMARY KEY REFERENCES sources(id),
    summary TEXT,                      -- 2-3 sentence summary
    arc TEXT,                          -- JSON: started_with, key_turns, ended_at
    builds TEXT,                       -- JSON array: things created/modified
    learnings TEXT,                    -- JSON array: insights with why_it_matters
    friction TEXT,                     -- JSON array: problems encountered
    patterns TEXT,                     -- JSON array: recurring themes
    open_threads TEXT,                 -- JSON array: unfinished business
    model_used TEXT,                   -- e.g., claude-sonnet-4-20250514
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- File mentions: files touched per source (for file-based search)
CREATE TABLE IF NOT EXISTS file_mentions (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    file_path TEXT NOT NULL,
    operation TEXT,                    -- 'read', 'edit', 'write', or null
    UNIQUE(source_id, file_path)
);

-- Full-text search for file paths
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_path,
    content='file_mentions',
    content_rowid='id'
);

-- Triggers to keep files FTS in sync
CREATE TRIGGER IF NOT EXISTS file_mentions_ai AFTER INSERT ON file_mentions BEGIN
    INSERT INTO files_fts(rowid, file_path) VALUES (NEW.id, NEW.file_path);
END;

CREATE TRIGGER IF NOT EXISTS file_mentions_ad AFTER DELETE ON file_mentions BEGIN
    INSERT INTO files_fts(files_fts, rowid, file_path) VALUES('delete', OLD.id, OLD.file_path);
END;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
CREATE INDEX IF NOT EXISTS idx_sources_subagent ON sources(is_subagent) WHERE is_subagent = TRUE;
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_entities(status);
CREATE INDEX IF NOT EXISTS idx_source_entities_entity ON source_entities(entity_id);
CREATE INDEX IF NOT EXISTS idx_extractions_model ON extractions(model_used);
CREATE INDEX IF NOT EXISTS idx_file_mentions_source ON file_mentions(source_id);
"""


@dataclass
class SearchResult:
    """A search result from FTS5."""
    source_id: str
    source_type: str
    title: str
    summary_text: str
    created_at: str
    rank: float


class Database:
    """SQLite database connection and operations."""

    def __init__(self, db_path: Path | None = None):
        """Initialize database.

        Args:
            db_path: Path to local database file
        """
        self.db_path = db_path or get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None

    def connect(self):
        """Get or create database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def _init_schema(self):
        """Initialize database schema."""
        self._conn.executescript(SCHEMA)
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self):
        """Apply any pending migrations to existing database."""
        # Migration 1: Add metadata column to sources table
        try:
            self._conn.execute("ALTER TABLE sources ADD COLUMN metadata TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration 2: Add raw_text column to summaries table
        try:
            self._conn.execute("ALTER TABLE summaries ADD COLUMN raw_text TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration 3: Fix FTS5 triggers for standalone mode
        # Old triggers used INSERT...VALUES('delete',...) syntax which only works
        # for contentless/external content FTS5 tables. summaries_fts is standalone.
        try:
            # Check if we need to migrate by testing the trigger SQL
            row = self._conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='summaries_ad'"
            ).fetchone()
            if row and "VALUES('delete'" in (row[0] or ''):
                # Old trigger format - need to recreate
                self._conn.execute("DROP TRIGGER IF EXISTS summaries_ad")
                self._conn.execute("DROP TRIGGER IF EXISTS summaries_au")
                self._conn.execute("""
                    CREATE TRIGGER summaries_ad AFTER DELETE ON summaries BEGIN
                        DELETE FROM summaries_fts WHERE rowid = OLD.rowid;
                    END
                """)
                self._conn.execute("""
                    CREATE TRIGGER summaries_au AFTER UPDATE ON summaries BEGIN
                        DELETE FROM summaries_fts WHERE rowid = OLD.rowid;
                        INSERT INTO summaries_fts(rowid, source_id, title, summary_text, raw_text)
                        SELECT s.rowid, s.source_id, src.title, s.summary_text, s.raw_text
                        FROM summaries s JOIN sources src ON s.source_id = src.id
                        WHERE s.source_id = NEW.source_id;
                    END
                """)
        except sqlite3.OperationalError:
            pass  # Triggers don't exist or migration already done

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    # Source operations

    def upsert_source(
        self,
        source_id: str,
        source_type: str,
        title: str,
        path: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        is_subagent: bool = False,
        project_path: str | None = None,
        content_hash: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Insert or update a source."""
        conn = self.connect()
        metadata_json = json.dumps(metadata) if metadata else None
        conn.execute("""
            INSERT INTO sources (id, source_type, title, path, created_at, updated_at,
                                is_subagent, project_path, content_hash, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                path = excluded.path,
                updated_at = excluded.updated_at,
                content_hash = excluded.content_hash,
                metadata = excluded.metadata
        """, (
            source_id,
            source_type,
            title,
            path,
            created_at.isoformat() if created_at else None,
            updated_at.isoformat() if updated_at else None,
            is_subagent,
            project_path,
            content_hash,
            metadata_json,
        ))
        conn.commit()

    def get_source(self, source_id: str) -> dict | None:
        """Get source by ID."""
        conn = self.connect()
        cursor = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_sources(
        self,
        source_type: str | None = None,
        status: str | None = None,
        limit: int = 100
    ) -> list[dict]:
        """List sources with optional filters."""
        conn = self.connect()
        query = "SELECT * FROM sources WHERE 1=1"
        params = []

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def mark_processed(self, source_id: str) -> None:
        """Mark a source as processed."""
        conn = self.connect()
        conn.execute("""
            UPDATE sources
            SET status = 'processed', processed_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), source_id))
        conn.commit()

    def source_exists(self, source_id: str) -> bool:
        """Check if source already exists."""
        conn = self.connect()
        cursor = conn.execute("SELECT 1 FROM sources WHERE id = ?", (source_id,))
        return cursor.fetchone() is not None

    def delete_source(self, source_id: str) -> bool:
        """Delete a source and all related data.

        Cascades to: summaries, extractions, source_entities,
        pending_entities, file_mentions.

        Returns True if source was found and deleted.
        """
        conn = self.connect()
        with conn:
            # Delete related rows first (no CASCADE in schema)
            conn.execute("DELETE FROM file_mentions WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM pending_entities WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM source_entities WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM extractions WHERE source_id = ?", (source_id,))
            # This triggers FTS cleanup via summaries_ad trigger
            conn.execute("DELETE FROM summaries WHERE source_id = ?", (source_id,))
            # Delete source
            cursor = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            return cursor.rowcount > 0

    def mark_stale(self, source_id: str) -> bool:
        """Mark a source as stale (path no longer exists).

        Preserves summaries and extractions for continued search value.
        Returns True if source was found and marked.
        """
        conn = self.connect()
        cursor = conn.execute(
            "UPDATE sources SET status = 'stale' WHERE id = ?",
            (source_id,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def mark_stale_batch(self, source_ids: list[str]) -> int:
        """Mark multiple sources as stale. Returns count marked."""
        conn = self.connect()
        cursor = conn.executemany(
            "UPDATE sources SET status = 'stale' WHERE id = ?",
            [(sid,) for sid in source_ids]
        )
        conn.commit()
        return cursor.rowcount

    def get_sources_with_paths(
        self,
        source_type: str | None = None,
        include_stale: bool = False
    ) -> list[dict]:
        """Get all sources that have filesystem paths.

        Args:
            source_type: Optional filter by source type
            include_stale: If False (default), exclude sources already marked stale

        Returns:
            List of source dicts with id, source_type, path, title
        """
        conn = self.connect()
        query = "SELECT id, source_type, path, title FROM sources WHERE path IS NOT NULL"
        params = []

        if not include_stale:
            query += " AND (status IS NULL OR status != 'stale')"

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)

        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    # Summary operations

    def upsert_summary(
        self,
        source_id: str,
        summary_text: str,
        has_presummary: bool = False,
        raw_text: str | None = None,
        title: str | None = None,
    ) -> None:
        """Insert or update a summary.

        Args:
            source_id: The source identifier
            summary_text: Extraction summary or title (for FTS)
            has_presummary: Whether source has pre-generated summary
            raw_text: Full conversation text (capped at 100K chars) for FTS
            title: Session title (denormalized from sources for FTS)
        """
        conn = self.connect()
        word_count = len(summary_text.split())
        # Cap raw_text at 100K chars
        if raw_text and len(raw_text) > 100_000:
            raw_text = raw_text[:100_000]
        # If title not provided, fetch from sources
        if title is None:
            row = conn.execute("SELECT title FROM sources WHERE id = ?", (source_id,)).fetchone()
            title = row[0] if row else None
        conn.execute("""
            INSERT INTO summaries (source_id, summary_text, has_presummary, word_count, raw_text, title)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                summary_text = excluded.summary_text,
                has_presummary = excluded.has_presummary,
                word_count = excluded.word_count,
                raw_text = excluded.raw_text,
                title = excluded.title
        """, (source_id, summary_text, has_presummary, word_count, raw_text or '', title))
        conn.commit()

    # Extraction operations

    def upsert_extraction(
        self,
        source_id: str,
        summary: str | None = None,
        arc: dict | None = None,
        builds: list | None = None,
        learnings: list | None = None,
        friction: list | None = None,
        patterns: list | None = None,
        open_threads: list | None = None,
        model_used: str | None = None,
    ) -> None:
        """Insert or update a hybrid extraction."""
        conn = self.connect()
        conn.execute("""
            INSERT INTO extractions (
                source_id, summary, arc, builds, learnings,
                friction, patterns, open_threads, model_used
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                summary = excluded.summary,
                arc = excluded.arc,
                builds = excluded.builds,
                learnings = excluded.learnings,
                friction = excluded.friction,
                patterns = excluded.patterns,
                open_threads = excluded.open_threads,
                model_used = excluded.model_used,
                extracted_at = CURRENT_TIMESTAMP
        """, (
            source_id,
            summary,
            json.dumps(arc) if arc else None,
            json.dumps(builds) if builds else None,
            json.dumps(learnings) if learnings else None,
            json.dumps(friction) if friction else None,
            json.dumps(patterns) if patterns else None,
            json.dumps(open_threads) if open_threads else None,
            model_used,
        ))

        # Update summaries table with extraction summary for FTS indexing
        if summary:
            conn.execute("""
                UPDATE summaries SET summary_text = ?
                WHERE source_id = ?
            """, (summary, source_id))

        conn.commit()

    def get_extraction(self, source_id: str) -> dict | None:
        """Get extraction for a source, with JSON fields parsed."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM extractions WHERE source_id = ?",
            (source_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            'source_id': row['source_id'],
            'summary': row['summary'],
            'arc': json.loads(row['arc']) if row['arc'] else None,
            'builds': json.loads(row['builds']) if row['builds'] else None,
            'learnings': json.loads(row['learnings']) if row['learnings'] else None,
            'friction': json.loads(row['friction']) if row['friction'] else None,
            'patterns': json.loads(row['patterns']) if row['patterns'] else None,
            'open_threads': json.loads(row['open_threads']) if row['open_threads'] else None,
            'model_used': row['model_used'],
            'extracted_at': row['extracted_at'],
        }

    def has_extraction(self, source_id: str) -> bool:
        """Check if source has a hybrid extraction."""
        conn = self.connect()
        cursor = conn.execute(
            "SELECT 1 FROM extractions WHERE source_id = ?",
            (source_id,)
        )
        return cursor.fetchone() is not None

    # Search operations

    def search(
        self,
        query: str,
        source_type: str | None = None,
        project_path: str | None = None,
        limit: int = 5,
        recency_half_life: int | None = None,
    ) -> list[SearchResult]:
        """Full-text search over summaries.

        Args:
            query: FTS5 search query
            source_type: Filter by source type (claude_code, handoff, etc.)
            project_path: Filter by project path (matches against src.project_path)
            limit: Maximum number of results
            recency_half_life: If set, apply recency decay with this half-life in days.
                Recent results rank higher. E.g., 90 means 90-day-old results get 0.5x weight.
        """
        from datetime import datetime, timezone

        conn = self.connect()

        # FTS5 search - join with sources for metadata
        sql = """
            SELECT
                s.source_id,
                src.source_type,
                src.title,
                s.summary_text,
                src.created_at,
                bm25(summaries_fts) as rank
            FROM summaries_fts
            JOIN summaries s ON summaries_fts.rowid = s.rowid
            JOIN sources src ON s.source_id = src.id
            WHERE summaries_fts MATCH ?
        """
        params = [query]

        if source_type:
            sql += " AND src.source_type = ?"
            params.append(source_type)

        if project_path:
            # Match project_path - use LIKE for flexibility (handles slight variations)
            sql += " AND src.project_path LIKE ?"
            params.append(f"%{project_path}%")

        # If recency weighting, fetch more results to rerank
        fetch_limit = limit * 20 if recency_half_life else limit
        sql += " ORDER BY rank LIMIT ?"
        params.append(fetch_limit)

        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()

        results = [
            SearchResult(
                source_id=row['source_id'],
                source_type=row['source_type'],
                title=row['title'],
                summary_text=row['summary_text'],
                created_at=row['created_at'],
                rank=row['rank'],
            )
            for row in rows
        ]

        # Apply recency decay if requested
        if recency_half_life and results:
            now = datetime.now(timezone.utc)
            for r in results:
                if r.created_at:
                    try:
                        created = datetime.fromisoformat(r.created_at.replace('Z', '+00:00'))
                        days_old = (now - created).days
                        decay = 0.5 ** (days_old / recency_half_life)
                        # BM25 scores are negative (closer to 0 = better), so multiply
                        r.rank = r.rank * decay
                    except (ValueError, TypeError):
                        pass  # Keep original rank if date parsing fails
            # Re-sort by decayed rank (more negative = better match)
            results.sort(key=lambda r: r.rank)
            results = results[:limit]

        return results

    # Entity operations

    def add_source_entity(
        self,
        source_id: str,
        entity_id: str,
        mention_text: str,
        confidence: float = 0.9,
    ) -> None:
        """Add a resolved entity mention for a source."""
        conn = self.connect()
        conn.execute("""
            INSERT OR REPLACE INTO source_entities
            (source_id, entity_id, mention_text, confidence)
            VALUES (?, ?, ?, ?)
        """, (source_id, entity_id, mention_text, confidence))
        conn.commit()

    def queue_pending_entity(
        self,
        mention_text: str,
        source_id: str,
        suggested_entity: str | None = None,
        confidence: float = 0.5,
    ) -> int:
        """Queue an entity for human resolution. Returns the pending entity ID."""
        conn = self.connect()
        cursor = conn.execute("""
            INSERT INTO pending_entities
            (mention_text, source_id, suggested_entity, confidence)
            VALUES (?, ?, ?, ?)
        """, (mention_text, source_id, suggested_entity, confidence))
        conn.commit()
        return cursor.lastrowid

    def get_pending_entities(
        self,
        limit: int = 20,
        status: str = 'pending'
    ) -> list[dict]:
        """Get pending entities for resolution."""
        conn = self.connect()
        cursor = conn.execute("""
            SELECT pe.*, src.title as source_title
            FROM pending_entities pe
            LEFT JOIN sources src ON pe.source_id = src.id
            WHERE pe.status = ?
            ORDER BY pe.confidence DESC, pe.created_at ASC
            LIMIT ?
        """, (status, limit))
        return [dict(row) for row in cursor.fetchall()]

    def resolve_pending_entity(
        self,
        pending_id: int,
        resolution: str | None,
        status: str = 'resolved'
    ) -> None:
        """Resolve or reject a pending entity.

        Args:
            pending_id: The pending entity ID
            resolution: The canonical entity name it resolves to (None if rejected)
            status: 'resolved' or 'rejected'
        """
        conn = self.connect()
        conn.execute("""
            UPDATE pending_entities
            SET status = ?, resolution = ?
            WHERE id = ?
        """, (status, resolution, pending_id))
        conn.commit()

    def get_entities_for_source(self, source_id: str) -> list[dict]:
        """Get all resolved entities for a source."""
        conn = self.connect()
        cursor = conn.execute("""
            SELECT entity_id, mention_text, confidence
            FROM source_entities
            WHERE source_id = ?
            ORDER BY confidence DESC
        """, (source_id,))
        return [dict(row) for row in cursor.fetchall()]

    # File mention operations

    def add_file_mention(
        self,
        source_id: str,
        file_path: str,
        operation: str | None = None,
    ) -> None:
        """Add a file mention for a source."""
        conn = self.connect()
        conn.execute("""
            INSERT OR IGNORE INTO file_mentions
            (source_id, file_path, operation)
            VALUES (?, ?, ?)
        """, (source_id, file_path, operation))
        conn.commit()

    def add_file_mentions_batch(
        self,
        source_id: str,
        file_paths: list[str],
        operation: str | None = None,
    ) -> int:
        """Add multiple file mentions for a source. Returns count added."""
        conn = self.connect()
        cursor = conn.executemany("""
            INSERT OR IGNORE INTO file_mentions
            (source_id, file_path, operation)
            VALUES (?, ?, ?)
        """, [(source_id, fp, operation) for fp in file_paths])
        conn.commit()
        return cursor.rowcount

    def search_files(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """Search for sources by file path.

        Args:
            query: FTS5 query (auto-quotes patterns with dots)
            limit: Maximum results

        Returns:
            List of dicts with source_id, file_path, source metadata
        """
        conn = self.connect()

        # Auto-quote patterns containing dots (file extensions)
        if '.' in query and not query.startswith('"'):
            query = f'"{query}"'

        cursor = conn.execute("""
            SELECT
                fm.source_id,
                fm.file_path,
                fm.operation,
                src.source_type,
                src.title,
                src.created_at
            FROM files_fts
            JOIN file_mentions fm ON files_fts.rowid = fm.id
            JOIN sources src ON fm.source_id = src.id
            WHERE files_fts MATCH ?
            ORDER BY src.created_at DESC
            LIMIT ?
        """, (query, limit))

        return [dict(row) for row in cursor.fetchall()]

    def get_files_for_source(self, source_id: str) -> list[dict]:
        """Get all file mentions for a source."""
        conn = self.connect()
        cursor = conn.execute("""
            SELECT file_path, operation
            FROM file_mentions
            WHERE source_id = ?
            ORDER BY file_path
        """, (source_id,))
        return [dict(row) for row in cursor.fetchall()]

    # Stats

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        conn = self.connect()

        cursor = conn.execute("SELECT COUNT(*) FROM sources")
        total = cursor.fetchone()[0]

        cursor = conn.execute("""
            SELECT source_type, COUNT(*) as count
            FROM sources GROUP BY source_type
        """)
        by_type = cursor.fetchall()

        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM sources GROUP BY status
        """)
        by_status = cursor.fetchall()

        cursor = conn.execute("SELECT COUNT(*) FROM summaries")
        summaries = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT COUNT(*) FROM pending_entities WHERE status = 'pending'"
        )
        pending = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT COUNT(DISTINCT entity_id) FROM source_entities"
        )
        resolved_entities = cursor.fetchone()[0]

        return {
            'total_sources': total,
            'by_type': {row['source_type']: row['count'] for row in by_type},
            'by_status': {row['status']: row['count'] for row in by_status},
            'summaries': summaries,
            'pending_entities': pending,
            'resolved_entities': resolved_entities,
        }


def get_database() -> Database:
    """Get a database instance."""
    return Database()
