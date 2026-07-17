from __future__ import annotations

import json
import pathlib
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
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            status TEXT NOT NULL,
            face_count INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            indexed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY,
            photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            face_index INTEGER NOT NULL,
            detector_score REAL NOT NULL,
            bbox_json TEXT NOT NULL,
            landmarks_json TEXT NOT NULL,
            embedding BLOB NOT NULL,
            embedding_dim INTEGER NOT NULL,
            UNIQUE(photo_id, face_index)
        );
        CREATE INDEX IF NOT EXISTS faces_photo_id_idx ON faces(photo_id);
        CREATE INDEX IF NOT EXISTS photos_status_idx ON photos(status);
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    connection.commit()
    return connection


def photo_needs_index(connection: sqlite3.Connection, path: pathlib.Path) -> bool:
    stat = path.stat()
    row = connection.execute(
        "SELECT size_bytes, mtime_ns, status FROM photos WHERE path = ?",
        (str(path),),
    ).fetchone()
    return row is None or row["status"] != "complete" or row["size_bytes"] != stat.st_size or row["mtime_ns"] != stat.st_mtime_ns


def store_result(
    connection: sqlite3.Connection,
    path: pathlib.Path,
    result: dict[str, object],
    indexed_at: str,
) -> None:
    stat = path.stat()
    faces = result.get("faces")
    if not isinstance(faces, list):
        raise ValueError("face result is missing faces[]")
    connection.execute(
        """
        INSERT INTO photos(path, size_bytes, mtime_ns, status, face_count, error, indexed_at)
        VALUES(?, ?, ?, 'complete', ?, NULL, ?)
        ON CONFLICT(path) DO UPDATE SET
          size_bytes=excluded.size_bytes,
          mtime_ns=excluded.mtime_ns,
          status='complete',
          face_count=excluded.face_count,
          error=NULL,
          indexed_at=excluded.indexed_at
        """,
        (str(path), stat.st_size, stat.st_mtime_ns, len(faces), indexed_at),
    )
    photo_id = connection.execute("SELECT id FROM photos WHERE path = ?", (str(path),)).fetchone()["id"]
    connection.execute("DELETE FROM faces WHERE photo_id = ?", (photo_id,))
    for raw_face in faces:
        if not isinstance(raw_face, dict):
            raise ValueError("face result contains a non-object")
        embedding = raw_face.get("embedding")
        detection = raw_face.get("detection")
        if not isinstance(embedding, list) or not isinstance(detection, dict):
            raise ValueError("face result is missing embedding or detection")
        vector = [float(value) for value in embedding]
        if len(vector) != 512:
            raise ValueError(f"expected a 512-dimensional embedding, found {len(vector)}")
        connection.execute(
            """
            INSERT INTO faces(
              photo_id, face_index, detector_score, bbox_json,
              landmarks_json, embedding, embedding_dim
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                photo_id,
                int(raw_face.get("index", 0)),
                float(detection.get("score", 0)),
                json.dumps(detection.get("boundingBox", {}), sort_keys=True),
                json.dumps(detection.get("landmarks", []), sort_keys=True),
                sqlite3.Binary(struct.pack("<512f", *vector)),
                len(vector),
            ),
        )
    connection.commit()


def store_error(
    connection: sqlite3.Connection,
    path: pathlib.Path,
    error: str,
    indexed_at: str,
) -> None:
    stat = path.stat()
    connection.execute(
        """
        INSERT INTO photos(path, size_bytes, mtime_ns, status, face_count, error, indexed_at)
        VALUES(?, ?, ?, 'error', 0, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          size_bytes=excluded.size_bytes,
          mtime_ns=excluded.mtime_ns,
          status='error',
          face_count=0,
          error=excluded.error,
          indexed_at=excluded.indexed_at
        """,
        (str(path), stat.st_size, stat.st_mtime_ns, error, indexed_at),
    )
    photo_id = connection.execute("SELECT id FROM photos WHERE path = ?", (str(path),)).fetchone()["id"]
    connection.execute("DELETE FROM faces WHERE photo_id = ?", (photo_id,))
    connection.commit()


def iter_face_embeddings(connection: sqlite3.Connection) -> Iterator[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT faces.id AS face_id, faces.face_index, faces.detector_score,
               faces.bbox_json, faces.landmarks_json, faces.embedding,
               photos.path
        FROM faces JOIN photos ON photos.id = faces.photo_id
        WHERE photos.status = 'complete' AND faces.embedding_dim = 512
        ORDER BY photos.id, faces.face_index
        """
    )
    for row in rows:
        yield {
            "face_id": row["face_id"],
            "face_index": row["face_index"],
            "detector_score": row["detector_score"],
            "bounding_box": json.loads(row["bbox_json"]),
            "landmarks": json.loads(row["landmarks_json"]),
            "embedding": struct.unpack("<512f", row["embedding"]),
            "path": row["path"],
        }


def stats(connection: sqlite3.Connection) -> dict[str, int]:
    photo_counts = {
        row["status"]: row["count"]
        for row in connection.execute("SELECT status, COUNT(*) AS count FROM photos GROUP BY status")
    }
    face_count = connection.execute("SELECT COUNT(*) AS count FROM faces").fetchone()["count"]
    return {
        "photos": sum(photo_counts.values()),
        "complete": photo_counts.get("complete", 0),
        "errors": photo_counts.get("error", 0),
        "faces": face_count,
    }


def set_metadata(connection: sqlite3.Connection, values: Iterable[tuple[str, str]]) -> None:
    connection.executemany("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", values)
    connection.commit()
