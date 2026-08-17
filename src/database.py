"""database.py — SQLite layer for the Movie Recommendation System.

Models the same entities as the UML class diagram:
  * Person (single SQLite table `users`, with `role` discriminator = USER | ADMIN).
    Conceptually inherits into User and Admin in the application layer.
  * Movie
  * Rating (User 1..* -- Movie 0..*)
  * WatchHistory (User 1..* -- Movie 0..*)

All public functions return plain Python types (list[dict] / scalar) so they
can be consumed directly by Streamlit widgets without a custom adapter.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

# ---------- connection helpers ----------

# Resolve the database location relative to this file so the same path is
# used by Streamlit and by the seed/management scripts.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DEFAULT_DB = os.path.join(_PROJECT_ROOT, "data", "mrs.db")


def db_path() -> str:
    """Return the path to the SQLite database file. Override with MRS_DB env var."""
    return os.environ.get("MRS_DB", _DEFAULT_DB)


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


@contextmanager
def connect(db: str | None = None):
    """Context-managed SQLite connection with row_factory=dict."""
    path = db or db_path()
    _ensure_dir(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------- schema ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username         TEXT NOT NULL UNIQUE,
    display_name     TEXT NOT NULL,
    password_hash    TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('USER', 'ADMIN')),
    geo_id           TEXT,
    preferred_genres TEXT,
    registration_date TEXT NOT NULL,
    last_login_at    TEXT
);

CREATE TABLE IF NOT EXISTS movies (
    movie_id        INTEGER PRIMARY KEY,
    title           TEXT NOT NULL,
    genres          TEXT NOT NULL,         -- '|' separated, matches MovieLens format
    content_rating  TEXT,                  -- age rating (G/PG/PG-13/R/18+ etc.)
    release_year    INTEGER,
    duration_min    INTEGER,
    average_rating  REAL DEFAULT 0.0,
    rating_count    INTEGER DEFAULT 0,
    last_updated    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ratings (
    rating_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    movie_id   INTEGER NOT NULL REFERENCES movies(movie_id) ON DELETE CASCADE,
    score      REAL NOT NULL CHECK (score >= 0.5 AND score <= 5.0),
    timestamp  TEXT NOT NULL,
    UNIQUE (user_id, movie_id)
);

CREATE TABLE IF NOT EXISTS watch_history (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    movie_id       INTEGER NOT NULL REFERENCES movies(movie_id) ON DELETE CASCADE,
    watched_at     TEXT NOT NULL,
    completion_pct REAL NOT NULL CHECK (completion_pct >= 0 AND completion_pct <= 1),
    device         TEXT
);

CREATE INDEX IF NOT EXISTS idx_ratings_user ON ratings(user_id);
CREATE INDEX IF NOT EXISTS idx_ratings_movie ON ratings(movie_id);
CREATE INDEX IF NOT EXISTS idx_history_user ON watch_history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_movie ON watch_history(movie_id);

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_schema() -> None:
    """Create all tables / indexes if they don't already exist."""
    with connect() as conn:
        conn.executescript(SCHEMA)


def reset_schema() -> None:
    """Drop everything and recreate. Used by the seed script."""
    with connect() as conn:
        for stmt in (
            "DROP TABLE IF EXISTS watch_history;",
            "DROP TABLE IF EXISTS ratings;",
            "DROP TABLE IF EXISTS movies;",
            "DROP TABLE IF EXISTS users;",
            "DROP TABLE IF EXISTS app_state;",
        ):
            conn.execute(stmt)
        conn.executescript(SCHEMA)


# ---------- helpers ----------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ---------- user / auth ----------

def create_user(
    username: str,
    display_name: str,
    password_hash: str,
    role: str = "USER",
    geo_id: str | None = None,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, "
            "geo_id, registration_date) VALUES (?, ?, ?, ?, ?, ?)",
            (username, display_name, password_hash, role, geo_id, _now()),
        )
        return cur.lastrowid


