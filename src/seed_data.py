"""seed_data.py — Populate the database from MovieLens small + demo accounts.

What it does
============
1. Resets the schema (drops + recreates all tables).
2. Reads ``data/ml-latest-small/movies.csv`` and inserts each film into the
   ``movies`` table. The release year is parsed out of the title
   (e.g. ``Toy Story (1995)``); content rating is left NULL (would come from
   the platform's catalog metadata).
3. Reads ``data/ml-latest-small/ratings.csv`` and imports the rating matrix.
   To make the recommender's behaviour observable on the demo accounts, the
   MovieLens user-id is remapped onto a fixed list of demo usernames
   (alice/bob/...) using ``userId % N``.
4. Creates an admin account (``admin`` / ``AdminPass!23``) and 5 demo user
   accounts with shared password ``Demo1234!``.
5. Bumps the cached ``average_rating`` and ``rating_count`` on every movie.

Run with::

    python seed_data.py

Re-running is safe — it resets the schema first.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import sys
from pathlib import Path

# ensure src/ is importable when run directly
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import database as db  # noqa: E402

DATA_DIR = _HERE.parent / "data" / "ml-latest-small"

DEMO_USERS = [
    # (username, display_name, role, geo)
    ("alice",   "Alice Tan",   "USER", "MY"),
    ("bob",     "Bob Lee",     "USER", "SG"),
    ("charlie", "Charly Wong", "USER", "MY"),
    ("dana",    "Dana Cruz",   "USER", "PH"),
    ("evan",    "Evan Park",   "USER", "US"),
]
DEMO_PASSWORD = "Demo1234!"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "AdminPass!23"


# ---------- helpers ----------

def _hash(password: str) -> str:
    """Lightweight password hashing for the demo. A production deployment
    should replace this with bcrypt / argon2 via passlib."""
    salt = "mrs-static-salt"
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


_YEAR_RE = re.compile(r"\((\d{4})\)\s*$")


def _parse_year(title: str) -> tuple[str, int | None]:
    """Strip the trailing ``(YYYY)`` from MovieLens titles."""
    m = _YEAR_RE.search(title)
    if not m:
        return title, None
    year = int(m.group(1))
    return title[: m.start()].strip(), year


# ---------- main ----------

def seed() -> dict[str, int]:
    if not DATA_DIR.exists():
        raise SystemExit(
            f"MovieLens data not found at {DATA_DIR}. "
            "Run scripts/download_data.py first or extract ml-latest-small.zip."
        )

    print(f"[seed] resetting schema at {db.db_path()}")
    db.reset_schema()

    # ---- demo accounts ----
    print("[seed] creating demo accounts")
    admin_uid = db.create_user(
        ADMIN_USERNAME, "System Admin", _hash(ADMIN_PASSWORD), role="ADMIN"
    )
    print(f"        admin uid={admin_uid}")
    demo_uids: dict[str, int] = {}
    for username, display, role, geo in DEMO_USERS:
        uid = db.create_user(
            username,
            display,
            _hash(DEMO_PASSWORD),
            role=role,
            geo_id=geo,
        )
        demo_uids[username] = uid
    print(f"        demo uids={demo_uids}")

    # ---- movies ----
    print("[seed] loading movies")
    movies_rows: list[tuple] = []
    n_movies = 0
    with (DATA_DIR / "movies.csv").open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            base_title, year = _parse_year(row["title"])
            movies_rows.append(
                (int(row["movieId"]), base_title,
                 row["genres"] or "(no genres listed)", None,
                 year, None, db._now())
            )
    with db.connect() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO movies
              (movie_id, title, genres, content_rating,
               release_year, duration_min, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            movies_rows,
        )
    n_movies = len(movies_rows)
    print(f"        inserted {n_movies} movies")

    # ---- ratings ----
    # Map MovieLens userId (1..610) -> demo account via modulo.
    print("[seed] loading ratings")
    usernames = list(demo_uids.keys())
    n_ratings = 0
    rows_buffer: list[tuple] = []
    with (DATA_DIR / "ratings.csv").open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            demo_index = (int(row["userId"]) - 1) % len(usernames)
            username = usernames[demo_index]
            uid = demo_uids[username]
            try:
                score = float(row["rating"])
            except ValueError:
                continue
            rows_buffer.append((uid, int(row["movieId"]), score, "2024-01-01 00:00:00"))
            if len(rows_buffer) >= 5_000:
                _bulk_insert_ratings(rows_buffer)
                n_ratings += len(rows_buffer)
                rows_buffer = []
        if rows_buffer:
            _bulk_insert_ratings(rows_buffer)
            n_ratings += len(rows_buffer)
    print(f"        inserted {n_ratings} ratings")

    # ---- refresh averages / counts ----
    print("[seed] refreshing movie aggregates")
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE movies
            SET average_rating = COALESCE((
                SELECT ROUND(AVG(score), 3) FROM ratings WHERE ratings.movie_id = movies.movie_id
            ), 0),
            rating_count = COALESCE((
                SELECT COUNT(*) FROM ratings WHERE ratings.movie_id = movies.movie_id
            ), 0)
            """
        )

    return {
        "movies": n_movies,
        "ratings": n_ratings,
        "demo_users": len(demo_uids),
    }


def _bulk_insert_ratings(rows: list[tuple]) -> None:
    """Insert rating rows directly, bypassing add_rating()'s per-row update
    of the cached average for performance during bulk import."""
    with db.connect() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO ratings (user_id, movie_id, score, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )


if __name__ == "__main__":
    counts = seed()
    print("\n[done]")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(
        "\nDemo accounts (password '{}' for users, '{}' for admin):".format(
            DEMO_PASSWORD, ADMIN_PASSWORD
        )
    )
    for u, _, _, _ in DEMO_USERS:
        print(f"  - {u}")
    print(f"  - {ADMIN_USERNAME}")
