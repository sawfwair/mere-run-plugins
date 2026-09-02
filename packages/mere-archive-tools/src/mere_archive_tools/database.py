"""Versioned SQLite storage for the shared-drive index."""

from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import struct
from collections.abc import Iterable, Iterator

SCHEMA_VERSION = 1


def connect(path: pathlib.Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            storage_tier TEXT NOT NULL,
            display_text TEXT,
            keywords_json TEXT,
            pii_reduced INTEGER NOT NULL CHECK(pii_reduced = 1),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            relative_path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            sha256 TEXT,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            error_code TEXT,
            indexed_at TEXT,
            content_id INTEGER REFERENCES contents(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            content_id INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            modality TEXT NOT NULL,
            text TEXT,
            embedding BLOB NOT NULL,
            embedding_dim INTEGER NOT NULL,
            UNIQUE(content_id, chunk_index, modality)
        );
        CREATE INDEX IF NOT EXISTS files_status_idx ON files(status);
        CREATE INDEX IF NOT EXISTS files_content_id_idx ON files(content_id);
        CREATE INDEX IF NOT EXISTS chunks_content_id_idx ON chunks(content_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
            content_id UNINDEXED,
            body,
            tokenize='unicode61'
        );
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


def metadata(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}


def configure(connection: sqlite3.Connection, values: Iterable[tuple[str, str]]) -> None:
    existing = metadata(connection)
    for key, value in values:
        if key in existing and existing[key] != value:
            raise ValueError(
                f"database setting {key} is {existing[key]!r}, not {value!r}; create a separate database"
            )
        connection.execute("INSERT OR IGNORE INTO metadata(key, value) VALUES(?, ?)", (key, value))
    connection.commit()


def file_needs_index(connection: sqlite3.Connection, path: pathlib.Path) -> bool:
    stat = path.stat()
    row = connection.execute(
        "SELECT size_bytes, mtime_ns, status FROM files WHERE path = ?",
        (str(path),),
    ).fetchone()
    return (
        row is None
        or row["status"] != "complete"
        or row["size_bytes"] != stat.st_size
        or row["mtime_ns"] != stat.st_mtime_ns
    )


def content_id_for_sha(connection: sqlite3.Connection, sha256: str) -> int | None:
    row = connection.execute("SELECT id FROM contents WHERE sha256 = ?", (sha256,)).fetchone()
    return int(row["id"]) if row is not None else None


def store_content(
    connection: sqlite3.Connection,
    sha256: str,
    kind: str,
    storage_tier: str,
    display_text: str | None,
    keywords: list[str] | None,
    chunks: list[tuple[int, str, str | None, list[float]]],
    created_at: str,
) -> int:
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO contents(
              sha256, kind, storage_tier, display_text, keywords_json,
              pii_reduced, created_at
            ) VALUES(?, ?, ?, ?, ?, 1, ?)
            """,
            (
                sha256,
                kind,
                storage_tier,
                display_text,
                json.dumps(keywords, sort_keys=True) if keywords is not None else None,
                created_at,
            ),
        )
        if cursor.lastrowid is None:
            raise sqlite3.DatabaseError("SQLite didn't return a content identifier")
        content_id = cursor.lastrowid
        for chunk_index, modality, chunk_text, vector in chunks:
            packed = struct.pack(f"<{len(vector)}f", *vector)
            connection.execute(
                """
                INSERT INTO chunks(
                  content_id, chunk_index, modality, text, embedding, embedding_dim
                ) VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    content_id,
                    chunk_index,
                    modality,
                    chunk_text,
                    sqlite3.Binary(packed),
                    len(vector),
                ),
            )
        if display_text:
            connection.execute(
                "INSERT INTO content_fts(content_id, body) VALUES(?, ?)",
                (content_id, display_text),
            )
    return content_id


