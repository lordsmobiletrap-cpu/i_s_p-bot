"""
Database layer — connection management + repositories.

Provides:
- ``Database`` — manages aiosqlite connection and schema
- ``UserRepository`` — CRUD for the ``users`` table
- ``TopicRepository`` — CRUD for ``topics`` + ``user_topics``
- ``UserRecord`` — typed dataclass for a user row
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema SQL
# ---------------------------------------------------------------------------

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    free_attempts_used INTEGER DEFAULT 0,
    subscription_active BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_TOPICS_TABLE = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    category TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_USER_TOPICS_TABLE = """
CREATE TABLE IF NOT EXISTS user_topics (
    user_id INTEGER,
    topic_id INTEGER,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, topic_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
)
"""


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


@dataclass
class UserRecord:
    """Represents one row from the ``users`` table."""

    user_id: int
    free_attempts_used: int = 0
    subscription_active: bool = False
    created_at: str = ""


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------


class Database:
    """Manages a single aiosqlite connection.

    Usage::

        db = Database("ielts_bot.db")
        await db.connect()
        await db.init_schema()
        ...
        await db.close()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the connection and set pragmas."""
        self._conn = await aiosqlite.connect(self._db_path, timeout=30)
        await self._conn.execute("PRAGMA journal_mode=DELETE")
        logger.info("Database connected: %s", self._db_path)

    async def close(self) -> None:
        """Close the connection if open."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed.")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected. Call connect() first.")
        return self._conn

    async def init_schema(self) -> None:
        """Create all tables if they do not exist."""
        await self.conn.execute(CREATE_USERS_TABLE)
        await self.conn.execute(CREATE_TOPICS_TABLE)
        await self.conn.execute(CREATE_USER_TOPICS_TABLE)
        await self.conn.commit()
        logger.info("Database schema initialized.")


# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------


class UserRepository:
    """Repository for the ``users`` table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_or_create(self, user_id: int) -> UserRecord:
        """Ensure user exists and return their record."""
        db = self._db.conn
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        await db.commit()
        async with db.execute(
            "SELECT user_id, free_attempts_used, subscription_active, created_at "
            "FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        return UserRecord(
            user_id=row[0],
            free_attempts_used=row[1],
            subscription_active=bool(row[2]),
            created_at=row[3],
        )

    async def get_by_id(self, user_id: int) -> UserRecord | None:
        """Return user record or None."""
        async with self._db.conn.execute(
            "SELECT user_id, free_attempts_used, subscription_active, created_at "
            "FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return UserRecord(
            user_id=row[0],
            free_attempts_used=row[1],
            subscription_active=bool(row[2]),
            created_at=row[3],
        )

    async def get_all(
        self, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return a list of user dicts with pagination."""
        async with self._db.conn.execute(
            "SELECT user_id, free_attempts_used, subscription_active, created_at "
            "FROM users ORDER BY user_id LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "free_attempts_used": row[1],
                "subscription_active": bool(row[2]),
                "created_at": row[3],
            }
            for row in rows
        ]

    async def increment_attempts(self, user_id: int) -> None:
        """Increment ``free_attempts_used`` by 1."""
        await self._db.conn.execute(
            "UPDATE users SET free_attempts_used = free_attempts_used + 1 "
            "WHERE user_id = ?",
            (user_id,),
        )
        await self._db.conn.commit()

    async def set_subscription(self, user_id: int, active: bool) -> bool:
        """Set ``subscription_active``. Returns True if any row was updated."""
        cursor = await self._db.conn.execute(
            "UPDATE users SET subscription_active = ? WHERE user_id = ?",
            (1 if active else 0, user_id),
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    async def get_stats(self) -> dict[str, int]:
        """Return aggregate statistics."""
        db = self._db.conn
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()
            total_users = row[0] if row else 0
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_active = 1"
        ) as cur:
            row = await cur.fetchone()
            active_subs = row[0] if row else 0
        async with db.execute(
            "SELECT COALESCE(SUM(free_attempts_used), 0) FROM users"
        ) as cur:
            row = await cur.fetchone()
            total_attempts = row[0] if row else 0
        return {
            "total_users": total_users,
            "active_subs": active_subs,
            "total_attempts": total_attempts,
        }


# ---------------------------------------------------------------------------
# TopicRepository
# ---------------------------------------------------------------------------


class TopicRepository:
    """Repository for the ``topics`` and ``user_topics`` tables."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_random_unused(self, user_id: int) -> str | None:
        """Return text of a random topic not yet shown to the user, or None."""
        db = self._db.conn
        async with db.execute(
            """
            SELECT t.id, t.text FROM topics t
            WHERE t.id NOT IN (
                SELECT topic_id FROM user_topics WHERE user_id = ?
            )
            ORDER BY RANDOM() LIMIT 1
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        topic_id, topic_text = row
        await db.execute(
            "INSERT INTO user_topics (user_id, topic_id) VALUES (?, ?)",
            (user_id, topic_id),
        )
        await db.commit()
        return topic_text

    async def seed_from_list(self, questions: list[str]) -> int:
        """Insert questions that are not already in the DB.

        Returns the number of new rows inserted.
        """
        db = self._db.conn
        async with db.execute("SELECT text FROM topics") as cursor:
            existing = {row[0] for row in await cursor.fetchall()}

        new_questions = [q.strip() for q in questions if q.strip() not in existing]
        if not new_questions:
            return 0

        await db.executemany(
            "INSERT INTO topics (text) VALUES (?)",
            [(q,) for q in new_questions],
        )
        await db.commit()
        return len(new_questions)