def find_user_by_username(username: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return _row_to_dict(row)


def touch_last_login(user_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE user_id = ?",
            (_now(), user_id),
        )


def list_users(role: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if role:
            rows = conn.execute(
                "SELECT user_id, username, display_name, role, "
                "geo_id, registration_date, last_login_at "
                "FROM users WHERE role = ? ORDER BY username",
                (role,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT user_id, username, display_name, role, "
                "geo_id, registration_date, last_login_at "
                "FROM users ORDER BY role, username"
            ).fetchall()
        return rows_to_dicts(rows)


# ---------- movies (admin CRUD) ----------

def upsert_movie(
    movie_id: int,
    title: str,
    genres: str,
    release_year: int | None = None,
    content_rating: str | None = None,
    duration_min: int | None = None,
) -> None:
    """Insert or replace a movie. Used by both the seed script and the admin
    'add movie' form."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO movies (movie_id, title, genres, content_rating,
                                release_year, duration_min, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(movie_id) DO UPDATE SET
                title = excluded.title,
                genres = excluded.genres,
                content_rating = excluded.content_rating,
                release_year = excluded.release_year,
                duration_min = excluded.duration_min,
                last_updated = excluded.last_updated
            """,
            (movie_id, title, genres, content_rating, release_year,
             duration_min, _now()),
        )


def update_movie(movie_id: int, fields: dict[str, Any]) -> None:
    """Partial update by admin."""
    if not fields:
        return
    allowed = {"title", "genres", "content_rating", "release_year", "duration_min"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    safe["last_updated"] = _now()
    placeholders = ", ".join(f"{col} = :{col}" for col in safe.keys())
    safe["movie_id"] = movie_id
    with connect() as conn:
        conn.execute(f"UPDATE movies SET {placeholders} WHERE movie_id = :movie_id", safe)


def delete_movie(movie_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM movies WHERE movie_id = ?", (movie_id,))


def list_movies(
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    genre: str | None = None,
    sort_by: str = "title",
) -> list[dict[str, Any]]:
    """List movies with optional filters. Used by both user search and admin browse."""
    where = []
    params: list[Any] = []
    if search:
        where.append("title LIKE ?")
        params.append(f"%{search}%")
    if genre:
        where.append("genres LIKE ?")
        params.append(f"%{genre}%")
    where_clause = "WHERE " + " AND ".join(where) if where else ""

    order = {
        "title": "title ASC",
        "rating": "average_rating DESC, rating_count DESC",
        "year": "release_year DESC NULLS LAST",
        "popularity": "rating_count DESC",
    }.get(sort_by, "title ASC")

    sql = (
        f"SELECT movie_id, title, genres, content_rating, release_year, "
        f"average_rating, rating_count FROM movies {where_clause} "
        f"ORDER BY {order} LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return rows_to_dicts(rows)


def count_movies(search: str | None = None, genre: str | None = None) -> int:
    where = []
    params: list[Any] = []
    if search:
        where.append("title LIKE ?")
        params.append(f"%{search}%")
    if genre:
        where.append("genres LIKE ?")
        params.append(f"%{genre}%")
    where_clause = "WHERE " + " AND ".join(where) if where else ""
    with connect() as conn:
        n = conn.execute(f"SELECT COUNT(*) AS n FROM movies {where_clause}", params).fetchone()
        return int(n["n"])


def get_movie(movie_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM movies WHERE movie_id = ?", (movie_id,)
        ).fetchone()
        return _row_to_dict(row)


def get_popular_genres(limit: int = 10) -> list[dict[str, Any]]:
    """Aggregate genre counts and average ratings from the watch history + ratings tables."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.genres AS genres
            FROM movies m
            JOIN ratings r ON r.movie_id = m.movie_id
            """
        ).fetchall()
    counts: dict[str, dict[str, float]] = {}
    for row in rows:
        for g in row["genres"].split("|"):
            if not g:
                continue
            d = counts.setdefault(g, {"count": 0.0, "sum": 0.0})
            d["count"] += 1
    # simple popularity = number of ratings seen for movies with this genre
    out = [
        {"genre": g, "rating_count": int(v["count"])}
        for g, v in sorted(counts.items(), key=lambda kv: kv[1]["count"], reverse=True)
    ][:limit]
    return out


# ---------- ratings ----------

def add_rating(user_id: int, movie_id: int, score: float) -> int:
    """Persist a rating (replace any previous score for the same user+movie)."""
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO ratings (user_id, movie_id, score, timestamp)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, movie_id) DO UPDATE SET
                score = excluded.score,
                timestamp = excluded.timestamp
            """,
            (user_id, movie_id, score, _now()),
        )
        # update cached average
        avg = conn.execute(
            "SELECT AVG(score) AS avg, COUNT(*) AS cnt FROM ratings WHERE movie_id = ?",
            (movie_id,),
        ).fetchone()
        conn.execute(
            "UPDATE movies SET average_rating = ?, rating_count = ?, last_updated = ? "
            "WHERE movie_id = ?",
            (round(float(avg["avg"] or 0.0), 3), int(avg["cnt"]), _now(), movie_id),
        )
        return cur.lastrowid or 0


def list_ratings_by_user(user_id: int, limit: int = 200) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.rating_id, r.movie_id, r.score, r.timestamp,
                   m.title, m.genres, m.average_rating
            FROM ratings r
            JOIN movies m ON m.movie_id = r.movie_id
            WHERE r.user_id = ?
            ORDER BY r.timestamp DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return rows_to_dicts(rows)


# ---------- watch history ----------

def add_watch_event(
    user_id: int, movie_id: int, completion_pct: float, device: str = "web"
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO watch_history (user_id, movie_id, watched_at,
                                       completion_pct, device)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, movie_id, _now(), completion_pct, device),
        )
        return cur.lastrowid or 0


def list_history_by_user(user_id: int, limit: int = 200) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT h.event_id, h.movie_id, h.watched_at, h.completion_pct, h.device,
                   m.title, m.genres, m.average_rating
            FROM watch_history h
            JOIN movies m ON m.movie_id = h.movie_id
            WHERE h.user_id = ?
            ORDER BY h.watched_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return rows_to_dicts(rows)


# ---------- analytics ----------

def most_watched_movies(limit: int = 10, days: int | None = None) -> list[dict[str, Any]]:
    """Returns the most-watched movies in (optionally) the last N days."""
    where = ""
    params: list[Any] = []
    if days:
        # SQLite stores timestamps in 'YYYY-MM-DD HH:MM:SS' UTC, so use julianday
        # for a coarse cutoff.
        where = "WHERE julianday(h.watched_at) >= julianday('now', ?)"
        params.append(f"-{days} days")
    params.append(limit)
    sql = (
        f"""
        SELECT m.movie_id, m.title, m.genres, m.average_rating,
               COUNT(*) AS watches,
               AVG(h.completion_pct) AS avg_completion
        FROM watch_history h
        JOIN movies m ON m.movie_id = h.movie_id
        {where}
        GROUP BY m.movie_id
        ORDER BY watches DESC, avg_completion DESC
        LIMIT ?
        """
    )
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return rows_to_dicts(rows)


def engagement_over_time(days: int = 30) -> list[dict[str, Any]]:
    """Returns per-day event counts for the last N days."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT substr(watched_at, 1, 10) AS day, COUNT(*) AS events,
                   AVG(completion_pct) AS avg_completion
            FROM watch_history
            WHERE julianday(watched_at) >= julianday('now', ?)
            GROUP BY day
            ORDER BY day
            """,
            (f"-{days} days",),
        ).fetchall()
        return rows_to_dicts(rows)


def genre_popularity() -> list[dict[str, Any]]:
    """Counts ratings per genre across the catalogue."""
    with connect() as conn:
        rows = conn.execute("SELECT genres FROM movies").fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        for g in (r["genres"] or "").split("|"):
            g = g.strip()
            if not g:
                continue
            counts[g] = counts.get(g, 0) + 1
    return sorted(
        [{"genre": g, "movie_count": c} for g, c in counts.items()],
        key=lambda d: d["movie_count"],
        reverse=True,
    )


def app_state_get(key: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def app_state_set(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------- main entry ----------

if __name__ == "__main__":
    # Allows the file to be run as `python database.py` to bootstrap the schema
    # on a fresh checkout before the seed script is run.
    init_schema()
    print(f"Initialised schema at {db_path()}")