def store_file_success(
    connection: sqlite3.Connection,
    path: pathlib.Path,
    relative_path: str,
    size_bytes: int,
    mtime_ns: int,
    sha256: str,
    kind: str,
    content_id: int,
    indexed_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO files(
          path, relative_path, size_bytes, mtime_ns, sha256, kind, status,
          error_code, indexed_at, content_id
        ) VALUES(?, ?, ?, ?, ?, ?, 'complete', NULL, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          relative_path=excluded.relative_path,
          size_bytes=excluded.size_bytes,
          mtime_ns=excluded.mtime_ns,
          sha256=excluded.sha256,
          kind=excluded.kind,
          status='complete',
          error_code=NULL,
          indexed_at=excluded.indexed_at,
          content_id=excluded.content_id
        """,
        (
            str(path),
            relative_path,
            size_bytes,
            mtime_ns,
            sha256,
            kind,
            indexed_at,
            content_id,
        ),
    )
    connection.commit()


def store_file_error(
    connection: sqlite3.Connection,
    path: pathlib.Path,
    relative_path: str,
    kind: str,
    error_code: str,
    indexed_at: str,
    size_bytes: int,
    mtime_ns: int,
) -> None:
    connection.execute(
        """
        INSERT INTO files(
          path, relative_path, size_bytes, mtime_ns, kind, status,
          error_code, indexed_at, content_id
        ) VALUES(?, ?, ?, ?, ?, 'error', ?, ?, NULL)
        ON CONFLICT(path) DO UPDATE SET
          relative_path=excluded.relative_path,
          size_bytes=excluded.size_bytes,
          mtime_ns=excluded.mtime_ns,
          sha256=NULL,
          kind=excluded.kind,
          status='error',
          error_code=excluded.error_code,
          indexed_at=excluded.indexed_at,
          content_id=NULL
        """,
        (str(path), relative_path, size_bytes, mtime_ns, kind, error_code, indexed_at),
    )
    connection.commit()


def prune_missing_files(connection: sqlite3.Connection, current_paths: set[str]) -> int:
    stored = {str(row["path"]) for row in connection.execute("SELECT path FROM files")}
    missing = stored - current_paths
    if missing:
        connection.executemany("DELETE FROM files WHERE path = ?", ((path,) for path in missing))
        connection.commit()
    return len(missing)


def delete_orphan_contents(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        "SELECT id FROM contents WHERE NOT EXISTS (SELECT 1 FROM files WHERE files.content_id = contents.id)"
    ).fetchall()
    identifiers = [int(row["id"]) for row in rows]
    if identifiers:
        connection.executemany("DELETE FROM content_fts WHERE content_id = ?", ((value,) for value in identifiers))
        connection.executemany("DELETE FROM contents WHERE id = ?", ((value,) for value in identifiers))
        connection.commit()
    return len(identifiers)


def stats(connection: sqlite3.Connection) -> dict[str, object]:
    file_counts = {
        str(row["status"]): int(row["count"])
        for row in connection.execute("SELECT status, COUNT(*) AS count FROM files GROUP BY status")
    }
    content_count = int(connection.execute("SELECT COUNT(*) AS count FROM contents").fetchone()["count"])
    chunk_count = int(connection.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()["count"])
    fts_count = int(connection.execute("SELECT COUNT(*) AS count FROM content_fts").fetchone()["count"])
    complete = file_counts.get("complete", 0)
    return {
        "files": sum(file_counts.values()),
        "complete": complete,
        "errors": file_counts.get("error", 0),
        "contents": content_count,
        "duplicates": max(0, complete - content_count),
        "embeddings": chunk_count,
        "fullTextRecords": fts_count,
        "settings": metadata(connection),
    }


def iter_embedding_rows(connection: sqlite3.Connection) -> Iterator[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT chunks.id AS chunk_id, chunks.content_id, chunks.chunk_index,
               chunks.modality, chunks.text AS chunk_text, chunks.embedding,
               chunks.embedding_dim, contents.kind, contents.storage_tier,
               contents.display_text, contents.keywords_json
        FROM chunks
        JOIN contents ON contents.id = chunks.content_id
        WHERE EXISTS (
          SELECT 1 FROM files
          WHERE files.content_id = contents.id AND files.status = 'complete'
        )
        ORDER BY chunks.content_id, chunks.chunk_index, chunks.modality
        """
    )
    for row in rows:
        dimension = int(row["embedding_dim"])
        yield {
            "chunk_id": int(row["chunk_id"]),
            "content_id": int(row["content_id"]),
            "chunk_index": int(row["chunk_index"]),
            "modality": str(row["modality"]),
            "chunk_text": row["chunk_text"],
            "embedding": struct.unpack(f"<{dimension}f", row["embedding"]),
            "kind": str(row["kind"]),
            "storage_tier": str(row["storage_tier"]),
            "display_text": row["display_text"],
            "keywords": json.loads(row["keywords_json"]) if row["keywords_json"] else None,
        }


def lexical_content_ids(connection: sqlite3.Connection, query: str, limit: int = 500) -> set[int]:
    tokens = re.findall(r"[\w-]+", query, flags=re.UNICODE)
    if not tokens:
        return set()
    expression = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens[:32])
    rows = connection.execute(
        "SELECT content_id FROM content_fts WHERE content_fts MATCH ? LIMIT ?",
        (expression, limit),
    )
    return {int(row["content_id"]) for row in rows}


def paths_for_content(connection: sqlite3.Connection, content_id: int) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT path, relative_path, size_bytes, mtime_ns
        FROM files
        WHERE content_id = ? AND status = 'complete'
        ORDER BY relative_path
        """,
        (content_id,),
    )
    return [
        {
            "path": str(row["path"]),
            "relativePath": str(row["relative_path"]),
            "sizeBytes": int(row["size_bytes"]),
            "mtimeNs": int(row["mtime_ns"]),
            "available": pathlib.Path(str(row["path"])).is_file(),
        }
        for row in rows
    ]
